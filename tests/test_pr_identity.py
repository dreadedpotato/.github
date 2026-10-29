"""Execute the repo-ci pull request identity step from the workflow file."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEP_NAME = (
    "PR identity (linked issue; body and every commit: one Doer, one Grader, "
    "different seats; allowed commit email)"
)
SEATS = "Alpha (seat one), Beta (seat two)\nGamma (seat three)"
ALLOWED = "allowed@example.com"
OTHER = "other@example.com"
GOOD_BODY = "Closes #3\n\nDoer: Alpha (seat one)\nGrader: Beta (seat two)\n"
GOOD_MSG = "Update template\n\nDoer: Alpha (seat one)\nGrader: Beta (seat two)\n"


@pytest.fixture(scope="module")
def step_run():
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "repo-ci.yml").read_text())
    steps = data["jobs"]["repo-ci"]["steps"]
    checkout = steps[0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    trigger = data.get("on", data.get(True))
    email_input = trigger["workflow_call"]["inputs"]["allowed-email"]
    assert email_input["type"] == "string"
    assert "org/repo variable" in email_input["description"]
    assert isinstance(email_input["default"], str) and email_input["default"].strip()
    seats_input = trigger["workflow_call"]["inputs"]["allowed-seats"]
    assert seats_input["type"] == "string"
    assert isinstance(seats_input["default"], str) and seats_input["default"].strip()
    for block in (data["permissions"], data["jobs"]["repo-ci"]["permissions"]):
        assert "pull-requests" not in block
    matches = [step for step in steps if step.get("name") == STEP_NAME]
    assert len(matches) == 1
    step = matches[0]
    assert "if" not in step
    assert step["shell"] == "python3 {0}"
    assert step["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}"
    assert step["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert step["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert step["env"]["ALLOWED_EMAIL"] == "${{ inputs.allowed-email }}"
    assert step["env"]["EVENT_NAME"] == "${{ github.event_name }}"
    assert step["env"]["ALLOWED_SEATS"] == "${{ inputs.allowed-seats }}"
    assert "continue-on-error" not in step
    return step["run"]


def git_stdout(repo, *args):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def git(repo, *args, author=ALLOWED, committer=ALLOWED):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env["GIT_AUTHOR_NAME"] = "Alpha"
    env["GIT_COMMITTER_NAME"] = "Alpha"
    env["GIT_AUTHOR_EMAIL"] = author
    env["GIT_COMMITTER_EMAIL"] = committer
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Alpha",
            "-c",
            f"user.email={author}",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def head_sha(repo):
    return git_stdout(repo, "rev-parse", "HEAD").strip()


def placed(where, bad):
    good = "Doer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    if where == "commit":
        return f"Closes #3\n\n{good}", f"Update template\n\n{bad}"
    return f"Closes #3\n\n{bad}", f"Update template\n\n{good}"


def run_identity(
    tmp_path,
    script,
    body,
    commits,
    allowed=ALLOWED,
    head_override=None,
    event="pull_request",
    seats=SEATS,
    summary_path=None,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "commit", "--allow-empty", "-m", "base")
    base = head_sha(repo)
    branch = git_stdout(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    side_n = 0
    for commit in commits:
        author = commit.get("author", ALLOWED)
        committer = commit.get("committer", ALLOWED)
        if commit.get("merge"):
            side_n += 1
            side = f"side-{side_n}"
            git(repo, "checkout", "-b", side)
            git(
                repo,
                "commit",
                "--allow-empty",
                "-m",
                commit.get("side_message", GOOD_MSG),
                author=author,
                committer=committer,
            )
            git(repo, "checkout", branch)
            git(
                repo,
                "merge",
                "--no-ff",
                "-m",
                commit["message"],
                side,
                author=author,
                committer=committer,
            )
        else:
            git(
                repo,
                "commit",
                "--allow-empty",
                "-m",
                commit["message"],
                author=author,
                committer=committer,
            )
    head = head_override if head_override is not None else head_sha(repo)
    path = tmp_path / "pr_identity_step.py"
    path.write_text(script)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env["PR_BODY"] = body
    env["BASE_SHA"] = base
    env["HEAD_SHA"] = head
    if allowed is None:
        env.pop("ALLOWED_EMAIL", None)
    else:
        env["ALLOWED_EMAIL"] = allowed
    if event is None:
        env.pop("EVENT_NAME", None)
    else:
        env["EVENT_NAME"] = event
    if seats is None:
        env.pop("ALLOWED_SEATS", None)
    else:
        env["ALLOWED_SEATS"] = seats
    env.pop("GITHUB_STEP_SUMMARY", None)
    if summary_path is not None:
        env["GITHUB_STEP_SUMMARY"] = str(summary_path)
    proc = subprocess.run(
        ["python3", str(path)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc, head


def assert_fail(proc, needle):
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 1, blob
    assert "::error::" in proc.stdout, blob
    assert needle in proc.stdout, blob
    assert "PR identity ok" not in proc.stdout


def test_good_commit_passes(tmp_path, step_run):
    mixed = "Allowed@Example.com"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG, "author": mixed, "committer": mixed}],
        allowed=f"  {mixed}  ",
    )
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout


def test_bad_author_email_fails(tmp_path, step_run):
    proc, head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG, "author": OTHER, "committer": ALLOWED}],
    )
    assert_fail(proc, f"{head[:7]}: author email {OTHER!r} is not the allowed email {ALLOWED!r}")
    assert "committer email" not in proc.stdout


def test_bad_committer_email_fails(tmp_path, step_run):
    proc, head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG, "author": ALLOWED, "committer": OTHER}],
    )
    assert_fail(proc, f"{head[:7]}: committer email {OTHER!r} is not the allowed email {ALLOWED!r}")
    assert "author email" not in proc.stdout


def test_missing_doer_fails(tmp_path, step_run):
    message = "Update template\n\nGrader: Beta (seat two)\n"
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} needs a filled-in 'Doer:' line")


def test_two_grader_lines_fails(tmp_path, step_run):
    message = (
        "Update template\n\n"
        "Doer: Alpha (seat one)\n"
        "Grader: Beta (seat two)\n"
        "Grader: Beta (seat two)\n"
    )
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} must have exactly one 'Grader:' line (found 2)")


@pytest.mark.parametrize(
    "grader",
    [
        "Alpha (seat one)",
        "ALPHA (seat one)",
        "  alpha (seat one)  ",
    ],
)
@pytest.mark.parametrize("where", ["commit", "body"])
def test_doer_equals_grader_fails(tmp_path, step_run, grader, where):
    bad = f"Doer: Alpha (seat one)\nGrader: {grader}\n"
    good = "Doer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    if where == "commit":
        body = f"Closes #3\n\n{good}"
        message = f"Update template\n\n{bad}"
    else:
        body = f"Closes #3\n\n{bad}"
        message = f"Update template\n\n{good}"
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, "Doer and Grader name the same seat")
    if where == "commit":
        assert f"commit {head[:7]}" in proc.stdout


@pytest.mark.parametrize("where", ["commit", "body"])
def test_grader_alpha_seat_two_is_not_allowed(tmp_path, step_run, where):
    bad = "Doer: Alpha (seat one)\nGrader: Alpha (seat two)\n"
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    if where == "commit":
        label = f"commit {head[:7]}"
    else:
        label = "PR body"
    assert_fail(proc, f"{label} 'Grader:' value 'Alpha (seat two)' is not an allowed seat")
    assert "name the same seat" not in proc.stdout


@pytest.mark.parametrize(
    "body,needle",
    [
        ("", "PR body is empty"),
        ("   \n\t", "PR body is empty"),
        (
            "Closes #3\n\nDoer: Alpha (seat one)\n",
            "PR body needs a filled-in 'Grader:' line",
        ),
    ],
)
def test_bad_pr_body_fails(tmp_path, step_run, body, needle):
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, needle)


def test_zero_commits_fails(tmp_path, step_run):
    proc, _head = run_identity(tmp_path, step_run, GOOD_BODY, [])
    assert_fail(proc, "PR range contains zero commits")
    assert "Doer" not in proc.stdout


@pytest.mark.parametrize("allowed", [None, "", "   "])
def test_missing_allowed_email_fails(tmp_path, step_run, allowed):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG}],
        allowed=allowed,
    )
    assert_fail(proc, "ALLOWED_EMAIL is empty")


def test_missing_commit_sha_fails(tmp_path, step_run):
    missing = "deadbeef" * 5
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG}],
        head_override=missing,
    )
    assert_fail(proc, "git rev-list")
    assert missing in proc.stdout


def test_yml_default_seats_accept_rei_and_priya(tmp_path, step_run):
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "repo-ci.yml").read_text())
    trigger = data.get("on", data.get(True))
    seats = trigger["workflow_call"]["inputs"]["allowed-seats"]["default"]
    roles = "Doer: Rei (Stream seat)\nGrader: Priya (Shard seat)\n"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        f"Closes #3\n\n{roles}",
        [{"message": f"Update template\n\n{roles}"}],
        seats=seats,
    )
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout


@pytest.mark.parametrize(
    "grader",
    [
        pytest.param("Alpha.", id="rei-dot"),
        pytest.param("Alpha-2", id="rei-dash"),
        pytest.param("Alpha\u200b", id="zero-width"),
        pytest.param("\u0410lpha (seat one)", id="cyrillic"),
        pytest.param("TBD", id="tbd"),
        pytest.param("-", id="dash"),
        pytest.param("?", id="question"),
        pytest.param("<placeholder>", id="placeholder"),
        pytest.param("Alpha (seat one).", id="seat-dot"),
    ],
)
@pytest.mark.parametrize("where", ["commit", "body"])
def test_disguised_grader_is_not_allowed_seat(tmp_path, step_run, grader, where):
    bad = f"Doer: Alpha (seat one)\nGrader: {grader}\n"
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    if where == "commit":
        label = f"commit {head[:7]}"
    else:
        label = "PR body"
    assert_fail(proc, f"{label} 'Grader:' value {grader!r} is not an allowed seat")


@pytest.mark.parametrize(
    "grader",
    [
        "Al\u200bpha (seat one)",
        "\uff21lpha (seat one)",
        "ALPHA  (seat   one)",
    ],
)
@pytest.mark.parametrize("where", ["commit", "body"])
def test_normalized_grader_is_same_seat(tmp_path, step_run, grader, where):
    bad = f"Doer: Alpha (seat one)\nGrader: {grader}\n"
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    if where == "commit":
        label = f"commit {head[:7]}"
    else:
        label = "PR body"
    assert_fail(proc, f"{label} Doer and Grader name the same seat")


@pytest.mark.parametrize("where", ["commit", "body"])
def test_empty_grader_value_fails(tmp_path, step_run, where):
    bad = "Doer: Alpha (seat one)\nGrader:\n"
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    if where == "commit":
        label = f"commit {head[:7]}"
    else:
        label = "PR body"
    assert_fail(proc, f"{label} needs a filled-in 'Grader:' line")


def test_lowercase_doer_key_passes(tmp_path, step_run):
    message = "Update template\n\ndoer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    proc, _head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout


def test_duplicate_doer_key_ignores_case(tmp_path, step_run):
    message = (
        "Update template\n\n"
        "Doer: Alpha (seat one)\n"
        "doer: Gamma (seat three)\n"
        "Grader: Beta (seat two)\n"
    )
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} must have exactly one 'Doer:' line (found 2)")


def test_midline_doer_does_not_count(tmp_path, step_run):
    message = "Note: see Doer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} needs a filled-in 'Doer:' line")


def test_html_comment_extra_doer_is_ignored(tmp_path, step_run):
    body = GOOD_BODY + "<!--\nDoer: Gamma (seat three)\n-->"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout


def test_doer_only_inside_html_comment_fails(tmp_path, step_run):
    body = "Closes #3\n\n<!--\nDoer: Alpha (seat one)\n-->\nGrader: Beta (seat two)\n"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body needs a filled-in 'Doer:' line")


def test_unclosed_comment_after_good_lines_passes(tmp_path, step_run):
    body = GOOD_BODY + "<!-- Doer: Gamma (seat three)"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout


def test_unclosed_comment_before_doer_hides_it(tmp_path, step_run):
    body = "Closes #3\n\nGrader: Beta (seat two)\n<!-- Doer: Alpha (seat one)"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body needs a filled-in 'Doer:' line")


def test_merge_commit_without_trailers_fails(tmp_path, step_run):
    proc, head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"merge": True, "message": "Merge branch 'main' into feature"}],
    )
    shas = [
        line.strip()
        for line in git_stdout(tmp_path / "repo", "rev-list", "--reverse", "HEAD").splitlines()
        if line.strip()
    ]
    assert shas[-1] == head
    assert_fail(proc, f"commit {head[:7]} needs a filled-in 'Doer:' line")
    assert shas[-2][:7] not in proc.stdout


def test_merge_commit_with_trailers_passes(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"merge": True, "message": GOOD_MSG}],
    )
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout


def test_only_middle_commit_of_three_is_named(tmp_path, step_run):
    bad = "Update template\n\nDoer: TBD\nGrader: Beta (seat two)\n"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [
            {"message": GOOD_MSG},
            {"message": bad},
            {"message": GOOD_MSG},
        ],
    )
    shas = [
        line.strip()
        for line in git_stdout(tmp_path / "repo", "rev-list", "--reverse", "HEAD").splitlines()
        if line.strip()
    ]
    assert len(shas) == 4
    good_a, bad_sha, good_b = shas[1], shas[2], shas[3]
    assert_fail(proc, f"commit {bad_sha[:7]} 'Doer:' value 'TBD' is not an allowed seat")
    assert good_a[:7] not in proc.stdout
    assert good_b[:7] not in proc.stdout


def test_push_event_skips(tmp_path, step_run):
    summary = tmp_path / "summary.md"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        "",
        [],
        event="push",
        summary_path=summary,
    )
    line = "PR identity check not applicable to event 'push' (runs on pull_request and pull_request_target)"
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "::notice::" in proc.stdout
    assert "not applicable to event 'push'" in proc.stdout
    assert proc.stdout.strip() == f"::notice::{line}"
    assert summary.read_text(encoding="utf-8") == line + "\n"


def test_pull_request_target_checks_body(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        "",
        [{"message": GOOD_MSG}],
        event="pull_request_target",
    )
    assert_fail(proc, "PR body is empty")


def test_missing_event_name_fails(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG}],
        event=None,
    )
    assert_fail(proc, "EVENT_NAME is empty")
    assert proc.stdout.strip() == "::error::EVENT_NAME is empty"


@pytest.mark.parametrize("seats", [None, "", " , \n "])
def test_empty_allowed_seats_fails(tmp_path, step_run, seats):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG}],
        seats=seats,
    )
    assert_fail(proc, "ALLOWED_SEATS is empty")


def test_issue_link_inside_html_comment_does_not_count(tmp_path, step_run):
    body = "<!-- Closes #3 -->\nDoer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body must link an issue")
