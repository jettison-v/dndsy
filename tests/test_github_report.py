"""What GitHub tells askdnd about the pull requests (scripts/github_report.py, run by .github/workflows/report.yml; item
39): the tests' state, which waiting pull requests it brings up to date with main, and the whole list it sends. GitHub
and askdnd are stand-ins here: nothing reaches either."""

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
    state = {"prs": [], "calls": [], "sent": None, "fail": set()}

    def gh(*args):
        state["calls"].append(args)
        if args[:2] == ("pr", "list"):
            return json.dumps(state["prs"])
        if args[0] == "api" and any(f"/pulls/{n}/" in a for n in state["fail"] for a in args):
            raise gr.subprocess.CalledProcessError(1, "gh", stderr="merge conflict")
        return ""

    monkeypatch.setattr(gr, "gh", gh)
    monkeypatch.setattr(gr, "send", lambda rows, key: state.__setitem__("sent", rows))
    monkeypatch.setattr(gr.time, "sleep", lambda s: None)
    monkeypatch.setenv("FFT_GITHUB_KEY", "k" * 40)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    def run(event, payload=None):
        path = tmp_path / "event.json"
        path.write_text(json.dumps(payload or {}))
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
        gr.main()
        return state

    state["run"] = run
    return state


def test_after_main_moves_a_waiting_pull_request_is_brought_up_to_date_and_retested(github):
    """Only one set to merge by itself and behind main: main is merged in at the commit GitHub showed, its tests start
    again (an update made with GitHub's own token starts none), and askdnd hears it's running again."""
    github["prs"] = [_pr(1, autoMergeRequest={"enabledAt": "x"}, mergeStateStatus="BEHIND"),
                     _pr(2, mergeStateStatus="BEHIND"),  # (not set to merge by itself: left as it is)
                     _pr(3, autoMergeRequest={"enabledAt": "x"}, mergeStateStatus="CLEAN")]
    got = github["run"]("push")
    updates = [c for c in got["calls"] if c[0] == "api"]
    assert updates == [("api", "-X", "PUT", "repos/owner/repo/pulls/1/update-branch", "-f", "expected_head_sha=" + "b" * 40)]
    assert ("workflow", "run", "tests.yml", "--ref", "branch-1") in got["calls"]
    sent = {r["number"]: r for r in got["sent"]}
    assert sent[1]["updated"] is True and sent[1]["tests"] == "running"
    assert "updated" not in sent[2] and sent[2]["merge_state"] == "behind"


def test_one_that_conflicts_is_left_for_claude_and_the_rest_still_report(github):
    github["prs"] = [_pr(1, autoMergeRequest={"x": 1}, mergeStateStatus="BEHIND"), _pr(2)]
    github["fail"] = {1}
    got = github["run"]("push")
    assert not any(c[:2] == ("workflow", "run") for c in got["calls"])
    assert [r["number"] for r in got["sent"]] == [1, 2] and "updated" not in got["sent"][0]


def test_nothing_is_brought_up_to_date_on_a_test_run_or_a_pull_requests_own_push(github):
    """Only when main moves, or auto-merge is turned on: a run that merges main in starts runs that would start it again."""
    github["prs"] = [_pr(1, autoMergeRequest={"x": 1}, mergeStateStatus="BEHIND")]
    for event, payload in (("workflow_run", {"action": "completed"}), ("pull_request_target", {"action": "synchronize"})):
        github["calls"].clear()
        assert not [c for c in github["run"](event, payload)["calls"] if c[0] == "api"]
    github["calls"].clear()
    assert [c for c in github["run"]("pull_request_target", {"action": "auto_merge_enabled"})["calls"] if c[0] == "api"]


def test_a_closed_one_is_reported_merged_or_closed_and_forks_are_left_out(github):
    """The one just closed isn't on the open list: it's added, merged or not. A pull request from a fork isn't ours."""
    github["prs"] = [_pr(5), _pr(6, isCrossRepository=True)]
    closed = {"number": 4, "title": "Done", "merged": True, "user": {"login": "dependabot[bot]", "type": "Bot"},
              "head": {"ref": "dependabot/uv/x", "sha": "c" * 40, "repo": {"fork": False}}}
    got = github["run"]("pull_request_target", {"action": "closed", "pull_request": closed})
    assert [(r["number"], r["state"]) for r in got["sent"]] == [(5, "open"), (4, "merged")]
    assert got["sent"][1]["by_bot"] is True and "tests" not in got["sent"][1]
    forked = closed | {"number": 7, "head": closed["head"] | {"repo": {"fork": True}}}
    assert [r["number"] for r in github["run"]("pull_request_target", {"action": "closed", "pull_request": forked})["sent"]] == [5]


def test_without_its_key_it_sends_nothing(github, monkeypatch):
    monkeypatch.delenv("FFT_GITHUB_KEY")
    github["prs"] = [_pr(1)]
    assert github["run"]("push")["sent"] is None


def test_dependabots_are_marked_as_a_bots():
    assert gr.row(_pr(1, author={"login": "app/dependabot", "is_bot": True}))["by_bot"] is True
    assert gr.row(_pr(1))["by_bot"] is False
