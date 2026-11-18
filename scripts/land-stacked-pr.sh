#!/usr/bin/env bash
# Land the base of a stack of PRs, then carry the stack onto dev (#373).
#
#     scripts/land-stacked-pr.sh <base PR> <PR stacked on it> [<PR stacked on that> ...]
#
# Run it from any checkout of this repository. It:
#
# 1. squash-merges the base PR once its `checks` job passes, leaving its branch in place (deleting it would make
#    GitHub close the PR stacked on it instead of retargeting it), and waits until it has merged;
# 2. retargets the PR stacked on it onto dev;
# 3. merges dev into that PR's branch, then each branch into the one stacked on it, and pushes each. Every merge runs in
#    a temporary worktree, so the branches may be checked out elsewhere: pull them there afterwards.
#
# A squash merge leaves dev holding the base's changes as one new commit, so merging dev into the next branch
# conflicts on every file both touched. A conflicted file goes to the next branch's version only when dev now holds
# that file exactly as the merged base branch did: then dev has nothing the next branch lacks. Any other conflict
# stops the script with the merge left in progress for you to resolve. rerere is off for these merges, so no
# remembered resolution is applied silently, and a merge still in progress afterwards stops the script, since it
# would leave the PR conflicting. A branch further up takes its own version of a conflicted file on the same test: the
# branch below it holds that file exactly as the landed base did.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <base PR> <PR stacked on it> [<PR stacked on that> ...]" >&2
  exit 2
fi

base_pr=$1
shift
git fetch -q origin
base_branch=$(gh pr view "$base_pr" --json headRefName --jq .headRefName)
merged_head=$(git rev-parse "origin/$base_branch")

if [ "$(gh pr view "$base_pr" --json state --jq .state)" != "MERGED" ]; then
  gh pr merge "$base_pr" --squash --auto
  echo "Waiting for #$base_pr to merge..."
  until [ "$(gh pr view "$base_pr" --json state --jq .state)" = "MERGED" ]; do
    sleep 30
  done
fi
git fetch -q origin

# Merge `$2` into the checked-out branch. A conflicted file takes the checked-out branch's version only when `$2`
# holds it exactly as `$1`, the landed base branch's head, did.
merge_up() {
  local landed=$1 into=$2
  if git -c rerere.enabled=false merge --no-edit "$into"; then
    return
  fi
  local file
  while IFS= read -r file; do
    if git diff --quiet "$landed" "$into" -- "$file"; then
      git checkout --ours -- "$file"
      git add -- "$file"
    else
      echo "Conflict in $file that the landed base doesn't explain. Resolve it in $(pwd), commit," >&2
      echo "push to $branch, and run the script again for the PRs above it." >&2
      exit 1
    fi
  done < <(git diff --name-only --diff-filter=U)
  git -c core.editor=true commit --no-edit
}

# Each merge happens in a worktree of its own, so a branch checked out in another worktree can still be carried.
target=dev
for pr in "$@"; do
  branch=$(gh pr view "$pr" --json headRefName --jq .headRefName)
  if [ "$target" = dev ]; then
    # gh pr edit fails on some repositories over the retired classic Projects, so the REST API retargets it.
    gh api -X PATCH "repos/{owner}/{repo}/pulls/$pr" -f base=dev --silent
  fi
  work=$(mktemp -d)
  git worktree add -q --detach "$work" "origin/$branch"
  (
    cd "$work"
    merge_up "$merged_head" "origin/$target"
    if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
      echo "The merge into $branch is still in progress in $work: finish it before pushing." >&2
      exit 1
    fi
    git push -q origin "HEAD:refs/heads/$branch"
  )
  git worktree remove "$work"
  git fetch -q origin
  echo "#$pr ($branch) is now on $target. Pull it in any worktree that has it checked out."
  target=$branch
done
