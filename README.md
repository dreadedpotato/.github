# Org CI template

This repo holds the org's reusable CI template and issue forms.
Repo tier: TEST

## PR identity check

Every commit in the PR range and the PR body need exactly one `Doer:` line and one `Grader:` line. Grader may be `self-merge` for a TEST PR that needs no grade, and otherwise must differ from Doer. Self-merge is TEST only; PROD needs a named grader. Seats are matched after Unicode NFKC normalization, removing invisible format characters, collapsing spaces, and ignoring case. The key is case-insensitive, so `doer:` counts and a second one is a duplicate. Lines inside HTML comments in the PR body are ignored.

After those comments are stripped, the PR body must start with a non-blank line `For Dread:` plus text, stay within 12 non-blank lines, and include one `Tested:` line with non-empty text. Current seats come from seats.txt on main. A roster change is a one-line PR to seats.txt. When the caller repository is dreadedpotato/.github and seats.txt is in the checkout, the check reads that file so the roster PR checks itself. A first name alone is fine, and a trailing parenthetical is ignored. Grader may instead be exactly `self-merge`. Retired names, including Rei, Priya, and Lyska Embervane, fail. The body must still link an issue with `Closes #<n>`, `Fixes #<n>`, or an issue URL.

Every failure names the exact fix. A failing run ends with: Fix it on this same PR: edit the PR body or push the fix to this branch. Do not close and reopen a copy. Do not rerun CI without a change.

TEST PRs self-merge when CI is green, the PR-body check passes, and `Tested:` links live output for a visible change (`Grader: self-merge`). Risky PRs (PROD, CI, gates, checks, the template, PII, or secrets) need Hester's Grade: PASS first. PROD merges are Dread's.

Every commit author and committer email must equal allowed-email, so the check rejects commits made in the GitHub web editor, "Update branch" merge commits, and bot commits, because they carry other emails and no Doer/Grader trailers.

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
