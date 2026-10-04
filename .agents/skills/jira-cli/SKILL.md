---
name: jira-cli
description: Install, check and use jira-cli (the `jira` command, github.com/ankitpokhrel/jira-cli) to read and change Jira issues from the terminal. Use for any request about Jira tickets, issues, epics, sprints or boards, for "set up jira-cli", "is jira working", and before running any `jira` command. Not for Atlassian's own `acli`.
---

# jira-cli

Talk to the user in their language. Do three checks, in order, then work.

## 1. Is it installed?

`command -v jira && jira version`. Found? Go to step 2.

Missing? Say what you will install and where, and wait for a yes. Then use the first line that fits:

- **macOS:** `brew tap ankitpokhrel/jira-cli && brew install jira-cli`
- **Windows:** `scoop bucket add extras && scoop install jira-cli` (in WSL, use the Linux script)
- **Linux:** the script below. It takes the newest release, checks its checksum and installs to
  `~/.local/bin`.

```sh
set -eu
case "$(uname -m)" in x86_64) A=x86_64;; aarch64|arm64) A=arm64;; armv6l|armv7l) A=armv6;; i386|i686) A=i386;; *) echo "unsupported CPU" >&2; exit 1;; esac
V=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/ankitpokhrel/jira-cli/releases/latest); V=${V##*/v}
B=https://github.com/ankitpokhrel/jira-cli/releases/download/v$V; F=jira_${V}_linux_${A}.tar.gz
T=$(mktemp -d); cd "$T"
curl -fsSL -O "$B/$F" -O "$B/checksums.txt"
grep " $F\$" checksums.txt | sha256sum -c -
tar -xzf "$F"
mkdir -p ~/.local/bin && install -m 0755 "jira_${V}_linux_${A}/bin/jira" ~/.local/bin/jira
cd ~ && rm -rf "$T"
```

Then run `jira version`. Not found? `~/.local/bin` is not on the PATH. Tell the user to add it.
Other methods (Nix, Docker, BSD): the [upstream install page](https://github.com/ankitpokhrel/jira-cli/wiki/Installation).

## 2. Does it log in?

`jira me` prints the user name. That works? Go to step 3.

"The tool needs a Jira API token", but the user already did the setup below? **This case is for a token
held in the env file `~/.config/jira-cli/env`.** Your shell is non-interactive and skipped the profile
that loads it. Run `. ~/.config/jira-cli/env && jira me`. That works? Begin every later `jira` command
the same way. A token from `.netrc` or the keychain needs none of this.

Still failing, or no env file? The user must do the setup in their own terminal. You cannot answer its
prompts, and the token must never pass through this chat. Give them these steps:

1. Create a token. **Jira Cloud:** https://id.atlassian.com/manage-profile/security/api-tokens.
   **Self-hosted:** a personal access token from the Jira profile (also `export JIRA_AUTH_TYPE=bearer`),
   or the login password for basic auth.
2. Store it in a file only they can read, and load it from the shell profile (bash and zsh):

   ```sh
   RC=~/.bashrc; [ -n "${ZSH_VERSION:-}" ] && RC=~/.zshrc
   mkdir -p ~/.config/jira-cli && (umask 077; : > ~/.config/jira-cli/env)
   printf 'Token: '; read -rs t; echo; printf 'export JIRA_API_TOKEN=%q\n' "$t" > ~/.config/jira-cli/env; unset t
   grep -q jira-cli/env "$RC" 2>/dev/null || echo '[ -f ~/.config/jira-cli/env ] && . ~/.config/jira-cli/env' >> "$RC"
   . "$RC"
   ```
3. Run `jira init`: type `Cloud` or `Local`, the server URL, the login (the email on Cloud) and the
   default project.

Then run `jira me` again yourself. Never `cat` the env file or the config, and never use `--debug`.

## 3. Work with it

Read `llm.md` in this folder in full before your first `jira` command. Its rules (machine-readable
output, no guessing of fields, confirm before destructive changes, never `jira init` unprompted)
come from the jira-cli authors and override your habits. It is an unmodified copy of
https://github.com/ankitpokhrel/jira-cli/blob/main/llm.md, kept here so the skill works when GitHub is slow.

`llm.md` does not cover which Jira project to use. Most users have more than one:

1. Look in the repo's `CLAUDE.md`, `AGENTS.md` or README for a project key or config path.
2. One-off: `jira issue list -p KEY`. Standing: `JIRA_CONFIG_FILE=<path>` or `-c <path>`.
3. Still unclear? Ask. Do not rerun `jira init` to switch project: that overwrites the shared config.
   A second config is made with `JIRA_CONFIG_FILE=~/.config/.jira/other.yml jira init`, run by the user.
