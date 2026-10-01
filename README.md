# agentic-workshop

Skills for running coding agents as a team.

## foreman-start

One agent acts as the **foreman** over a markdown TODO checklist. Every open item gets its own
[paseo](https://paseo.sh) workspace: a git worktree off the default branch, with
its own agent. At most two workspaces run at a time.

Each workspace does the whole job itself:
- implement the item;
- prove it with a test that first fails on the old code;
- run the project's fast check once, when the diff is ready for review;
- get a review subagent to review the diff;
- run the pre-merge check once, on the tree merged with the default branch;
- merge through a PR.

The foreman:
- plans the order by **file conflict**, so parallel workspaces never edit the same files;
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
resumes a cycle after a restart or a lost context.

### Requirements

- The paseo MCP server, with workspaces, agents and heartbeats.
- `git` with a remote, and the GitHub CLI `gh`, authenticated.
- Optional: paseo agent profiles, each with notes on what it is for. Without them, the workers
  copy the foreman's own settings.
- Optional: a `merge-to-main` skill in the workers' client. Without it, the workers merge with
  plain `gh`.

### Install

The two copies hold the same procedure. The Claude Code copy uses Claude's tool names. The
other follows the general Agent Skills layout (`.agents/skills/`), which Kimi Code and other
clients read.

```sh
# Claude Code, for all projects
cp -r .claude/skills/foreman-start ~/.claude/skills/

# Kimi Code or another Agent Skills client, for all projects
mkdir -p ~/.agents/skills && cp -r .agents/skills/foreman-start ~/.agents/skills/
```

For a single project, copy the folder into that project's `.claude/skills/` or `.agents/skills/`
instead. Start a new session afterwards so the skill is picked up.

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
- answer the decisions it brings up;
- ask it to deploy. It never deploys on its own.

## License

MIT, see [LICENSE](LICENSE).
