# Releasing the eval-gate action

The action is published as
[`ashishodu2023/cortexops-eval-action`](https://github.com/ashishodu2023/cortexops-eval-action), a
standalone repository so it can be listed on the GitHub Marketplace (which needs `action.yml` at the
repository root). This directory is the development copy:

- `action.yml` here and in the action repo are identical.
- `README.md` here is the published README plus a development-copy note between
  `<!-- dev-copy-note:start -->` and `<!-- dev-copy-note:end -->`, which the sync removes.
- `CHANGELOG.md` and `LICENSE` live only in the action repo.

Make changes here, through a normal pull request. The dogfood job in `.github/workflows/eval.yml` runs
this copy (`uses: ./actions/eval-gate`) against the SDK at the same commit, so it tests every change
before it is synced.

## Versioning

- `vX.Y.Z` tags are immutable releases. Never move or delete one.
- `v1` is a moving tag that points at the latest `v1.x.y`. Users on `@v1` get every 1.x release, so
  within v1 only add inputs and outputs or fix bugs. Removing or renaming an input or output, or changing
  a default in a way that can fail existing workflows, needs `v2.0.0` and a new `v2` tag.
- The default `cortexops-version` is a pinned range (`>=0.6.0,<0.7`). When a new SDK minor release
  (0.7.0) ships, test the action against it, then widen or bump the range in a minor action release.

## Syncing and releasing

Prerequisites: push access to the action repo, `git`, and `bash`. Run from a clean checkout of `main`
in this repository after the change has merged.

1. Sync without pushing and review the result:

   ```bash
   scripts/sync-eval-action.sh
   ```

   The script clones the action repo into a temporary directory, copies `action.yml` and `README.md`
   (dropping the development-copy note), commits as `Sync from ashishodu2023/cortexops@<sha>`, and prints
   the clone's path.

2. For a docs-only change, push it and stop; no release is needed:

   ```bash
   scripts/sync-eval-action.sh --push --dir <path printed in step 1>
   ```

3. For a release, add a `## vX.Y.Z - YYYY-MM-DD` entry at the top of `CHANGELOG.md` in the clone, commit
   it, then tag and push:

   ```bash
   scripts/sync-eval-action.sh --version vX.Y.Z --push --dir <path>
   ```

   This creates the annotated tag `vX.Y.Z`, moves `vX` (e.g. `v1`) to the same commit with a force push,
   and pushes `main`. The script refuses to tag when the changelog entry is missing and never moves an
   existing `vX.Y.Z` tag.

4. Create the GitHub release from the web UI, so it can be listed on the Marketplace:
   `https://github.com/ashishodu2023/cortexops-eval-action/releases/new?tag=vX.Y.Z`. Tick
   **Publish this Action to the GitHub Marketplace**, check the primary and secondary categories
   (Continuous integration and Testing), paste the changelog entry as the notes, and click **Publish release** (requires two-factor authentication). Releases created with
   `gh release create` or the API are not listed on the Marketplace until you edit them in the web UI
   and tick that box.

5. Check that `uses: ashishodu2023/cortexops-eval-action@vX.Y.Z` and `@vX` work, for example from a
   throwaway branch with a workflow that runs the action against `examples/langgraph_payments`, then
   delete the branch.

## Optional: automatic sync

Syncing on every merge can be automated with a workflow in this repository that runs
`scripts/sync-eval-action.sh --push` (without `--version`) when `actions/eval-gate/**` changes on
`main`. The default `GITHUB_TOKEN` cannot push to another repository, so this needs a fine-grained
personal access token limited to `ashishodu2023/cortexops-eval-action` with **Contents: read and
write**, stored as a repository secret (for example `EVAL_ACTION_SYNC_TOKEN`) and passed to the script
through `ACTION_REPO_URL=https://x-access-token:${TOKEN}@github.com/ashishodu2023/cortexops-eval-action.git`.
No such workflow is set up yet. Tagging and releases stay manual either way.
