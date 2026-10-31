---
name: merge-to-main
description: Get the current branch or worktree merged into the default branch — commit open work, merge the default branch in, resolve conflicts on your own, open a PR, merge it and report when done. Use for "merge this to main", "prepare this branch for merge", "maak dit klaar om te mergen", "merge deze branch naar main", or similar requests. Plain git + gh, so it works in any client (Claude Code, Codex, Kimi …).
---

# Get a branch or worktree into the default branch

Six steps, in this order. Each step gates the next; skip none.

## 0. Requirements

- `git` and the GitHub CLI `gh`, logged in (`gh auth status`).
- Work in the current directory as it is. A normal checkout or a `git worktree` makes no
  difference to the steps below.
- Find the default branch, called `<default>` below:

```bash
gh repo view --json defaultBranchRef -q .defaultBranchRef.name
```

- Commit messages and the PR title follow [Conventional Commits](https://www.conventionalcommits.org/):
  `<type>(<scope>): <summary>`, with a type such as `feat`, `fix`, `chore`, `docs`, `refactor`,
  `test`, `perf`, `build` or `ci`. Only an explicit rule in the project instructions (CLAUDE.md,
  AGENTS.md, CONTRIBUTING.md) replaces this default. The style of older commits doesn't.
- Find the work's reference, called `<ref>` below: its Jira key (`ABC-123`), or its number when
  the project numbers its TODO items. Take it from the task you were given, or from the branch
  name (`feat/ABC-123-…`). Never guess one. No reference? Leave out every `<ref>` part below.

## 1. Stop if you are on the default branch

```bash
git rev-parse --abbrev-ref HEAD
```

Is it `<default>`? **Stop and tell the user.** There is nothing to merge, and a PR from the
default branch into itself can't exist.

## 2. Commit open work

```bash
git status
```

Changed or untracked files?
- Read `git diff` (staged and unstaged).
- Stage files by name (no `git add -A` / `git add .` without checking the list: an `.env` or a
  secret doesn't belong in the commit).
- Write a message in the convention from step 0 that sums up the **why**, not a list of files.
  With a `<ref>`, end it with a `Refs: <ref>` footer, above any co-author lines:

  ```
  feat(metrics): push metrics on shutdown

  Refs: ABC-123
  ```
- Never skip a pre-commit hook (`--no-verify`). The hook fails? Fix the cause and commit again.

A clean tree? Skip this step.

## 3. Merge the default branch in

```bash
git fetch origin <default>
git merge origin/<default> --no-edit
```

Conflicts? Go to step 4. Already up to date, or merged without conflicts? Go to step 5.

## 4. Resolve conflicts

For every file under "Unmerged paths" in `git status`:

1. Read the whole file, not just the conflict blocks. The context tells you what each side tried
   to do.
2. Use `git log --oneline HEAD..origin/<default>` and `git log --oneline origin/<default>..HEAD`
   to see what each side added, so you throw away neither intention.
3. Remove the markers (`<<<<<<<`, `=======`, `>>>>>>>`) and write the version that combines both
   intentions.
4. **Resolve on your own, even when it seems ambiguous.** Pick the version that best combines both
   intentions. Can't they be combined (the same line, contradicting logic)? Take the side that
   keeps the existing tests and build passing (step 5 proves it) and note that choice for the
   report in step 6: not to stop on, but so the user can check it afterwards.
5. If the repo has one, run the fast verification (build, typecheck, tests) before you finish the
   merge. A conflict that reads as resolved can still fail to compile. It fails after your best
   attempt? Try another combination of the two sides before you go on.
6. `git add <file>` for every resolved file, then finish with:

```bash
git commit --no-edit
```

## 5. Open a PR and merge it

```bash
git push -u origin HEAD
gh pr create --fill --base <default> --title "$(cat <title-file>)"
```

The title is a Conventional Commits header for the branch's work as a whole, ending in ` (<ref>)`
when there is one: `feat(metrics): push metrics on shutdown (ABC-123)`. Write it to a file first,
so quotes or backticks in it can't break the command. `--title` overrides the title `--fill`
takes from the commits; the body still comes from them.

Check the PR before you merge it:

```bash
gh pr checks
```

- Checks still running: wait for them (poll, no short sleep loop) instead of merging blind.
- Checks failing: stop and tell the user. Never merge through a red check.
- No checks, or all green:

```bash
gh pr merge --merge
```

Use `--merge` (not `--squash` / `--rebase`) unless the user or the repo's convention says
otherwise. Don't delete the branch (leave out `--delete-branch`); that is the user's call.

Afterwards run `git fetch origin`. Don't check out `<default>` here: in a worktree it is usually
checked out in the main checkout, and git refuses.

## 6. Report

Tell the user in one or two sentences: which branch was merged, the PR link, and whether there
were conflicts. Was a resolution in step 4 a judgment call (no obvious combination, or picked by
which side kept the tests passing)? Name that file and the choice. That is the one thing the user
can't read from the PR diff alone. No longer report: the PR and the merge commit are the proof.

## Don't

- Don't force-push, also not after resolving a conflict on your own branch. A plain `git push`
  is enough after step 4.
- Don't merge with `--no-verify` or skip hooks.
- Don't go on to step 5 while step 4 left a file with conflict markers.
- Don't delete the branch, and never force-push to the default branch.
