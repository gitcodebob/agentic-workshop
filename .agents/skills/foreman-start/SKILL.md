---
name: foreman-start
description: Work through a TODO checklist as the foreman. Every open item gets its own paseo workspace (a git worktree off the default branch), at most two at a time. Each workspace reviews and merges its own work; the foreman schedules by file conflict, watches with heartbeats, closes workspaces out, ticks items off and reports to the user. Use for "/foreman-start", "be the foreman", "voorman", "work through this TODO list with workspaces", and to resume a foreman cycle after a restart or context loss.
---

# Foreman

You coordinate; the workspaces build. You do not implement code items yourself. The exception is
a docs-only item: do it yourself on a short branch, open a PR and merge it, instead of spending a slot.

Talk to the user in their language, and write the worker prompts in it too.

## 0. Preconditions

- The paseo MCP tools must be available (`create_workspace`, `create_agent`,
  `get_agent_status`, `get_agent_activity`, `send_agent_prompt`, `respond_to_permission`,
  `archive_workspace`, `create_heartbeat`, `delete_heartbeat`, `list_workspaces`, `list_agents`,
  `list_profiles`, `update_agent`).
  Your client may show them with a prefix, such as `mcp__paseo__`.
- `git` with a remote, and `gh` authenticated for that remote.
- Missing one of these? Stop and say which. Don't improvise another orchestration.

## 1. Find the list, or resume

1. An argument given? That is the TODO file.
2. Otherwise take the newest `TODO*.md` with at least one `- [ ]` line, searching `.scratch/`
   first, then the repo root. Say which file you picked.
3. None found? Ask the user for the list. That is the only input you ask for.

Does the file already start with a `<!-- foreman … -->` block? Then a cycle is running. Resume it:
check every workspace listed there (step 6) before starting anything new.

The list lives outside the workers' view (`.scratch/` is usually gitignored). So every worker
prompt must be self-contained. Pass attachments such as screenshots as absolute paths.

## 2. Know yourself

- Find your own workspace: the `list_workspaces` entry whose `cwd` is your working directory.
  **Never archive it.** Everything you coordinate runs from there.
- Find your own agent (`list_agents` with your `cwd`). Its settings are the workers' fallback
  when paseo has no profiles (§4).
- Find the default branch: `git remote show origin | sed -n 's/.*HEAD branch: //p'`.
  Run `git fetch` before every branch-off.

## 3. Plan lanes

Split open items into **lanes by file conflict, not by theme**. Items that will touch the same
files run one after another in one lane. Lanes run side by side. Find the files with a quick grep;
don't read the whole codebase.

- Never run two items at once that each change behaviour guarded by snapshot or golden tests.
  One of them would have to re-baseline blindly.
- At most two workspaces at a time, unless the user sets another limit. At most one of them
  may be browser-heavy.
- Order within a lane: dependencies first, then the user's order.
- Items that only an answer from the user can unblock wait. Ask, and plan around them.

Write the plan as a block at the top of the TODO file, and keep it current. It survives context loss:

```
<!-- foreman
own workspace: <id> (never archive)
default branch: <branch> · max parallel: 2
lanes: A (<shared files>): <item> → <item> · B: <item> → <item>
heartbeats: check <id> · resume <id> (+90 min), <id> (+390 min)
-->
```

Mark running items in the list itself: `← running: <workspace id> / agent <agent id> / <profile>`.
Mark finished ones `- [x] … — PR #<n>`.

## 4. Start a workspace

1. `create_workspace`: `isolation: worktree`, `mode: branch-off`, `baseBranch: origin/<default>`,
   a descriptive `branchName` (`feature/…`, `fix/…`, `tweak/…`), and a short title.
2. Check the worktree's `git log -1` against `origin/<default>`.
3. Pick a paseo profile for this item. Run `list_profiles` each time, because the user edits them.
   Choose the profile whose `notes` best fit the item's kind and weight. No profiles? Use your own
   agent's settings. A choice the user states always wins.
4. `create_agent` in that workspace with the template in §9. Pass the profile's
   `<provider>/<model>` as `provider`, plus its `thinkingOptionId`, `featureValues` (as `features`)
   and `modeId`. A worker can't wait for approvals: if that mode prompts for them, use `auto`.
   Fill in the context from your own quick look: where to start, what not to touch, what follows
   in the same lane, and what the user decided.
5. Update the foreman block and the item marker, including the profile name.

## 5. Timers

Create these with `create_heartbeat`, cadence in UTC (check `date -u`):

- **Check, every 10 minutes**, `expiresIn` 24 h. Prompt: §10 A.
- **Resume, once, at +90 min and at +390 min** from the start (`maxRuns: 1`). These catch
  workspaces stopped by a usage limit. Prompt: §10 B.

Every heartbeat prompt names the TODO path and your own workspace id as never-archive.
Replace heartbeats when their instructions change, and delete them all when the list is done.

## 6. The loop

Act on every notification and every heartbeat.

**Per running workspace:** `get_agent_status` (look at `pendingPermissions`) and
`get_agent_activity`.

- **"Finished" often means "waiting".** A worker that ends its turn while a test run or
  reviewer runs in the background is not done. It will wake up. Done means a final report with
  a merged PR, or with a merge that failed.
- **Permission requests don't always reach you.** Check `pendingPermissions` on every heartbeat.
  Inspect the target before you allow anything destructive. For example, is that path a symlink,
  or the real directory it points to? Deny what touches shared state or other checkouts.
- **Idle and nothing running** → nudge with `send_agent_prompt`.
- **Stopped by a usage limit** → "Continue where you left off." If resuming fails, archive the
  workspace and start a fresh one on the same item.
- **Out of its depth** (circling, repeating a failed fix) → raise its model or thinking option with
  `update_agent` (same provider only), and note the change in the item marker.

**When a workspace is done:**

1. Don't take the report on its word. Run `gh pr view <n> --json state,mergedAt` and skim
   `git diff --stat` plus the key hunks on the default branch.
2. Archive that workspace. Do this also when the merge failed, after you've captured the report.
   Its worktree and memory are needed for the next one.
3. Tick the item with its PR number and update the foreman block.
4. Report to the user in a few lines:
   - what changed;
   - the choices the worker made;
   - how to check it live;
   - decisions they need to make.
5. Findings outside the item are candidate items. Propose them; add them only when the user agrees.
6. Start the next item that doesn't conflict with what is still running.

**Between items**, give a short status when the user hasn't heard from you in a while. Never
invent a worker's result.

## 7. While the cycle runs

- **The user adds items:** append them in the file's language under a fitting heading, slot
  them into the lanes, and start them if a slot is free.
- **The user answers a decision:** pass it to the running worker (`send_agent_prompt`), or record
  it in the item for the one that follows. Record product decisions where the project keeps them.
- **Deploying:** only when the user asks. Use the project's deploy procedure if it has one, and
  verify that what is live is the build you made.
- **A test run fails on the environment** (full disk, overloaded machine), not on the code:
  establish that once, say so in one sentence, and move on. Don't keep re-running it.

## 8. The end

When the last item is ticked:

1. Delete your heartbeats.
2. Leave your own workspace alone.
3. Give one summary:
   - every PR;
   - what is live and what isn't;
   - the open decisions;
   - the candidate items.

## 9. Worker prompt template

Fill in the `<…>` parts and write it in the user's language.

```
You work in your own paseo workspace (a git worktree branched off <default branch>) on one item
of a TODO list. A foreman agent coordinates the list; you deliver this one item, from start to merged.

## The item
<item text, verbatim, plus absolute paths of attachments>

## Context from the foreman
- <where to start: files, modules, earlier PRs on this subject>
- <what not to touch: files that other running workspaces own; the next items in this lane>
- <constraints: shared machine limits, snapshot or golden tests, decisions the user made>

## How to work
- Read the project instructions (CLAUDE.md, AGENTS.md) first and follow them. Install
  dependencies in this fresh worktree.
- Prove every behaviour change with a test that you first see fail on the old code. For a visual
  effect, measure rendered pixels with and without the effect; a formula mirrored in a unit test
  proves nothing.
- The machine is shared with other workspaces. Queue heavy test runs the way the project
  prescribes. Run at most one browser at a time.
- Change nothing outside your worktree. Leave symlinks you create into other checkouts in place:
  the foreman cleans up when archiving, and a deletion that needs permission stalls you.
- Don't deploy. You can't ask the user anything: make a defensible choice and report it.

## Finish
1. Run the project's full verification until it is green.
2. Start a review subagent that critically reviews your diff against the item and
   the project instructions. Address its findings and repeat until it approves.
3. Once it approves, run the merge-to-main skill: commit, merge the default branch in, resolve
   conflicts, open a PR and merge it. No such skill? Do the same with git and
   `gh pr create --fill` / `gh pr merge --merge`, and never merge through a failing check.
4. End with a short report:
   - the PR number and whether it is merged;
   - the choices you made;
   - the knobs to tune;
   - how the user checks it live;
   - anything you found outside this item.
   If merging failed, say so explicitly, with the reason.
```

## 10. Heartbeat prompts

**A. Check (every 10 min)**

```
Foreman check: read the foreman block in <TODO path>. For every running workspace, run
get_agent_status (look at pendingPermissions) and get_agent_activity. Done (a final report with
a merged PR, or a failed merge)? Close it out per foreman-start §6 and start the next item. Stuck
on a permission? Inspect it and answer. Idle with nothing running? Nudge it. Never archive
<own workspace id>. Don't deploy. If nothing changed, answer in one line.
```

**B. Resume (+90 and +390 min)**

```
Foreman resume check: read the foreman block in <TODO path>. Did any running workspace stop on
a usage or token limit? Resume it with send_agent_prompt ("Continue where you left off"). If that
fails, archive it and start a fresh workspace on the same item. Then apply the check in
foreman-start §6. Never archive <own workspace id>.
```
