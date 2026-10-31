# agentic-workshop

Skills for running coding agents as a team.

## foreman-start

One agent acts as the **foreman** over a markdown or Jira TODO checklist. Every open item gets its own
[paseo](https://paseo.sh) workspace: a git worktree off the default branch, with
its own agent. At most three workspaces run at a time, fewer when the machine's free RAM or the project's
instructions call for it.

Each workspace does the whole job itself:
- implement the item;
- prove it with a test that first fails on the old code;
- run the project's fast check once, when the diff is ready for review;
- get a review subagent to review the diff;
- run the pre-merge check once, on the tree merged with the default branch;
- merge through a PR.

The foreman:
- plans the order by **file conflict**, so parallel workspaces never edit the same files;
- checks the free RAM before it starts, to see how many workspaces fit, and lets the project's
  instructions lower that: note heavy test stages or machine limits in `CLAUDE.md` or `AGENTS.md`;
- reads the project's verification stages and names the right command in every prompt, so each
  stage runs once, when it proves something new;
- writes self-contained prompts;
- gives each workspace the paseo agent profile whose notes fit the item;
- watches with heartbeats, catching missed signals, pending permission requests, usage-limit
  stalls and daemon restarts;
- checks each merge itself;
- archives the workspace, ticks the item off with its PR number, and reports to you;
- runs the deploy-level check (end-to-end tests, recordings) once at the end of the cycle.

It keeps its state in a comment block at the top of the TODO file. So `/foreman-start` also
resumes a cycle after a restart or a lost context. While a cycle runs, the foreman's own
workspace is named after the run's progress, such as `Foreman (3/7)`. The foreman keeps that
count in its own session; it isn't stored in the TODO file or anywhere else.

The mechanical steps run through one script, `scripts/foreman.py`, rather than through the
model: picking the TODO file, writing the block and the checklist markers, renaming the workspace, moving and commenting on tickets, the heartbeat scan of all workers, checking that a PR is
really merged, and checking the machine's free RAM (zram counted, memory pressure watched), which sets the parallel limit (at most three; a regular worker counts 0.4 GiB, a heavy one 1.3 GiB). Run it with `--help`
for the commands.

### Requirements

- The paseo MCP server, with workspaces, agents and heartbeats.
- `git` with a remote, and the GitHub CLI `gh`, authenticated.
- `python3` and the paseo CLI (`paseo`), for the script.
- Optional: paseo agent profiles, each with notes on what it is for. Without them, the workers
  copy the foreman's own settings.
- Optional: the `merge-to-main` skill below, in the workers' client. Without it, the workers merge
  with plain `gh`.

### Install

The skills live in `.agents/skills/`, the general Agent Skills layout that Codex, Kimi Code and
other clients read. `.claude/skills` is a symlink to it, for Claude Code. Install by symlinking
each skill to this checkout, so every client reads the same files and a `git pull` updates them:

```sh
REPO=$PWD   # this checkout
# ~/.claude/skills for Claude Code; ~/.agents/skills for Codex, Kimi Code and other clients
for d in ~/.claude/skills ~/.agents/skills; do
  mkdir -p "$d"
  for s in foreman-start merge-to-main; do
    if [ -e "$d/$s" ] || [ -L "$d/$s" ]; then echo "$d/$s exists: remove it first"; continue; fi
    ln -s "$REPO/.agents/skills/$s" "$d/$s"
  done
done
```

The check matters: `ln -s` onto an existing folder puts the link inside it. For a single project,
link the folder into that project's `.claude/skills/` or `.agents/skills/` instead.
Start a new session afterwards so the skill is picked up.

### Use

Write a checklist, for example `.scratch/TODO.md`:

```md
# Controls
- [ ] Make J fire the cannon
- [ ] Show an icon per colour in the key legend

# Weather
- [ ] Add a storm weather type with lightning
```

Then run `/foreman-start`, or `/foreman-start path/to/TODO.md`. Without a path, it takes the
newest `TODO*.md` with open items, looking in `.scratch/` first and then the repo root.

While it runs you can:
- add items to the list;
- answer the decisions it brings up. It asks them in plain text and keeps the other workspaces
  going meanwhile. Open questions stand under `## Waiting on the user` in the list, on the item's
  ticket, and at the top of each of its messages. A small choice that is easy to undo may get a
  default with a deadline; a product choice always waits for you;
- ask it to deploy. It never deploys on its own.

## merge-to-main

Gets the current branch or worktree into the default branch: commit open work, merge the default
branch in, resolve conflicts, open a PR, wait for its checks and merge it. Plain `git` and `gh`, so
any client can run it. The foreman's workers use it to merge their own work. Install it like
`foreman-start` above.

## jira-cli

Gets an agent working with Jira through [jira-cli](https://github.com/ankitpokhrel/jira-cli), the
`jira` command. The skill:
- checks that `jira` is installed, and installs it on request: Homebrew, Scoop, or on Linux the
  newest release binary with its checksum verified;
- checks the login with `jira me`, and walks you through the API token and `jira init` in your own
  terminal, so the token never passes through the chat;
- makes the agent read the jira-cli authors' own agent rules (`llm.md`) before its first command;
- picks the right Jira project when you have more than one;
- downloads ticket attachments such as screenshots, which neither `jira-cli` nor Atlassian's `acli` can.

Needs `curl` (Linux install, attachments), `python3` (attachments), and a Jira API token. Install
it like `foreman-start` above, with `jira-cli` as the folder. Then ask about a ticket, or run `/jira-cli`.

`llm.md` is an unmodified copy of upstream's, taken at commit `e74646e` (22 Sep 2026). It is kept
in the skill so nothing depends on GitHub at run time. To refresh it, then update the commit
here:

```sh
gh api repos/ankitpokhrel/jira-cli/contents/llm.md \
  -H 'Accept: application/vnd.github.raw' > .agents/skills/jira-cli/llm.md
```

## Editing the skills

Edit `.agents/skills/`; `.claude/skills` is a symlink to it, so there is nothing to copy. CI
checks on every push that the symlink is still there.

## Versions

Every merge into `main` gets the next version tag from CI (`.github/workflows/release.yml`).
It bumps the patch number by default. Label the PR `release:minor` or `release:major` to bump that
part instead, or `release:skip` to tag nothing.

- `v1.0.0`: `foreman-start` for Claude Code workers.
- `v1.1.0`: provider-neutral `foreman-start`, for Claude, Codex and Kimi workers; `check` shows
  each worker's provider and flags a Codex worker that has been silent for a while. `.agents/skills/`
  is the single source, `merge-to-main` is part of the repo, and CI tags every merge into `main`.

## License

MIT, see [LICENSE](LICENSE). The `llm.md` in the jira-cli skill is © 2022 Ankit Pokhrel, also MIT,
copied from [jira-cli](https://github.com/ankitpokhrel/jira-cli).
