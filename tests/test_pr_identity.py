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
    matches = [step for step in steps if step.get("name") == STEP_NAME]
    assert len(matches) == 1
    step = matches[0]
    assert step["if"] == "github.event_name == 'pull_request'"
    assert step["shell"] == "python3 {0}"
    assert step["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}"
    assert step["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert step["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert step["env"]["ALLOWED_EMAIL"] == "${{ inputs.allowed-email }}"
    assert "continue-on-error" not in step
    return step["run"]


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
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def run_identity(tmp_path, script, body, commits, allowed=ALLOWED, head_override=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "commit", "--allow-empty", "-m", "base")
    base = head_sha(repo)
    for commit in commits:
        git(
            repo,
            "commit",
            "--allow-empty",
            "-m",
            commit["message"],
            author=commit.get("author", ALLOWED),
            committer=commit.get("committer", ALLOWED),
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
    assert "Doer and Grader must be different seats" in proc.stdout
    if where == "commit":
        assert f"commit {head[:7]}" in proc.stdout


@pytest.mark.parametrize("where", ["commit", "body"])
def test_same_first_token_fails(tmp_path, step_run, where):
    bad = "Doer: Alpha (seat one)\nGrader: Alpha (seat two)\n"
    good = "Doer: Alpha (seat one)\nGrader: Beta (seat two)\n"
    if where == "commit":
        body = f"Closes #3\n\n{good}"
        message = f"Update template\n\n{bad}"
    else:
        body = f"Closes #3\n\n{bad}"
        message = f"Update template\n\n{good}"
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, "Doer and Grader must be different seats")
    assert "name the same seat" not in proc.stdout
    if where == "commit":
        assert f"commit {head[:7]}" in proc.stdout


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
