"""What GitHub tells askdnd about the pull requests (scripts/github_report.py, run by .github/workflows/report.yml; item
39): the tests' state and the whole list it sends, changing nothing on GitHub. GitHub and askdnd are stand-ins here:
nothing reaches either."""

import json

import pytest

from scripts import github_report as gr


def _pr(n, **kw):
    return {"number": n, "title": f"Pull {n}", "headRefName": f"branch-{n}", "author": {"login": "someone", "is_bot": False},
            "isCrossRepository": False, "autoMergeRequest": None, "mergeStateStatus": "BLOCKED", "headRefOid": "b" * 40,
            "statusCheckRollup": []} | kw


def _check(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


@pytest.mark.parametrize(("rollup", "want"), [
    ([], ""),
    ([_check("Server tests"), _check("Browser tests")], "passed"),
    ([_check("Server tests"), _check("Browser tests", "IN_PROGRESS", "")], "running"),
    ([_check("Server tests", conclusion="FAILURE"), _check("Browser tests", "IN_PROGRESS", "")], "failed"),
    ([_check("Server tests"), _check("Browser tests"), _check("Game-night freeze", conclusion="FAILURE")], "passed"),
    ([_check("Server tests", conclusion="CANCELLED"), _check("Browser tests", conclusion="CANCELLED")], ""),
    ([_check("CodeQL", conclusion="FAILURE")], ""),
], ids=["none", "both-passed", "one-running", "one-failed", "freeze-isnt-a-test", "cancelled", "other-checks"])
def test_the_tests_state_reads_only_the_checks_main_asks_for(rollup, want):
    """A pause fails the freeze job, not the tests: it never makes a pull request look red (issue 110's pause)."""
    assert gr.tests_of(rollup) == want


@pytest.fixture
def github(monkeypatch, tmp_path):
    """A stand-in GitHub: the open pull requests `gh pr list` gives, and every other `gh` call recorded."""
    state = {"prs": [], "closed": [], "calls": [], "sent": None, "down": False}

    def gh(*args):
        state["calls"].append(args)
        if state["down"]:
            raise gr.subprocess.CalledProcessError(1, "gh", stderr="HTTP 502")
        if args[:2] == ("pr", "list"):
            return json.dumps(state["closed"] if "closed" in args else state["prs"])
        return ""

    monkeypatch.setattr(gr, "gh", gh)
    monkeypatch.setattr(gr, "send", lambda rows, key: state.__setitem__("sent", rows))
    monkeypatch.setattr(gr.time, "sleep", lambda s: None)
    monkeypatch.setenv("FFT_GITHUB_KEY", "k" * 40)

    def run(event, payload=None):
        path = tmp_path / "event.json"
        path.write_text(json.dumps(payload or {}))
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
        gr.main()
        return state

    state["run"] = run
    return state


def test_it_only_reads_github_and_a_waiting_one_behind_main_is_reported_as_behind(github):
    """Nov 24 (#485): runs GitHub's own robot starts wait for a person's approval, so the report changes nothing on
    GitHub; one set to merge by itself that's behind main reaches askdnd as behind (a gap for Claude, views `pull_behind`)."""
    github["prs"] = [_pr(1, autoMergeRequest={"enabledAt": "x"}, mergeStateStatus="BEHIND"), _pr(2, mergeStateStatus="BEHIND")]
    for event, payload in (("push", {}), ("workflow_run", {"action": "completed"}), ("pull_request_target", {"action": "synchronize"})):
        got = github["run"](event, payload)
        assert all(c[:2] in (("pr", "list"),) for c in got["calls"]), got["calls"]
        sent = {r["number"]: r for r in got["sent"]}
        assert (sent[1]["merge_state"], sent[1]["auto_merge"]) == ("behind", True) and "updated" not in sent[1]


def test_it_waits_while_github_still_works_out_behind(github, monkeypatch):
    slept = []
    monkeypatch.setattr(gr.time, "sleep", slept.append)
    github["prs"] = [_pr(1, autoMergeRequest={"x": 1}, mergeStateStatus="UNKNOWN")]
    github["run"]("push")
    assert len(slept) == 2 and sum(1 for c in github["calls"] if c[:2] == ("pr", "list") and "open" in c) == 3


def test_how_the_last_few_closed_ones_ended_is_reported_and_closed_wins(github):
    """The one just closed is added, merged or not, from the event; every run also reports the last few closed ones, so a
    replaced run's close isn't lost. One still listed open after it closed counts as closed. Forks aren't ours."""
    github["prs"] = [_pr(5), _pr(4), _pr(6, isCrossRepository=True)]
    github["closed"] = [_pr(3, mergedAt="2026-11-24T01:00:00Z", closedAt="2026-11-24T01:00:00Z"), _pr(2, closedAt="2026-11-23T09:00:00Z"),
                        _pr(8, isCrossRepository=True, closedAt="2026-11-23T09:00:00Z")]
    closed = {"number": 4, "title": "Done", "merged": True, "closed_at": "2026-11-24T02:00:00Z", "user": {"login": "dependabot[bot]", "type": "Bot"},
              "head": {"ref": "dependabot/uv/x", "sha": "c" * 40, "repo": {"fork": False}}}
    got = {r["number"]: r for r in github["run"]("pull_request_target", {"action": "closed", "pull_request": closed})["sent"]}
    assert {n: r["state"] for n, r in got.items()} == {5: "open", 4: "merged", 3: "merged", 2: "closed"}
    assert got[4]["by_bot"] is True and "tests" not in got[4] and got[4]["closed_at"] == "2026-11-24T02:00:00Z"
    assert got[3]["closed_at"] == "2026-11-24T01:00:00Z" and "auto_merge" not in got[2]
    forked = closed | {"number": 7, "head": closed["head"] | {"repo": {"fork": True}}}
    assert 7 not in {r["number"] for r in github["run"]("pull_request_target", {"action": "closed", "pull_request": forked})["sent"]}


def test_github_out_of_reach_is_a_warning_not_a_failed_run(github, capsys):
    """A failed run emails Brett: a report problem only warns, and the next run sends everything again."""
    github["down"] = True
    assert github["run"]("push")["sent"] is None
    assert "::warning::" in capsys.readouterr().out


def test_askdnd_out_of_reach_is_a_warning_too(monkeypatch, capsys):
    import http.client

    def boom(*a, **k):
        raise http.client.RemoteDisconnected("closed")

    monkeypatch.setattr(gr.urllib.request, "urlopen", boom)
    gr.send([{"number": 1}], "k" * 40)
    assert "::warning::" in capsys.readouterr().out


def test_without_its_key_it_sends_nothing(github, monkeypatch):
    monkeypatch.delenv("FFT_GITHUB_KEY")
    github["prs"] = [_pr(1)]
    assert github["run"]("push")["sent"] is None


def test_dependabots_are_marked_as_a_bots():
    assert gr.row(_pr(1, author={"login": "app/dependabot", "is_bot": True}))["by_bot"] is True
    assert gr.row(_pr(1))["by_bot"] is False


def test_a_merged_ones_merge_commit_is_sent_and_a_closed_ones_isnt(github):
    """askdnd finds what's inside the version it runs by the merge commit (rules.release_live)."""
    github["closed"] = [_pr(3, mergedAt="2026-11-24T01:00:00Z", closedAt="2026-11-24T01:00:00Z", mergeCommit={"oid": "d" * 40}),
                        _pr(2, closedAt="2026-11-23T09:00:00Z", mergeCommit=None)]
    got = {r["number"]: r for r in github["run"]("push")["sent"]}
    assert got[3]["merge_commit"] == "d" * 40 and "merge_commit" not in got[2]
    closed = {"number": 4, "title": "Done", "merged": True, "merge_commit_sha": "e" * 40, "closed_at": "2026-11-24T02:00:00Z",
              "user": {"login": "someone", "type": "User"}, "head": {"ref": "a17-x", "sha": "c" * 40, "repo": {"fork": False}}}
    assert {r["number"]: r for r in github["run"]("pull_request_target", {"action": "closed", "pull_request": closed})["sent"]}[4]["merge_commit"] == "e" * 40
