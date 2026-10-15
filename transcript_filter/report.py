"""Write the filtered transcript and a local HTML review page."""

import html
import json
from pathlib import Path

from transcript_filter.segments import Segment, format_time


def stats(segments: list[Segment]) -> dict:
    def words(pred):
        return sum(s.words for s in segments if pred(s))

    total = words(lambda s: True)
    echo = words(lambda s: s.removed_by == "echo")
    off = words(lambda s: s.removed_by == "off_topic")
    kept = words(lambda s: s.kept)
    return {
        "segments_total": len(segments),
        "segments_kept": sum(s.kept for s in segments),
        "words_total": total,
        "words_echo": echo,
        "words_off_topic": off,
        "words_kept": kept,
        "pct_echo": round(100 * echo / total, 1) if total else 0,
        "pct_off_topic": round(100 * off / total, 1) if total else 0,
        "pct_kept": round(100 * kept / total, 1) if total else 0,
    }


def write_filtered(segments: list[Segment], json_path: Path, txt_path: Path) -> None:
    kept = [s for s in segments if s.kept]
    json_path.write_text(
        json.dumps(
            [
                {"start": round(s.start, 3), "end": round(s.end, 3), "speaker": s.speaker, "text": s.text}
                for s in kept
            ],
            indent=1,
            ensure_ascii=False,
        )
    )
    txt_path.write_text(
        "\n".join(f"[{format_time(s.start)}] {s.speaker or 'Unknown'}: {s.text}" for s in kept) + "\n"
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Filter review: {title}</title>
<style>
body {{ font: 15px/1.45 system-ui, sans-serif; max-width: 60rem; margin: 2rem auto; padding: 0 1rem; color: #222; background: #fafaf7; }}
.stats {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: .75rem 1rem; }}
.controls {{ position: sticky; top: 0; background: #fafaf7; padding: .5rem 0; border-bottom: 1px solid #ddd; z-index: 1; }}
.line {{ display: flex; gap: .6rem; padding: 1px 0; }}
.t {{ color: #999; font-variant-numeric: tabular-nums; flex: none; width: 4.5rem; }}
.who {{ color: #557; flex: none; width: 7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.cut {{ background: #fde8e8; border-left: 4px solid #c33; margin: .6rem 0; padding: .3rem .5rem; }}
.cut > .reason {{ font-weight: 600; color: #a22; margin-bottom: .2rem; }}
.unchecked {{ background: #fff6d6; }}
.echo {{ color: #aaa; text-decoration: line-through; }}
body.hide-echo .echo {{ display: none; }}
body.only-cuts .keep {{ display: none; }}
</style></head>
<body class="hide-echo">
<h1>Filter review: {title}</h1>
<div class="stats">
<b>Model:</b> {model} &middot; <b>Kept:</b> {pct_kept}% of {words_total:,} words &middot;
<b>Echo removed:</b> {pct_echo}% &middot; <b>Off-topic removed:</b> {pct_off_topic}% ({n_cuts} stretches)
<p>Red boxes were cut as off-topic. Check that none of them contain game content, and that nothing off-topic was left in.
Yellow lines ({n_unchecked}) couldn't be checked by the model and were kept; review them by hand.</p>
</div>
<div class="controls">
<label><input type="checkbox" id="echo" autocomplete="off"> Show echo duplicates</label> &nbsp;
<label><input type="checkbox" id="cuts" autocomplete="off"> Show only cut stretches</label>
</div>
{body}
<script>
const echoBox = document.getElementById('echo'), cutsBox = document.getElementById('cuts');
function sync() {{
  document.body.classList.toggle('hide-echo', !echoBox.checked);
  document.body.classList.toggle('only-cuts', cutsBox.checked);
}}
echoBox.addEventListener('change', sync);
cutsBox.addEventListener('change', sync);
window.addEventListener('pageshow', sync);  // Safari restores checkbox state on reload/back
sync();
</script>
</body></html>
"""


def _line(s: Segment, cls: str) -> str:
    return (
        f'<div class="line {cls}"><span class="t">{format_time(s.start)}</span>'
        f'<span class="who">{html.escape(s.speaker or "Unknown")}</span>'
        f"<span>{html.escape(s.text)}</span></div>"
    )


def write_review(segments: list[Segment], path: Path, title: str, model: str) -> None:
    out, cut, n_cuts = [], [], 0

    def flush():
        nonlocal n_cuts
        if cut:
            n_cuts += 1
            reasons = dict.fromkeys(s.reason for s in cut if s.removed_by == "off_topic" and s.reason)
            first, last = cut[0], cut[-1]
            out.append(
                f'<div class="cut"><div class="reason">Cut {format_time(first.start)}–{format_time(last.end)}: '
                f'{html.escape("; ".join(reasons) or "off-topic")}</div>'
                + "".join(_line(s, "echo" if s.removed_by == "echo" else "") for s in cut)
                + "</div>"
            )
            cut.clear()

    for s in segments:
        if s.removed_by == "off_topic":
            cut.append(s)
        elif s.removed_by == "echo":
            (cut if cut else out).append(s if cut else _line(s, "echo keep"))
        else:
            flush()
            out.append(_line(s, "keep unchecked" if s.extra.get("unchecked") else "keep"))
    flush()
    path.write_text(PAGE.format(title=html.escape(title), model=html.escape(model), body="\n".join(out), n_cuts=n_cuts, n_unchecked=sum(1 for s in segments if s.extra.get("unchecked")), **stats(segments)))
