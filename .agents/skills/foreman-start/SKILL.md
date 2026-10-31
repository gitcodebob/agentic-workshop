---
name: foreman-start
description: Work through a TODO checklist as the foreman. Every open item gets its own paseo workspace (a git worktree off the default branch), at most three at a time, fewer when the machine's free RAM or the project's instructions say so. Each workspace reviews and merges its own work; the foreman schedules by file conflict, watches with heartbeats, closes workspaces out, ticks items off and reports to the user. Use for "/foreman-start", "be the foreman", "voorman", "work through this TODO list with workspaces", and to resume a foreman cycle after a restart or context loss.
---

# Foreman

You coordinate; the workspaces build. You do not implement code items yourself. The exception is
a docs-only item: do it yourself on a short branch (named as in §4) and merge it with the
merge-to-main skill, instead of spending a slot. No such skill? Follow its conventions with plain
`git` and `gh` (§9, Finish step 4).

Talk to the user in their language, and write the worker prompts in it too.

## 0. Preconditions

- The paseo MCP tools must be available (`create_workspace`, `create_agent`,
  `get_agent_status`, `get_agent_activity`, `send_agent_prompt`, `respond_to_permission`,
  `archive_workspace`, `create_heartbeat`, `delete_heartbeat`, `list_workspaces`, `list_agents`,
  `list_profiles`, `update_agent`, `rename_workspace`).
  Your client may show them with a prefix, for example `mcp__paseo__`. Deferred? Load them first,
  the way your client loads deferred tools.
- `git` with a remote, and `gh` authenticated for that remote.
- `python3` and the `paseo` CLI, for the scripts below.
- Missing one of these? Stop and say which. Don't improvise another orchestration.
- Optional: `jira` (jira-cli) or `acli` (Atlassian CLI), for ticket status (§2). Without them the
  cycle runs the same.

## The script

`scripts/foreman.py`, next to this file, does the mechanical steps: finding the list, the foreman
block, the checklist markers, the workspace name, ticket moves and comments, the heartbeat scan, the merge check and the machine check. Call it by its absolute path, as
`python3 <this skill's directory>/scripts/foreman.py <command>`; `--help` lists the commands.
Write that call into the foreman block as `script:`, so heartbeats and a resumed cycle find it.

Use it instead of doing these steps by hand, and don't edit the block or the markers yourself,
except for the free-text lines (`lanes:`, `verify:` …), which you set with
`state set`. It prints a few lines and exits 0 even when a side effect (a rename, a ticket move
or comment) fails: read the output and act on it. It exits non-zero only when called wrongly, for example with
an item that matches no open line or several; the error lists the candidates.

## Asking the user

Once you have the list, never ask with a tool that blocks your turn until the user answers, such
as `AskUserQuestion` in Claude Code. While your turn waits, every notification and heartbeat waits
with it: finished workers stay open and free slots stay empty. Ask in plain text in your reply
instead: the question, the options, your advice, what waits on it and what runs meanwhile. Then
carry on in the same turn: start what doesn't wait on the answer, handle the workers. The answer
arrives as a later message (§7).

Until it is answered, every question:
- stands as one plain bullet (no checkbox) under `## Waiting on the user`, right below the foreman
  block: `- <item> · <question> · options: <a> / <b> · advice: <a, and why>`, plus
  `· default: <a> by <YYYY-MM-DD HH:MM ±HH:MM>` if it has one. `state show` and `check` read it,
  so keep that heading in English whatever the file's language, and put nothing else under it;
- goes on the item's ticket, if it has a key: `ticket comment <KEY> '<question, options, advice>'
  --todo <TODO>`. A failed comment is one line in your report, never a hold-up;
- opens every message you send the user, in a short **Waiting on you** block with the same points,
  so they find everything in one place when they come back.

**A default with a deadline** is only for a choice that is easy to undo: a rounding, a label
text, when a hint disappears. Say "no answer by 18:00 CET, then I take <a>", a few hours ahead,
and write the deadline with its UTC offset in the bullet. `check` flags it with `!` once it has
passed: take the default as the answer (§7) and say so in one line. A product choice (direction,
scope, something users will see work differently, something hard to undo) never gets a default:
it waits, and you plan around it. Rule of thumb: if the user later picks the other option, is that
a small follow-up that leaves nothing to clean up? Then a default may do. In doubt, it waits.

## 1. Find the list, or resume

Run `find-todo [PATH]`. Without a path it takes the newest `TODO*.md` with at least one `- [ ]`
line, searching `.scratch/` first, then the repo root. Say which file you picked. It finds none?
Ask the user for the list. That is the only input you ask for before you start; a question about
a single item goes in plain text while the rest starts (Asking the user).

It reports `cycle: RUNNING` when the file already starts with a `<!-- foreman … -->` block. Then
resume: run `check` (§6) and handle every listed workspace before starting anything new. Resuming
from another workspace than the block names? Set `own workspace:` to yours with `state set` first,
so heartbeats protect the right one. Then pick up the run's count again (§3).

The list lives outside the workers' view (`.scratch/` is usually gitignored). So every worker
prompt must be self-contained. Pass attachments such as screenshots as absolute paths.

## 2. Know yourself

- Find your own workspace: the `list_workspaces` entry whose `cwd` is your working directory.
  **Never archive it.** Everything you coordinate runs from there.
- Find your own agent (`list_agents` with your `cwd`). Its settings are the workers' fallback
  when paseo has no profiles (§4).
- Find the default branch: `git remote show origin | sed -n 's/.*HEAD branch: //p'`.
  Run `git fetch` before every branch-off.
- Find the ticket tracker with `ticket detect`. It only matters for items that name a ticket key
  (`ABC-123`), and it also covers docs-only items you do yourself. It tries jira-cli (loading
  `~/.config/jira-cli/env` when the shell didn't), then `acli`. `none`? Say so once in your plan
  message and carry on. Don't install or log in for this; that is the user's call.

  `state start` and `state done` move an item's ticket themselves, to `In Progress` and `Done`
  unless the block's tracker line says otherwise (`start=` / `done=`). A move to an unknown state
  fails, and the output lists the valid states: put the plain equivalent in the tracker line with
  `state set` and retry with `ticket move <KEY> start|done --todo <TODO>`, or ask the user once.
  A failed move never holds up the cycle: say so in one line and carry on.

## 3. Plan lanes

Split open items into **lanes by file conflict, not by theme**. Items that will touch the same
files run one after another in one lane. Lanes run side by side. Find the files with a quick grep;
don't read the whole codebase.

- Never run two items at once that each change behaviour guarded by snapshot or golden tests.
  One of them would have to re-baseline blindly.
- At most three workspaces at a time, unless the user sets another limit. At most one of them
  may be heavy (see below).
- Run `capacity` before you start the first workspace and before you raise the limit. It reports
  cores, load, the memory available now, what zram could still free by compressing cold pages
  (counted with a haircut, and not at all while the machine is under pressure), memory pressure
  and swap-in, whether /tmp is a tmpfs (then it counts as RAM; caches there grow with every new
  worktree), the headroom left after a reserve for the system, and how many workers fit in it. It
  suggests a limit of at most three. A warning? Clean the stale caches it lists first, and keep to
  its suggestion.
- You decide which items are heavy, `capacity` can't see it: a worker that runs headless Chrome or
  a browser suite, or a large test suite that peaks past 1 GiB. Judge it from the item and the
  project instructions. A regular worker counts 0.4 GiB, a heavy one 1.3 GiB. Keep the sum over
  the workers that run and the one you are about to start within the headroom, stay at or under
  the suggested limit, and never run two heavy ones. Workers that already run are in the available
  memory at their current size, not at their peak.
- The project may deviate from that: heavy test stages, a browser suite, a build that needs
  several GiB, or limits of the machine it runs on. Read the project instructions (CLAUDE.md,
  AGENTS.md) for such notes before you settle the limit. They win over `capacity`: lower the limit
  or keep the heavy stage to one workspace at a time, and put the rule in the foreman block and in
  every worker prompt. A project that says nothing about it gets `capacity`'s suggestion.
- Per worker, one heavy step at a time: a verification chain, a browser run or a review subagent,
  never two at once. Put that rule in every worker prompt.
- Order within a lane: dependencies first, then the user's order.
- An item so big that it holds up a lane: split it by the files each half touches, so the halves
  can run side by side.
- Items that only an answer from the user can unblock wait. Ask without blocking (Asking the user),
  and plan around them: the rest starts now.
- Find out which verification stages the project has (`package.json` scripts, CLAUDE.md or
  AGENTS.md) and record them in the foreman block. Then every worker prompt names the right
  command instead of "full verification". A project with fewer stages leaves the rest out.

Write the plan as a block at the top of the TODO file, and keep it current. It survives context loss:

```
<!-- foreman
own workspace: <id> (never archive)
script: python3 <absolute path>/scripts/foreman.py
default branch: <branch> · max parallel: <1-3, from capacity and the project instructions>
verify: fast=<command> · pre-merge=<command> · deploy=<command>
lanes: A (<shared files>): <item> → <item> · B: <item> → <item>
heartbeats: check <id> · resume <id> (every 5 h)
tracker: <jira-cli | acli | none> · start=<state> · done=<state>
-->
```

Running items are marked in the list itself
(`← running: <workspace id> / agent <agent id> / <profile>`, by `state start`), finished ones as
`- [x] … — PR #<n>` (by `state done`). `state show` prints it all.

**Your own workspace carries the run's progress in its name: `Foreman (<done>/<total>)`.**
Keep the count yourself, in this session. Don't write it into the TODO file or anywhere else:
the list can be a TODO file or a set of Jira tickets, and neither is the place for it.
- `total` is the number of items this run picks up: every open item you plan, including docs-only
  items you do yourself and items waiting on an answer from the user. Items ticked before this
  run don't count.
- `done` is the number of those items finished in this run (merged).

Once the plan is written, run `name 0 <total>`. Run `name <done> <total>` again whenever either
number changes (§6, §7). It finds your own workspace by its directory. A failed rename prints the
title to set with `rename_workspace` instead; it never holds up the cycle.

Lost the count (a restart, a lost context)? `name` without numbers reads your workspace's
current name and the count in it. Carry on from there.

## 4. Start a workspace

1. `create_workspace`: `isolation: worktree`, `mode: branch-off`, `baseBranch: origin/<default>`,
   a short title, and a `branchName` of `<type>/<ref>-<two to five words>`, for example
   `feat/ABC-123-storm-weather` or `fix/key-legend-icons`. `<type>` is the Conventional Commits
   type (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`). `<ref>` is
   the item's ticket key, or its number when the project numbers its TODO items; leave it out when
   there is neither. A branch convention in the project instructions wins.
2. Check the worktree's `git log -1` against `origin/<default>`.
3. Pick a paseo profile for this item. Run `list_profiles` each time, because the user edits them.
   Choose the profile whose `notes` best fit the item's kind and weight. No profiles? Use your own
   agent's settings. A choice the user states always wins.
4. `create_agent` in that workspace with the template in §9. Pass the profile's
   `<provider>/<model>` as `provider`, plus its `thinkingOptionId`, `featureValues` (as `features`)
   and `modeId`. A worker can't wait for approvals: if that mode prompts for them, use Claude →
   `auto`; Codex → `auto-review` (or what the profile says); Kimi → `auto` with `auto_accept`.
   Codex's auto-reviewer decides escalations itself, and a denial never reaches you as a paseo
   permission request: a Codex worker that stays `running` long without an update may be stuck
   on one.
   Fill in the context from your own quick look: where to start, what not to touch, what follows
   in the same lane, what the user decided, the verification commands from the foreman block, and
   the open ends that merged items in this lane left for this one. A non-Claude worker doesn't see
   your memory: give it the project lessons that live only there.
5. `state start <TODO> <item> --ws <workspace id> --agent <agent id> --profile <profile>`. It
   marks the item and moves its ticket, if it has one, to the start state (§2). `<item>` is its
   ticket key or a unique piece of its text. Update `lanes:` with `state set` if the plan changed.

## 5. Timers

Create these with `create_heartbeat`, cadence in UTC (check `date -u`):

- **Check, every 10 minutes**, `expiresIn` 24 h. Prompt: §10 A.
- **Resume, every 5 hours** (cron `0 */5 * * *`), with the same `expiresIn` as the check. It
  catches workspaces stopped by a usage limit, however long the cycle runs. Prompt: §10 B.

Every heartbeat prompt names the TODO path, the script call and your own workspace id as
never-archive. Record the heartbeat ids with `state set <TODO> heartbeats "check <id> · resume <id> (every 5 h)"`.
Replace heartbeats when their instructions change, and delete them all when the list is done.

## 6. The loop

Act on every notification and every heartbeat.

**Start with `check <TODO>`.** One call scans every running workspace: its status, pending
permission requests, whether its workspace still exists, and for an idle worker its last message
plus the state of the PR it names. `NO CHANGE` on the first line means all workers run and nothing
waits on you: answer in one line. Lines starting with `!` or `*` need you. Look deeper
(`get_agent_status`, `get_agent_activity`) only for those.

- **"Finished" often means "waiting".** A worker that ends its turn while a test run or
  reviewer runs in the background is not done. It will wake up. Done means a final report with
  a merged PR, or with a merge that failed.
- **Permission requests don't always reach you.** `check` lists them on every heartbeat.
  Inspect the target before you allow anything destructive. For example, is that path a symlink,
  or the real directory it points to? Deny what touches shared state or other checkouts.
- **Idle and nothing running** → nudge with `send_agent_prompt`. Phrase every nudge or correction
  as a continuation: "Keep going; also …". A worker reads a bare correction as a stop.
- **All workers idle at the same moment, without a final report** → the daemon restarted (check
  its log for an OOM). Uncommitted work survives in the worktrees. Resume each with what was running
  and lower the parallel limit until memory allows it.
- **Stopped by a usage limit** → "Continue where you left off." If resuming fails and the worktree
  holds uncommitted work, start an agent of another provider (e.g. Claude ↔ Codex; the profile
  notes say which) in the same workspace with a handover prompt (what is done, what remains), and
  record it with `state start … --agent <new id> --no-ticket`, or `check` keeps watching the old
  agent. Archive and start fresh only when the worktree is clean.
- **Out of its depth** (circling, repeating a failed fix) → raise its model or thinking option with
  `update_agent` (same provider only), and note the change in the item marker by running
  `state start` again with the new `--profile` and `--no-ticket`.

**When a workspace is done:**

1. Don't take the report on its word. Run `verify-pr <n> --todo <TODO>`: it says whether the PR
   is merged and on the default branch, and lists the files it changed. Skim the key hunks
   (`gh pr diff <n>`).
2. Archive that workspace. Do this also when the merge failed, after you've captured the report.
   Its worktree and memory are needed for the next one.
3. Merged: `state done <TODO> <item> --pr <n>`. It ticks the item with its PR number and moves
   its ticket, if it has one, to the done state (§2). Then raise `done` by one and run
   `name <done> <total>`. A failed merge: `state unmark <TODO> <item>` instead; the item stays
   open, its ticket stays where it is, and the count doesn't change.
4. Report to the user in a few lines:
   - what changed;
   - the choices the worker made;
   - how to check it live;
   - decisions they need to make, asked as in Asking the user.
5. Findings outside the item are candidate items. Propose them; add them only when the user agrees.
   A finding that belongs to an item that is still open goes straight into that item's text, so
   its worker inherits it.
6. Start the next item that doesn't conflict with what is still running.

**Between items**, give a short status when the user hasn't heard from you in a while. Never
invent a worker's result. While a question is open, every status and report starts with the
**Waiting on you** block.

## 7. While the cycle runs

- **The user adds items:** append them in the file's language under a fitting heading, slot
  them into the lanes, and start them if a slot is free. Raise `total` by the number added and run
  `name <done> <total>`. An item the user drops lowers `total` the same way.
- **A docs-only item you do yourself:** once its PR is merged, `state done <TODO> <item> --pr <n>`,
  then count it and run `name`, just as in §6.
- **The user answers a decision, or its default's deadline passed:** pass it to the running worker
  (`send_agent_prompt`, phrased as a continuation, §6), or record it in the item for the one that
  follows. Record product decisions where the project keeps them. Remove its bullet from
  `Waiting on the user`, put the decision on the item's ticket with `ticket comment`, and start the
  item if a slot is free.
- **Deploying:** only when the user asks. Use the project's deploy procedure if it has one, and
  verify that what is live is the build you made.
- **A test run fails on the environment** (full disk, overloaded machine), not on the code:
  establish that once, say so in one sentence, and move on. Don't keep re-running it.

## 8. The end

When the last item is ticked:

1. Delete your heartbeats. `state show` should list no open items, and your workspace should
   read `Foreman (<total>/<total>)`.
2. Workers don't touch the project's docs; they report what belongs there. If they reported
   anything, do one docs pass yourself, as a docs-only item, so the final check runs on the final
   tree. A step that proved too heavy for the machine (an OOM, a stalled run) belongs there too:
   propose a note in the project instructions, so the next foreman plans around it.
3. Run the project's deploy-level verification (`deploy=` in the foreman block, e.g. end-to-end
   tests and recordings) once, on an up-to-date default branch. That is the one moment for it.
   A failure on the code is a candidate item: propose it, don't fix it yourself.
4. Leave your own workspace alone.
5. Give one summary:
   - every PR;
   - the result of the deploy-level verification;
   - what is live and what isn't;
   - the open decisions, as they stand under `Waiting on the user`. Without heartbeats a default
     no longer applies itself: they wait for the user;
   - the candidate items.

## 9. Worker prompt template

Fill in the `<…>` parts and write it in the user's language.

```
You work in your own paseo workspace (a git worktree branched off <default branch>) on one item
of a TODO list. A foreman agent coordinates the list; you deliver this one item, from start to merged.

## The item
<item text, verbatim, plus absolute paths of attachments>
Reference: <the item's ticket key or TODO number, or "none">

## Context from the foreman
- <where to start: files, modules, earlier PRs on this subject>
- <what not to touch: files that other running workspaces own; the next items in this lane>
- <constraints: shared machine limits, snapshot or golden tests, decisions the user made>
- <verification: the exact fast check and pre-merge check, from the foreman block>

## How to work
- Read the project instructions (CLAUDE.md, AGENTS.md) first and follow them. Install
  dependencies in this fresh worktree.
- Prove every behaviour change with a test that you first see fail on the old code. For a visual
  effect, measure rendered pixels with and without the effect; a formula mirrored in a unit test
  proves nothing.
- A new end-to-end test: run only that test (filter by name) to see it red and green, never the
  whole file.
- The machine is shared with other workspaces. Queue heavy test runs the way the project
  prescribes. Run at most one browser at a time.
- One heavy step at a time: a verification chain, a browser run or a review subagent, never two
  at once.
- Change nothing outside your worktree. Leave symlinks you create into other checkouts in place:
  the foreman cleans up when archiving, and a deletion that needs permission stalls you.
- Don't write to the user's memory, docs or other shared notes. Put what's worth keeping in your
  report; the foreman decides where it goes.
- Don't deploy. You can't ask the user anything: make a defensible choice and report it.

## Finish
1. While building, run only targeted tests. When the diff is ready for review, run the project's
   fast check once.
2. Start a review subagent (in Claude Code: the Agent tool) that critically reviews your diff against the item and
   the project instructions. It reads the diff and may run targeted tests to prove a finding. It does
   not run the project's verification chain or browser tests. Address its findings; ask for a second
   round only if the first found something blocking.
3. Merge the default branch into your branch. Then run the project's pre-merge check ONCE on that
   merged tree (queued, if the project has a queue). Never run the deploy-level suite (end-to-end,
   recordings): the foreman runs that once at the end of the cycle.
4. Green? Run the merge-to-main skill with the reference above: commit, merge the default branch
   in, resolve conflicts, open a PR and merge it. Don't re-run the check after the merge. If the
   skill still brings in new commits from the default branch, run the fast check once more, not
   the chain. No such skill? Do the same with git and `gh`, and never merge through a failing
   check. Unless the project instructions say otherwise, commit in Conventional Commits with a
   `Refs: <reference>` footer, open the PR with `gh pr create --fill --title '<type>(<scope>):
   <summary> (<reference>)'` and merge it with `gh pr merge --merge`. No reference? Leave out the
   footer and the parentheses.
5. End with a short report:
   - the PR number and whether it is merged;
   - the choices you made;
   - the knobs to tune;
   - how the user checks it live;
   - anything you found outside this item, and anything worth keeping for docs or memory.
   If merging failed, say so explicitly, with the reason.
```

## 10. Heartbeat prompts

**A. Check (every 10 min)**

```
Foreman check: run `<script call> check <TODO path>`. NO CHANGE? Answer in one line; it already
names what waits on the user. Otherwise handle every line marked ! or *: done (a final report with
a merged PR, or a failed merge)? Close it out per foreman-start §6 (verify-pr, archive, state done or state unmark) and start the next
item. Stuck on a permission? Inspect it and answer. Idle with nothing running? Nudge it, phrased
as a continuation. All idle at once without a report? Treat it as a daemon restart (§6). A
DEFAULT DUE? Take it as the user's answer (§7) and say so in one line. Ask the user only in plain
text, never with a tool that blocks your turn, and open every report with the Waiting on you
block while a question is open (Asking the user). Never archive <own workspace id>. Don't deploy.
```

**B. Resume (every 5 h)**

```
Foreman resume check: run `<script call> check <TODO path>`. Did any running workspace stop on
a usage or token limit? Resume it with send_agent_prompt ("Continue where you left off"). If that
fails and its worktree holds uncommitted work, start an agent of another provider in the same
workspace with a handover prompt (what is done, what remains) and record it with `state start …
--agent <new id> --no-ticket`; archive and start fresh only when the worktree is clean. Then apply the check in foreman-start §6, including a DEFAULT DUE (§7). Never ask with a tool that blocks your turn. Never archive <own workspace id>.
```
