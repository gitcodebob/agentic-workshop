---
name: jira-cli
description: Install, check and use jira-cli (the `jira` command, github.com/ankitpokhrel/jira-cli) to read and change Jira issues from the terminal, and to download ticket attachments such as screenshots. Use for any request about Jira tickets, issues, epics, sprints, boards or attachments, for "set up jira-cli", "is jira working", and before running any `jira` command. Not for Atlassian's own `acli`.
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

## 4. Download an attachment

`jira-cli` cannot download attachments, and neither can Atlassian's `acli`. Call the Jira Cloud REST
API with `curl` instead. The script lists the attachments of an issue, then saves one to a new temp
folder. The credentials go to `curl` on stdin, so they never show in the process list or the output.
It needs `python3`. It sends credentials only to `https://*.atlassian.net`, and refuses files over 25 MB.

```sh
set -eu -o pipefail
KEY=DG-3 N=0                 # the issue key, and which attachment (0 is the first)
[ -n "${JIRA_API_TOKEN:-}" ] || . ~/.config/jira-cli/env
LIST=$(jira issue view "$KEY" --raw | python3 -c '
import json, sys
for i, a in enumerate(json.load(sys.stdin)["fields"].get("attachment", [])):
    print(i, a["filename"], a["mimeType"], a["size"], a["content"], sep="\t")')
printf '%s\n' "$LIST" | cut -f1-4
LINE=$(printf '%s\n' "$LIST" | sed -n "$((N+1))p"); [ -n "$LINE" ] || { echo "no attachment $N on $KEY" >&2; exit 1; }
URL=$(printf '%s' "$LINE" | cut -f5); NAME=$(printf '%s' "$LINE" | cut -f2)
case "$URL" in https://*) H=${URL#https://}; H=${H%%/*};; *) H=;; esac      # the host; a path cannot fake it
case "$H" in *.atlassian.net) ;; *) echo "unexpected host, not sending credentials" >&2; exit 1;; esac
EXT=${NAME##*.}; case "$EXT" in ""|*[!A-Za-z0-9]*) EXT=bin;; esac
D=$(mktemp -d); OUT=$D/$KEY-$N.$EXT
printf 'user = "%s:%s"\n' "$(jira me)" "$JIRA_API_TOKEN" | curl -fsSL --proto '=https' --max-filesize 26214400 --max-time 60 -K - -o "$OUT" "$URL" || { rmdir "$D"; exit 1; }
echo "$OUT"
```

Open the printed file with your image or file reader. Then delete its temp folder, by its literal
path: an attachment can hold private data, and `/tmp` is often RAM.

Self-hosted Jira with a PAT needs `Authorization: Bearer` instead of the `user` line, and a different
URL check. That is untested.
