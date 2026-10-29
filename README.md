# Org CI template

This repo holds the org's reusable CI template and issue forms.
Repo tier: TEST

## PR identity check

Every commit in the PR range and the PR body need exactly one Doer: line and one Grader: line naming two different seats from the allowed-seats list. Seats are matched after Unicode NFKC normalization, removing invisible format characters, collapsing spaces, and ignoring case. The key is case-insensitive, so `doer:` counts and a second one is a duplicate. Lines inside HTML comments in the PR body are ignored.

Every commit author and committer email must equal allowed-email, so the check rejects commits made in the GitHub web editor, "Update branch" merge commits, and bot commits, because they carry other emails and no Doer/Grader trailers.

The check runs on pull_request and pull_request_target, and posts a notice and skips on other events like push. Callers override `allowed-email` and `allowed-seats` through `with:` inputs, for example from repo or org variables like `${{ vars.CI_ALLOWED_SEATS }}`.

