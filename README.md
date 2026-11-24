# Org CI template

This repo holds the org's reusable CI template and issue forms.
Repo tier: TEST

## PR identity check

Every commit in the PR range and the PR body need exactly one `Doer:` line and one `Grader:` line. Grader may be `self-merge` for a TEST PR that needs no grade, and otherwise must differ from Doer. Self-merge is TEST only; PROD needs a named grader. Seats are matched after Unicode NFKC normalization, removing invisible format characters, collapsing spaces, and ignoring case. The key is case-insensitive, so `doer:` counts and a second one is a duplicate. Lines inside HTML comments in the PR body are ignored.

After those comments are stripped, the PR body must start with a non-blank line `For Dread:` plus text, stay within 12 non-blank lines, and include one `Tested:` line with non-empty text. Current seats come from seats.txt on main. A roster change is a one-line PR to seats.txt. When the caller repository is dreadedpotato/.github and seats.txt is in the checkout, the check reads that file so the roster PR checks itself. A first name alone is fine, and a trailing parenthetical is ignored. Grader may instead be exactly `self-merge`. Retired names, including Rei, Priya, and Lyska Embervane, fail. The body must link an issue in the same repo on its own line, `Issue: https://github.com/<owner>/<repo>/issues/<n>`, and must not use a closing keyword (`Close`, `Closes`, `Closed`, `Fix`, `Fixes`, `Fixed`, `Resolve`, `Resolves`, `Resolved` before an issue reference, even inside an HTML comment), so a merge never closes the issue before it is validated. The default PR template for org repos without their own is `.github/PULL_REQUEST_TEMPLATE.md`.

Every failure names the exact fix. A failing run ends with: Fix it on this same PR: edit the PR body or push the fix to this branch. Do not close and reopen a copy. Do not rerun CI without a change.

TEST PRs self-merge when CI is green, the PR-body check passes, and `Tested:` links live output for a visible change (`Grader: self-merge`). Risky PRs (PROD, CI, gates, checks, the template, PII, or secrets) need Hester's Grade: PASS first. PROD merges are Dread's.

Every commit author and committer email must equal allowed-email, so the check rejects commits made in the GitHub web editor, "Update branch" merge commits, and bot commits, because they carry other emails and no Doer/Grader trailers. A two-parent merge commit whose second parent is already reachable from the PR base (a main-into-PR sync) is exempt from the Doer/Grader trailer rule only when `git merge-tree --write-tree` of those parents exits 0 and the resulting tree equals the merge commit's tree. A conflict, a tree mismatch, an octopus merge, a missing or older-than-2.38 git, or any other failed merge-tree is not exempt. Author and committer email are still checked.

A PR whose head branch matches `poc/*` may name one commit already on that branch with a single line `Legacy through:` and a 40-character hex sha. Commits from the base through that sha skip the per-commit identity and email checks, and a notice reports how many were skipped. A second line, a value that is not 40 hex characters, a sha that is not an ancestor of the head, or any head branch outside `poc/*` is an error, and every commit after the named sha is still checked.

The check runs on pull_request and pull_request_target, and posts a notice and skips on other events like push. `allowed-email` reads `vars.CI_ALLOWED_EMAIL` from the caller repository or organization settings by default. `with:` inputs still override, and the check fails closed when it is empty.

## Calling this workflow

Each repo calls this reusable workflow from a short caller workflow. CI runs on every repo. Runners clean up after themselves. Read values from settings variables and do not hardcode them. Keep machine details out of caller READMEs. Callers must list `edited` in pull_request types so a body edit re-runs the body check, and wrap number variables in fromJSON:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
jobs:
  ci:
    uses: dreadedpotato/.github/.github/workflows/repo-ci.yml@<sha>
    with:
      runner: ${{ vars.CI_RUNNER_LABEL || 'ubuntu-latest' }}
      max-file-mb: ${{ fromJSON(vars.CI_MAX_FILE_MB || '10') }}
```

Checkout does not download Git LFS objects, so LFS files stay pointer files and pass the file-size check. The limit is an integer number of bytes, including when max-file-mb is a decimal such as 2.5.
