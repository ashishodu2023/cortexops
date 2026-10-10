#!/usr/bin/env bash
# Sync actions/eval-gate to the standalone ashishodu2023/cortexops-eval-action repo.
# See actions/eval-gate/RELEASING.md.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sync-eval-action.sh [--version vX.Y.Z] [--push] [--dir PATH]

Copies actions/eval-gate/action.yml and README.md (without the development-copy note) into a
clone of the standalone action repo and commits the change there.

  --version vX.Y.Z  Also create the annotated tag vX.Y.Z and move the major tag (e.g. v1) to it.
                    CHANGELOG.md in the action repo must already have a '## vX.Y.Z' entry.
  --push            Push main and the tags. Without it nothing leaves your machine.
  --dir PATH        Use an existing clone of the action repo instead of a fresh temporary one.

Environment: ACTION_REPO_URL overrides the action repo URL.
EOF
}

repo_url="${ACTION_REPO_URL:-https://github.com/ashishodu2023/cortexops-eval-action.git}"
version=""
push=false
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="${2:?--version needs a value}"; shift 2 ;;
    --push) push=true; shift ;;
    --dir) dir="${2:?--dir needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

major=""
if [ -n "$version" ]; then
  if ! [[ "$version" =~ ^(v[0-9]+)\.[0-9]+\.[0-9]+$ ]]; then
    echo "--version must look like v1.2.3, got '$version'" >&2
    exit 2
  fi
  major="${BASH_REMATCH[1]}"
fi

root="$(git rev-parse --show-toplevel)"
src="$root/actions/eval-gate"
if [ -n "$(git -C "$root" status --porcelain -- actions/eval-gate)" ]; then
  echo "actions/eval-gate has uncommitted changes; commit them first so the sync records a real commit." >&2
  exit 1
fi
src_sha="$(git -C "$root" rev-parse HEAD)"

if [ -z "$dir" ]; then
  dir="$(mktemp -d)/cortexops-eval-action"
  git clone -q "$repo_url" "$dir"
else
  git -C "$dir" fetch -q --tags --force origin
  git -C "$dir" checkout -q main
  git -C "$dir" merge -q --ff-only origin/main
fi

cp "$src/action.yml" "$dir/action.yml"
awk '/<!-- dev-copy-note:start -->/ { skip = 1 }
     skip && /<!-- dev-copy-note:end -->/ { skip = 0; eat = 1; next }
     skip { next }
     eat && /^$/ { eat = 0; next }
     { eat = 0; print }' "$src/README.md" > "$dir/README.md"
if grep -q "dev-copy-note" "$dir/README.md"; then
  echo "README.md still contains a dev-copy-note marker; check the markers in $src/README.md." >&2
  exit 1
fi

cd "$dir"
if [ -n "$(git status --porcelain -- action.yml README.md)" ]; then
  git add action.yml README.md
  git commit -q -m "Sync from ashishodu2023/cortexops@${src_sha:0:7}" \
    -m "Source: https://github.com/ashishodu2023/cortexops/tree/$src_sha/actions/eval-gate"
  echo "Committed the sync from ${src_sha:0:7}:"
  git --no-pager show --stat --format='  %h %s' HEAD
else
  echo "action.yml and README.md are already in sync with ${src_sha:0:7}."
fi

if [ -n "$version" ]; then
  if ! grep -qE "^## ${version//./\\.}([[:space:]]|$)" CHANGELOG.md; then
    echo "CHANGELOG.md in $dir has no '## $version' entry. Add and commit one there, then re-run with --dir $dir." >&2
    exit 1
  fi
  if git rev-parse -q --verify "refs/tags/$version" >/dev/null; then
    if [ "$(git rev-parse "$version^{commit}")" != "$(git rev-parse HEAD)" ]; then
      echo "Tag $version already exists on another commit; release tags are never moved." >&2
      exit 1
    fi
  else
    git tag -a "$version" -m "CortexOps Eval Gate $version"
  fi
  git tag -fa "$major" -m "CortexOps Eval Gate $major (moving tag, currently $version)" >/dev/null
  echo "Tagged $version and moved $major to $(git rev-parse --short HEAD)."
fi

if $push; then
  git push -q origin main
  if [ -n "$version" ]; then
    git push -q origin "refs/tags/$version"
    git push -q --force origin "refs/tags/$major"
  fi
  echo "Pushed to $repo_url."
  if [ -n "$version" ]; then
    echo "Next: create the $version release in the web UI and tick 'Publish this Action to the GitHub Marketplace':"
    echo "  https://github.com/ashishodu2023/cortexops-eval-action/releases/new?tag=$version"
  fi
else
  echo "Nothing pushed. Review $dir, then re-run with --push --dir $dir${version:+ --version $version}."
fi
