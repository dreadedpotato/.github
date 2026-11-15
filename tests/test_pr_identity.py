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
SAME_PR = (
    "Fix it on this same PR: edit the PR body or push the fix to this branch. "
    "Do not close and reopen a copy. Do not rerun CI without a change."
)
PROD_SELF_MERGE = (
    "Grader: self-merge is not allowed on a PROD repo (README says Repo tier: PROD). "
    "Fix: set Grader: Hester Quill (a named current seat) in the PR body and the commit trailers."
)
GOOD_BODY = (
    "For Dread: identity check\n"
    "Closes #3\n"
    "\n"
    "Doer: Lyska\n"
    "Grader: Hester Quill\n"
    "\n"
    "Problem: body rules\n"
    "Fix: enforce them\n"
    "Tested: pytest passed\n"
    "Not checked / Risk: none\n"
)
GOOD_MSG = "Update template\n\nDoer: Lyska\nGrader: Hester Quill\n"


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
    assert "CI_ALLOWED_EMAIL" in email_input["description"]
    assert "variable" in email_input["description"]
    assert email_input["default"] == ""
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
    assert step["env"]["ALLOWED_EMAIL"] == "${{ inputs.allowed-email || vars.CI_ALLOWED_EMAIL }}"
    assert step["env"]["EVENT_NAME"] == "${{ github.event_name }}"
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
    if where == "commit":
        return GOOD_BODY, f"Update template\n\n{bad}"
    body = GOOD_BODY.replace("Doer: Lyska\nGrader: Hester Quill\n", bad)
    return body, GOOD_MSG


def run_identity(
    tmp_path,
    script,
    body,
    commits,
    allowed=ALLOWED,
    head_override=None,
    event="pull_request",
    summary_path=None,
    readme="# Caller\nRepo tier: TEST\n",
    readme_name="README.md",
):
    repo = tmp_path / "repo"
    repo.mkdir()
    if readme is not None:
        (repo / readme_name).write_text(readme)
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
    assert proc.stdout.rstrip().endswith(SAME_PR), blob
    for line in proc.stdout.splitlines():
        if line.startswith("::error::"):
            assert "Fix:" in line, line


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
    assert SAME_PR not in proc.stdout


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
    message = "Update template\n\nGrader: Hester Quill\n"
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} needs a filled-in 'Doer:' line")


def test_two_grader_lines_fails(tmp_path, step_run):
    message = (
        "Update template\n\n"
        "Doer: Lyska\n"
        "Grader: Hester Quill\n"
        "Grader: Ines\n"
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
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, "Doer and Grader name the same seat")
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


def test_repo_ci_yml_has_no_hardcoded_identity():
    text = (ROOT / ".github" / "workflows" / "repo-ci.yml").read_text()
    assert "@users.noreply.github.com" not in text
    for banned in ("(Stream seat)", "(Shard seat)", "(Chief of Staff)"):
        assert banned not in text


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
    message = "Update template\n\ndoer: Lyska\nGrader: Hester Quill\n"
    proc, _head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout


def test_duplicate_doer_key_ignores_case(tmp_path, step_run):
    message = (
        "Update template\n\n"
        "Doer: Lyska\n"
        "doer: Hester Quill\n"
        "Grader: Ines\n"
    )
    proc, head = run_identity(tmp_path, step_run, GOOD_BODY, [{"message": message}])
    assert_fail(proc, f"commit {head[:7]} must have exactly one 'Doer:' line (found 2)")


def test_midline_doer_does_not_count(tmp_path, step_run):
    message = "Note: see Doer: Lyska\nGrader: Hester Quill\n"
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
    assert "Fix: set EVENT_NAME to pull_request or pull_request_target." in proc.stdout


def test_issue_link_inside_html_comment_does_not_count(tmp_path, step_run):
    body = "<!-- Closes #3 -->\n" + GOOD_BODY.replace("Closes #3\n", "")
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body must link an issue")


def body_with_lines(count, first="For Dread: length check"):
    rows = [
        first,
        "Closes #3",
        "Doer: Lyska",
        "Grader: Hester Quill",
        "Problem: length",
        "Fix: cap the body",
        "Tested: pytest passed",
        "Not checked / Risk: none",
    ]
    extra = 0
    while len(rows) < count:
        extra += 1
        rows.append(f"Note: extra {extra}")
    if len(rows) != count:
        raise AssertionError(len(rows))
    return "\n".join(rows) + "\n"


def assert_pass(proc):
    blob = proc.stdout + proc.stderr
    assert proc.returncode == 0, blob
    assert "PR identity ok" in proc.stdout
    assert "::error::" not in proc.stdout
    assert SAME_PR not in proc.stdout


@pytest.mark.parametrize("where", ["body", "commit"])
@pytest.mark.parametrize("grader", ["self-merge", "Self-Merge", "SELF-MERGE", "self-merge (no grade)"])
def test_self_merge_grader_passes(tmp_path, step_run, where, grader):
    if where == "body":
        body = GOOD_BODY.replace("Grader: Hester Quill\n", f"Grader: {grader}\n")
        message = GOOD_MSG
    else:
        body = GOOD_BODY
        message = f"Update template\n\nDoer: Lyska\nGrader: {grader}\n"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_pass(proc)


@pytest.mark.parametrize("name", ["Rei", "Priya", "Lyska Embervane"])
@pytest.mark.parametrize("where", ["body", "commit"])
@pytest.mark.parametrize("role", ["Doer", "Grader"])
def test_retired_names_fail(tmp_path, step_run, name, where, role):
    if role == "Doer":
        bad = f"Doer: {name}\nGrader: Hester Quill\n"
    else:
        bad = f"Doer: Lyska\nGrader: {name}\n"
    body, message = placed(where, bad)
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, f"{role} value {name!r} is not a current seat")


def test_twelve_nonblank_lines_pass(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path, step_run, body_with_lines(12), [{"message": GOOD_MSG}]
    )
    assert_pass(proc)


def test_thirteen_nonblank_lines_fail(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path, step_run, body_with_lines(13), [{"message": GOOD_MSG}]
    )
    assert_fail(proc, "PR body has 13 non-blank lines, more than 12")
    assert "Fix: delete non-blank lines until 12 or fewer remain." in proc.stdout


def test_html_comment_lines_do_not_count_toward_max(tmp_path, step_run):
    hidden = "\n".join(f"Hidden: {i}" for i in range(5))
    body = body_with_lines(12) + "<!--\n" + hidden + "\n-->\n"
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_pass(proc)


@pytest.mark.parametrize(
    "first",
    ["Hello", "For Dread:", "for dread: text", "  For Dread: text"],
)
def test_bad_for_dread_fails(tmp_path, step_run, first):
    body = first + "\n" + GOOD_BODY.split("\n", 1)[1]
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body first non-blank line does not match ^For Dread:\\s*\\S")
    assert "Fix: start the body with 'For Dread: <what this PR is>'." in proc.stdout


def test_leading_blank_lines_still_see_for_dread(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path, step_run, "\n\n" + GOOD_BODY, [{"message": GOOD_MSG}]
    )
    assert_pass(proc)


@pytest.mark.parametrize("tested_line", ["", "Tested:", "Tested:   "])
def test_missing_or_empty_tested_fails(tmp_path, step_run, tested_line):
    if tested_line == "":
        body = GOOD_BODY.replace("Tested: pytest passed\n", "")
    else:
        body = GOOD_BODY.replace("Tested: pytest passed", tested_line)
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_fail(proc, "PR body needs a Tested: line with non-empty text")
    assert "Fix: add a line 'Tested: <command you ran and the result>'." in proc.stdout


@pytest.mark.parametrize(
    "doer,grader",
    [
        ("Lyska", "Hester"),
        ("hester quill", "Sidony"),
        ("Sidony Quire", "Oralie"),
        ("calla", "Calla Wrenfield"),
        ("Ines", "ines varro"),
        ("Oralie", "Lyska"),
        ("Calla Wrenfield", "Ines Varro"),
        ("Hester", "Ines"),
        ("Sidony", "Calla"),
        ("\uff2cyska", "Hester Quill"),
        ("Lys\u200bka", "Hester"),
        ("Hester   Quill", "Ines"),
    ],
)
def test_current_seats_pass(tmp_path, step_run, doer, grader):
    body = GOOD_BODY.replace("Doer: Lyska\n", f"Doer: {doer}\n").replace(
        "Grader: Hester Quill\n", f"Grader: {grader}\n"
    )
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_pass(proc)


def test_parenthetical_seat_passes(tmp_path, step_run):
    body = GOOD_BODY.replace("Doer: Lyska\n", "Doer: Lyska (seat)\n").replace(
        "Grader: Hester Quill\n", "Grader: Hester (grade)\n"
    )
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": GOOD_MSG}])
    assert_pass(proc)


@pytest.mark.parametrize("where", ["body", "commit"])
def test_same_current_seat_fails(tmp_path, step_run, where):
    bad = "Doer: Lyska\nGrader: lyska\n"
    body, message = placed(where, bad)
    proc, head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, "Doer and Grader name the same seat")
    if where == "commit":
        assert f"commit {head[:7]}" in proc.stdout


def test_doer_self_merge_fails(tmp_path, step_run):
    bad = "Doer: self-merge\nGrader: self-merge\n"
    body, message = placed("body", bad)
    proc, _head = run_identity(tmp_path, step_run, body, [{"message": message}])
    assert_fail(proc, "Doer value 'self-merge' is not a current seat")
    assert "Doer and Grader name the same seat" not in proc.stdout


@pytest.mark.parametrize("readme_name", ["README.md", "README", "README.markdown", "readme.md"])
def test_prod_readme_body_self_merge_fails(tmp_path, step_run, readme_name):
    body = GOOD_BODY.replace("Grader: Hester Quill\n", "Grader: self-merge\n")
    proc, _head = run_identity(
        tmp_path,
        step_run,
        body,
        [{"message": GOOD_MSG}],
        readme="Repo tier: PROD\n",
        readme_name=readme_name,
    )
    assert_fail(proc, PROD_SELF_MERGE)


def test_prod_readme_commit_self_merge_fails(tmp_path, step_run):
    message = "Update template\n\nDoer: Lyska\nGrader: self-merge\n"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": message}],
        readme="Repo tier: PROD\n",
    )
    assert_fail(proc, PROD_SELF_MERGE)


@pytest.mark.parametrize("where", ["body", "commit"])
def test_test_readme_self_merge_passes(tmp_path, step_run, where):
    if where == "body":
        body = GOOD_BODY.replace("Grader: Hester Quill\n", "Grader: self-merge\n")
        message = GOOD_MSG
    else:
        body = GOOD_BODY
        message = "Update template\n\nDoer: Lyska\nGrader: self-merge\n"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        body,
        [{"message": message}],
        readme="Repo tier: TEST\n",
    )
    assert_pass(proc)


def test_prod_readme_named_grader_passes(tmp_path, step_run):
    proc, _head = run_identity(
        tmp_path,
        step_run,
        GOOD_BODY,
        [{"message": GOOD_MSG}],
        readme="Repo tier: PROD\n",
    )
    assert_pass(proc)


def test_ambiguous_tier_lines_self_merge_fails(tmp_path, step_run):
    body = GOOD_BODY.replace("Grader: Hester Quill\n", "Grader: self-merge\n")
    proc, _head = run_identity(
        tmp_path,
        step_run,
        body,
        [{"message": GOOD_MSG}],
        readme="Repo tier: TEST\nRepo tier: PROD\n",
    )
    assert_fail(proc, PROD_SELF_MERGE)


def test_missing_readme_self_merge_fails(tmp_path, step_run):
    body = GOOD_BODY.replace("Grader: Hester Quill\n", "Grader: self-merge\n")
    proc, _head = run_identity(
        tmp_path,
        step_run,
        body,
        [{"message": GOOD_MSG}],
        readme=None,
    )
    assert_fail(proc, PROD_SELF_MERGE)


@pytest.mark.parametrize("where", ["body", "commit"])
def test_missing_tier_line_self_merge_fails(tmp_path, step_run, where):
    if where == "body":
        body = GOOD_BODY.replace("Grader: Hester Quill\n", "Grader: self-merge\n")
        message = GOOD_MSG
    else:
        body = GOOD_BODY
        message = "Update template\n\nDoer: Lyska\nGrader: self-merge\n"
    proc, _head = run_identity(
        tmp_path,
        step_run,
        body,
        [{"message": message}],
        readme="# Caller\n",
    )
    assert_fail(proc, PROD_SELF_MERGE)
