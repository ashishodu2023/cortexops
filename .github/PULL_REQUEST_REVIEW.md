# Pull request review guide

How reviewers leave comments and when a PR is approved for merge into `main`.

## Hard rules

1. **No direct commits to `main`.** All changes land via pull request.
2. **CI must be green** before merge: `Lint`, `Tests`, `SDK unit tests (3.11)`.
3. **At least one approving review** is required (code owners for owned paths).
4. **All review threads must be resolved** before merge.

Maintainer note: repository admins may bypass the approval count when merging their own PR, but they still **must** use a PR — direct pushes to `main` remain blocked.

## Review comment style

Keep comments actionable and scoped.

| Kind | Use when | Example |
|------|----------|---------|
| **Blocking** | Correctness, security, data loss, broken API, failing tests | `Blocking: this drops usage tokens before cost is recorded.` |
| **Request change** | Clear defect or policy violation | `Please add a regression test for invalid API keys.` |
| **Suggestion** | Optional improvement; author may decline with a reason | `Suggestion: extract this into a helper for readability.` |
| **Nit** | Style / naming only; never blocks merge alone | `Nit: rename `tmp` → `checkpoint_path`.` |
| **Question** | Need context before judging | `Question: is empty dataset intentional for this path?` |

Prefix the first line with the kind (`Blocking:`, `Suggestion:`, etc.) so authors can triage quickly.

### Do

- Point to the line or behaviour, and say what “done” looks like
- Prefer one thread per concern
- Call out security, secrets, and public API breakage explicitly
- Approve when the PR is mergeable even if nits remain (file nits as follow-ups if needed)

### Don’t

- Block on personal taste without a standard in `CONTRIBUTING.md` / ruff
- Rework large unrelated areas in review comments (“while you’re here…”)
- Approve with unresolved Blocking threads
- Ask authors to force-push history unless necessary for secrets removal

## Approval decision

Approve when **all** of the following are true:

- [ ] Intent matches the linked issue / PR summary
- [ ] Behaviour is correct for the stated scope
- [ ] Tests cover the change (or justified why not, e.g. docs-only)
- [ ] No new secrets or unsafe defaults
- [ ] Public API / CLI changes are intentional and documented
- [ ] CI required checks are passing (or will pass after a trivial fix already agreed)

Use **Request changes** when a Blocking item remains.
Use **Comment** when you only have questions or non-blocking suggestions.

## Merge checklist (maintainer)

- [ ] Title follows conventional commits
- [ ] `Closes #N` / `Fixes #N` present when applicable
- [ ] Required checks green
- [ ] Review threads resolved
