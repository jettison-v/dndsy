import json

from transcript_filter.classify import apply_labels, build_prompt, classify, smooth_and_cut
from transcript_filter.dedup import containment, remove_echo, tokens
from transcript_filter.report import stats
from transcript_filter.segments import Segment, load_macwhisper, parse_range, parse_time


def seg(i, start, end, text, speaker="A"):
    return Segment(index=i, start=start, end=end, speaker=speaker, text=text)


def test_parse_time_formats():
    assert parse_time("00:19.119") == 19.119
    assert parse_time("1:02:03.5") == 3723.5
    assert parse_range("59:59.000-01:00:01.000") == (3599.0, 3601.0)


def test_load_macwhisper_handles_missing_speaker(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps([
        {"text": "b", "timestamp": "00:02.000-00:03.000"},
        {"speaker": "DM", "text": " a ", "timestamp": "00:01.000-00:02.000"},
    ]))
    segments = load_macwhisper(path)
    assert [s.text for s in segments] == ["a", "b"]  # sorted by start, stripped
    assert segments[1].speaker is None


def test_containment_counts_repeats():
    assert containment(tokens("yeah yeah"), tokens("yeah okay")) == 0.5
    assert containment(tokens("All that stuff, right?"), tokens("wages, all that stuff right")) == 1.0


def test_echo_fragments_removed_longest_kept():
    segments = [
        seg(0, 19.1, 20.2, "Wages, medical", speaker=None),
        seg(1, 19.2, 22.1, "Wages, medical, all that stuff, right?"),
        seg(2, 20.9, 22.1, "All that stuff, right?", speaker=None),
    ]
    assert remove_echo(segments) == 2
    assert [s.kept for s in segments] == [False, True, False]


def test_exact_echo_drops_later_copy():
    segments = [seg(0, 22.0, 23.0, "Yeah.", speaker=None), seg(1, 22.0, 22.8, "Yeah.")]
    remove_echo(segments)
    assert [s.kept for s in segments] == [True, False]


def test_reworded_echo_with_long_same_order_run_is_removed():
    segments = [
        seg(0, 22.0, 24.0, "So like I've it's a 85% chance on those."),
        seg(1, 22.5, 24.0, "you know 85% chance on those.", speaker="B"),
    ]
    assert remove_echo(segments) == 1
    assert not segments[1].kept


def test_reply_sharing_a_few_words_is_kept():
    segments = [
        seg(0, 18.0, 19.0, "Is that an evocation?"),
        seg(1, 18.5, 20.0, "It's an evocation spell.", speaker="B"),
    ]
    assert remove_echo(segments) == 0


def test_repeated_words_far_apart_are_kept():
    segments = [seg(0, 10, 11, "Roll initiative."), seg(1, 300, 301, "Roll initiative.")]
    assert remove_echo(segments) == 0


def test_different_words_overlapping_are_kept():
    segments = [seg(0, 10, 12, "The door is locked."), seg(1, 10.5, 12, "I pick the lock.")]
    assert remove_echo(segments) == 0


def test_apply_labels_defaults_to_game():
    block = [seg(i, i, i + 1, f"line {i}") for i in range(4)]
    apply_labels(block, 1, [{"n": 1, "label": "table_talk"}, {"n": 3, "label": "nonsense"}, {"n": "x"}])
    assert [s.extra["label"] for s in block] == ["table_talk", "game", "game", "game"]


def labeled(labels, text="some words here"):
    segments = [seg(i, i, i + 1, text) for i in range(len(labels))]
    for s, label in zip(segments, labels):
        s.extra["label"] = {"g": "game", "t": "table_talk"}[label]
    return segments


def test_smoothing_absorbs_short_filler_into_table_talk():
    segments = labeled("ttttgtttt", text="yeah")
    assert smooth_and_cut(segments) == 9


def test_short_table_talk_inside_game_is_kept():
    segments = labeled("ggggtggggttgggg")
    assert smooth_and_cut(segments) == 0


def test_long_game_run_inside_table_talk_survives():
    segments = labeled("ttttggggtttt")
    assert smooth_and_cut(segments) == 8
    assert [s.kept for s in segments[4:8]] == [True] * 4


def test_build_prompt_numbers_only_the_block():
    context = [seg(0, 0, 1, "earlier")]
    block = [seg(1, 1, 2, "first"), seg(2, 2, 3, "second")]
    prompt = build_prompt(context, block, 1)
    assert "1. [0:00:01] A: first" in prompt
    assert "2. [0:00:02] A: second" in prompt
    assert "- [0:00:00] A: earlier" in prompt


def test_classify_skips_echo_and_cuts_table_talk():
    segments = [seg(i, i * 10, i * 10 + 1, f"line {i}") for i in range(10)]
    segments[0].removed_by = "echo"
    seen = []

    def fake_ask(system, user, schema):
        seen.append(user)
        return {"lines": [{"n": n, "label": "table_talk" if n <= 5 else "game"} for n in range(1, 10)]}

    assert classify(segments, fake_ask) == 5
    assert "line 0" not in seen[0].split("Lines to check")[1]
    assert [s.removed_by for s in segments[1:6]] == ["off_topic"] * 5
    assert all(s.kept for s in segments[6:])


def test_stats_percentages():
    segments = [seg(0, 0, 1, "a b c d"), seg(1, 1, 2, "e f"), seg(2, 2, 3, "g h i j")]
    segments[1].removed_by = "echo"
    segments[2].removed_by = "off_topic"
    s = stats(segments)
    assert (s["words_total"], s["words_kept"], s["pct_echo"], s["pct_off_topic"]) == (10, 4, 20.0, 40.0)


def test_failed_block_is_split_then_flagged():
    segments = [seg(i, i * 10, i * 10 + 1, f"line {i}") for i in range(30)]
    calls = []

    def flaky_ask(system, user, schema):
        calls.append(user)
        if "line 0" in user.split("Lines to check")[1]:
            raise TimeoutError
        return {"lines": []}

    classify(segments, flaky_ask)
    unchecked = [s.index for s in segments if s.extra.get("unchecked")]
    assert unchecked == list(range(15))  # first half failed again; second half checked
    assert all(s.kept for s in segments)
    assert len(calls) == 3


def test_cache_round_trip(tmp_path):
    from transcript_filter.cache import Cache

    path = tmp_path / "c.json"
    cache = Cache(path)
    cache[Cache.key("a", "b")] = {"off_topic": []}
    assert Cache(path)[Cache.key("a", "b")] == {"off_topic": []}
