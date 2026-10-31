#!/usr/bin/env python3
"""Deterministic helpers for the foreman-start skill.

Every subcommand prints a few short lines meant for an agent to read, and exits 0 unless it was
called wrongly. A failed side effect (a ticket move or comment, a workspace rename) is reported in
one line and never stops the cycle. No command waits on stdin, and every outside call has a timeout.

  find-todo  [PATH]                          pick the TODO file, say whether a cycle runs in it
  state      show|set|start|unmark|done  TODO ...
  name       [DONE TOTAL] [--ws ID]          name the own workspace `Foreman (DONE/TOTAL)`, or read it
  ticket     detect | move KEY start|done | comment KEY TEXT   [--todo TODO]
  check      TODO                            one scan of every running workspace and open question
  verify-pr  N [--todo TODO]                 is PR #N really merged, and what did it change
  capacity                                   cores, memory (zram counted), pressure, /tmp, running agents,
                                             room for light and heavy workers, a parallel limit

Open questions to the user are plain bullets under a `## Waiting on the user` heading in the TODO
file. `state show` lists them; `check` flags one whose `default: <option> by YYYY-MM-DD HH:MM +HH:MM`
has passed.

The run's count lives only in the foreman's own session and in its workspace name; nothing here
stores it.

Needs python3, git, gh and the paseo CLI. jira (jira-cli) or acli are optional.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BLOCK_RE = re.compile(r"<!--\s*foreman\b(.*?)-->", re.S)
ITEM_RE = re.compile(r"^([-*] \[)([ xX])(\]\s+)(.*)$")  # top level only; sub-items are notes
RUNNING_RE = re.compile(r"\s*← running:.*$")
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
OWN_KEY_RE = re.compile(r"^\W*([A-Z][A-Z0-9]+-\d+)\b|/browse/([A-Z][A-Z0-9]+-\d+)\b")
WAITING_RE = re.compile(r"^#+\s*Waiting on the user\b", re.I)
DEFAULT_RE = re.compile(r"(?:^|·)\s*default\s*:\s*([^·]+?)\s+by\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?\s*"
                        r"(Z|(?:UTC|GMT)?\s*[+-]\d{2}:?\d{2}|UTC|GMT)(?![\d:+-])", re.I)
JIRA_ENV = Path.home() / ".config/jira-cli/env"
# Codex's auto-reviewer denies escalations without a paseo permission request; a Codex worker
# running this long without an update may be stuck on one.
CODEX_SILENT_MINUTES = 15


def out(*lines):
    for line in lines:
        print(line)


def run(cmd, timeout=60, shell=False, input=None):
    """Run a command; return (exit code, stdout, stderr). A missing binary is exit 127, a timeout
    124. stdin is `input` on a pipe that closes, or else /dev/null, so nothing waits on it; a
    timeout kills the whole process group, so a child of the shell can't hold the pipes open."""
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=shell,
                             executable="/bin/bash" if shell else None, start_new_session=True)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    try:
        so, se = p.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 124, "", f"timed out after {timeout} s"
    return p.returncode, so.strip(), se.strip()


def item_key(text):
    """The item's own ticket key: one that leads its text, or a Jira /browse/ link. Other keys in
    the text (follow-ups, notes, `UTF-8`) are not the item's."""
    m = OWN_KEY_RE.search(text)
    return (m.group(1) or m.group(2)) if m else None


def one_line(text, limit=300):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def default_of(question):
    """None for a question without a default, else (option, deadline); the deadline is None when
    it can't be read. Only a choice that is easy to undo gets a default."""
    if not re.search(r"\bdefault\s*:", question, re.I):
        return None
    m = DEFAULT_RE.search(question)
    if not m:
        return "?", None
    tz = re.sub(r"^(UTC|GMT)\s*", "", m.group(4).upper()) or "Z"
    tz = "+00:00" if tz == "Z" else tz if ":" in tz else f"{tz[:3]}:{tz[3:]}"
    try:
        return m.group(1), datetime.fromisoformat(f"{m.group(2)}T{m.group(3)}{tz}")
    except ValueError:
        return m.group(1), None


def question_label(question):
    return item_key(question) or one_line(question.split(" · ")[0].strip("*_ "), 40)


# ---------------------------------------------------------------------------- TODO file

class Todo:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            sys.exit(f"error: no such TODO file: {path}")
        with open(self.path, newline="") as f:
            raw = f.read()
        self.nl = "\r\n" if "\r\n" in raw else "\n"
        self.text = raw.replace("\r\n", "\n")

    # -- foreman block
    def block(self):
        m = BLOCK_RE.search(self.text)
        return m.group(1) if m else None

    def field(self, key):
        """Value of a `key: value` segment in the block (segments split on ' · ')."""
        block = self.block() or ""
        m = re.search(rf"(?m)(?:^|·)\s*{re.escape(key)}\s*[:=]\s*([^·\n]*)", block)
        return m.group(1).strip() if m else None

    def set_line(self, key, value):
        """Set the whole `key: value` line in the block, adding it before `-->` if missing."""
        m = BLOCK_RE.search(self.text)
        if not m:
            sys.exit("error: the TODO file has no <!-- foreman … --> block yet; write the plan first")
        body = m.group(1)
        line = f"{key}: {value}"
        pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
        if pat.search(body):
            body = pat.sub(lambda _: line, body, count=1)
        else:
            body = body.rstrip("\n") + "\n" + line + "\n"
        self.text = self.text[: m.start(1)] + body + self.text[m.end(1):]

    def tracker(self):
        """(tool, {start: state, done: state}) from the block's tracker line."""
        m = re.search(r"(?m)^tracker\s*:(.*)$", self.block() or "")
        line = m.group(1) if m else ""
        tool = (line.split() or [None])[0]
        states = {k: v.strip() for k, v in re.findall(r"\b(start|done)\s*=\s*([^·\n]+)", line)}
        return tool, states

    def own_workspace(self):
        v = self.field("own workspace") or ""
        m = re.search(r"wks_\w+", v)
        return m.group(0) if m else (v.split()[0] if v else None)

    # -- checklist
    def items(self):
        """[(line index, checked, text without markers, running marker or '')]"""
        res = []
        for i, line in enumerate(self.text.split("\n")):
            m = ITEM_RE.match(line)
            if m:
                rest = m.group(4)
                r = RUNNING_RE.search(rest)
                res.append((i, m.group(2) != " ", RUNNING_RE.sub("", rest), r.group(0).strip() if r else ""))
        return res

    def find_item(self, query, open_only=True):
        all_items = self.items()
        cands = [it for it in all_items if not (open_only and it[1])]
        # A ticket key matches only the item's own key: DG-7 doesn't hit DG-78, and DG-78 doesn't
        # hit an item that merely mentions DG-78.
        is_key = bool(KEY_RE.fullmatch(query.upper()))
        hit = (lambda it: item_key(it[2]) == query.upper()) if is_key else (lambda it: query.lower() in it[2].lower())
        hits = [it for it in cands if hit(it)]
        if not hits and open_only:
            ticked = [it for it in all_items if it[1] and hit(it)]
            if len(ticked) == 1:
                sys.exit(f"error: {query!r} is already ticked (line {ticked[0][0] + 1}): "
                         f"{one_line(ticked[0][2], 100)}; nothing to do")
        if len(hits) != 1:
            what = "no" if not hits else f"{len(hits)}"
            lst = "".join(f"\n  line {it[0] + 1}: {one_line(it[2], 100)}" for it in (hits or cands))
            sys.exit(f"error: {what} {'open ' if open_only else ''}items match {query!r}:{lst}")
        return hits[0]

    def waiting(self):
        """The open questions: one plain bullet each under `## Waiting on the user`, indented
        lines joined to it. The next heading or checklist item ends the section. [(line index, text)]"""
        res, inside = [], False
        for i, line in enumerate(self.text.split("\n")):
            if line.startswith("#") or ITEM_RE.match(line):
                inside = bool(WAITING_RE.match(line))
            elif inside and re.match(r"[-*] ", line):
                res.append([i, line[2:].strip()])
            elif inside and res and line[:1].isspace() and line.strip():
                res[-1][1] += " " + line.strip()
        return [(i, x) for i, x in res]

    def replace_line(self, idx, new):
        lines = self.text.split("\n")
        lines[idx] = new
        self.text = "\n".join(lines)

    def line(self, idx):
        return self.text.split("\n")[idx]

    def save(self):
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".foreman-")
        with os.fdopen(fd, "w", newline="") as f:
            f.write(self.text.replace("\n", self.nl))
        os.chmod(tmp, self.path.stat().st_mode & 0o7777)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------- name

NAME_RE = re.compile(r"^Foreman \((\d+)/(\d+)\)$")


def own_workspace(ws=None):
    """(id, current name) of the given workspace, or of the one whose cwd is this directory."""
    workspaces, err = paseo_json(["workspace", "ls"])
    if workspaces is None:
        return ws, None, err
    here = {str(Path.cwd().resolve())}
    code, top, _ = run(["git", "rev-parse", "--show-toplevel"])
    if code == 0:
        here.add(str(Path(top).resolve()))
    for w in workspaces:
        if (ws and w.get("workspaceId") == ws) or (not ws and str(Path(w.get("cwd", "")).resolve()) in here):
            return w.get("workspaceId"), w.get("name"), None
    return ws, None, "no workspace with this directory as cwd" if not ws else f"{ws} not listed"


def cmd_name(a):
    if a.done is None:
        ws, name, err = own_workspace(a.ws)
        if not name:
            return out(f"name: unknown ({err})")
        m = NAME_RE.match(name)
        return out(f"name: {name!r} ({ws})"
                   + (f" → done {m.group(1)} of {m.group(2)}" if m else " → no run count in it"))
    if a.total is None or a.done < 0 or a.total < a.done:
        sys.exit("usage: foreman.py name DONE TOTAL (0 <= DONE <= TOTAL)")
    title = f"Foreman ({a.done}/{a.total})"
    if os.environ.get("FOREMAN_NO_RENAME"):
        return out(f"name: skipped by FOREMAN_NO_RENAME, would be {title!r}")
    ws, _, err = (a.ws, None, None) if a.ws else own_workspace()
    if not ws:
        return out(f"name FAILED ({err}); use rename_workspace with title {title!r}")
    code, _, err = run(["paseo", "workspace", "rename", ws, title])
    out(f"name: {ws} → {title!r}" if code == 0 else
        f"name FAILED ({one_line(err, 120) or f'exit {code}'}); use rename_workspace with title {title!r}")


# ---------------------------------------------------------------------------- find-todo

def cmd_find_todo(a):
    if a.path:
        cands = [Path(a.path)]
    else:
        code, top, _ = run(["git", "rev-parse", "--show-toplevel"])
        root = Path(top) if code == 0 else Path.cwd()
        cands = []
        for d in (root / ".scratch", root):
            found = sorted((p for p in d.glob("TODO*.md")
                            if re.search(r"(?m)^[-*] \[ \]", p.read_text(errors="ignore"))),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            if found:
                cands = found
                break
        if not cands:
            return out("todo: none (no TODO*.md with an open item in .scratch/ or the repo root); ask the user")
    t = Todo(cands[0])
    items = t.items()
    open_n = sum(1 for it in items if not it[1])
    running = [it for it in items if it[3]]
    out(f"todo: {t.path}",
        f"items: {open_n} open ({len(running)} running) · {len(items) - open_n} done")
    if t.block() is None:
        out("cycle: none yet → plan lanes, write the block")
    else:
        out("cycle: a block exists → resume; check every listed workspace first")
        out(f"own workspace in the block: {t.own_workspace() or '?'} → is that you? If not, `state set` it")
    for other in cands[1:4]:
        out(f"also: {other}")


# ---------------------------------------------------------------------------- state

def cmd_state(a):
    t = Todo(a.todo)
    if a.action == "show":
        items, waiting = t.items(), t.waiting()
        now = datetime.now(timezone.utc)
        if a.json:
            qs = []
            for i, x in waiting:
                d = default_of(x)
                qs.append({"line": i + 1, "text": x, "default": d and d[0],
                           "deadline": d[1].isoformat() if d and d[1] else None,
                           "due": bool(d and d[1] and d[1] <= now)})
            print(json.dumps({
                "todo": str(t.path), "block": t.block(), "own_workspace": t.own_workspace(),
                "items": [{"line": i + 1, "done": d, "text": x, "running": r} for i, d, x, r in items],
                "waiting": qs,
            }, indent=1, ensure_ascii=False))
            return
        out(f"todo: {t.path}", f"own workspace: {t.own_workspace() or '?'}")
        for i, d, x, r in items:
            out(f"  {'x' if d else ('>' if r else ' ')} line {i + 1}: {one_line(x, 90)}" + (f"  {r}" if r else ""))
        if waiting:
            out("waiting on the user:")
        for i, x in waiting:
            d = default_of(x)
            due = "  ← default due" if d and d[1] and d[1] <= now else ""
            out(f"  ? line {i + 1}: {one_line(x, 200)}{due}")
        return

    if a.action == "set":
        t.set_line(a.key, a.value)
        t.save()
        return out(f"set {a.key}: {a.value}")

    if a.action == "start":
        i, _, text, _ = t.find_item(a.item)
        base = RUNNING_RE.sub("", t.line(i))
        t.replace_line(i, f"{base} ← running: {a.ws} / agent {a.agent} / {a.profile}")
        t.save()
        out(f"running: line {i + 1}: {one_line(text, 80)}")
        return move_item_ticket(t, text, "start", a.no_ticket)

    if a.action == "unmark":
        i, _, text, r = t.find_item(a.item)
        if r:
            t.replace_line(i, RUNNING_RE.sub("", t.line(i)))
            t.save()
        return out(f"unmarked: line {i + 1}: {one_line(text, 80)}" if r else "nothing to unmark")

    if a.action == "done":
        i, _, text, _ = t.find_item(a.item)
        m = ITEM_RE.match(RUNNING_RE.sub("", t.line(i)))
        rest = m.group(4).rstrip()
        if a.pr and not re.search(rf"PR #{a.pr}\b", rest):
            rest += f" — PR #{a.pr}"
        t.replace_line(i, f"{m.group(1)}x{m.group(3)}{rest}")
        t.save()
        out(f"ticked: line {i + 1}: {one_line(rest, 80)} → count it and run `name <done> <total>`")
        return move_item_ticket(t, text, "done", a.no_ticket)


def move_item_ticket(t, text, which, skip):
    key = item_key(text)
    if skip or not key or t.tracker()[0] in (None, "none"):
        return
    ticket_move(key, which, t)


# ---------------------------------------------------------------------------- ticket

def jira_sh(args, input=None):
    """Run jira with the env-file token loaded when the shell did not load it."""
    load = f'[ -n "${{JIRA_API_TOKEN:-}}" ] || {{ [ -f {JIRA_ENV} ] && . {JIRA_ENV}; }}; '
    return run(load + "jira " + " ".join(_q(x) for x in args), shell=True, timeout=60, input=input)


def _q(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def detect_tracker():
    if shutil.which("jira"):
        code, me, _ = jira_sh(["me"])
        if code == 0 and me:
            return "jira-cli", me
    if shutil.which("acli"):
        code, so, se = run(["acli", "jira", "auth", "status"])
        if code == 0:
            return "acli", one_line(so or se, 80)
    return "none", ""


def cmd_ticket(a):
    if a.action == "detect":
        tracker, who = detect_tracker()
        return out(f"tracker: {tracker}" + (f" ({who})" if who else "")
                   + ("" if tracker != "none" else " → say so once and carry on; don't install or log in"))
    if a.action == "comment":
        # jira-cli turns a bare number into a key of its default project: take only a full key.
        if not KEY_RE.fullmatch((a.key or "").upper()) or not (a.which or "").strip():
            sys.exit("usage: foreman.py ticket comment KEY TEXT [--todo TODO]  (KEY like ABC-123; TEXT quoted)")
        return ticket_comment(a.key.upper(), a.which, Todo(a.todo) if a.todo else None)
    if not a.key or a.which not in ("start", "done"):
        sys.exit("usage: foreman.py ticket move KEY start|done [--todo TODO]")
    ticket_move(a.key, a.which, Todo(a.todo) if a.todo else None)


def tracker_of(todo):
    """The block's tracker, or the one `detect` finds when the block names none."""
    tracker = todo.tracker()[0] if todo is not None else None
    return tracker if tracker in ("jira-cli", "acli", "none") else detect_tracker()[0]


def ticket_comment(key, text, todo=None):
    tracker = tracker_of(todo)
    if tracker == "none":
        return out(f"ticket {key}: no tracker, no comment")
    if tracker == "jira-cli":
        # jira-cli reads stdin whenever it is not a terminal, even with the body as an argument,
        # so an open stdin hangs it. Give it the body on a pipe that closes. No REST fallback:
        # after a timeout the comment may be in already, and a second route would post it twice.
        code, so, se = jira_sh(["issue", "comment", "add", key, "--no-input", "--template", "-"], input=text)
    else:
        code, so, se = run(["acli", "jira", "workitem", "comment", "create", "--key", key, "--body", text])
    if code == 0:
        return out(f"ticket {key}: comment added ({tracker})")
    if code == 124:
        return out(f"ticket {key}: comment {se} ({tracker}); it may be there anyway: look at the "
                   "ticket before you post it again. Don't hold up the cycle.")
    out(f"ticket {key}: comment FAILED ({tracker}): {one_line(se or so, 240)}",
        "  → it stands in the TODO file and in your message anyway. Don't hold up the cycle.")


def ticket_move(key, which, todo=None):
    state = {"start": "In Progress", "done": "Done"}[which]
    if todo is not None:
        state = todo.tracker()[1].get(which) or state
    tracker = tracker_of(todo)
    if tracker == "none":
        return out(f"ticket {key}: no tracker, not moved")

    if tracker == "jira-cli":
        code, raw, _ = jira_sh(["issue", "view", key, "--raw"])
        if code == 0:
            try:
                cur = json.loads(raw)["fields"]["status"]["name"]
                if cur.lower() == state.lower():
                    return out(f"ticket {key}: already {cur!r}")
            except (ValueError, KeyError, TypeError):
                pass
        code, so, se = jira_sh(["issue", "move", key, state])
    else:
        code, so, se = run(["acli", "jira", "workitem", "transition", "--key", key, "--status", state, "--yes"])
    if code == 0:
        return out(f"ticket {key}: moved to {state!r} ({tracker})")
    out(f"ticket {key}: move to {state!r} FAILED ({tracker}): {one_line(se or so, 240)}",
        "  → the error lists the valid states: take the plain equivalent, set it in the block "
        "(tracker line, start= / done=) and retry, or ask the user once. Don't hold up the cycle.")


# ---------------------------------------------------------------------------- check

def paseo_json(args):
    code, so, se = run(["paseo", *args, "--json"], timeout=30)
    if code != 0:
        return None, one_line(se or so, 160)
    try:
        return json.loads(so), None
    except ValueError:
        return None, "unreadable JSON"


def last_text(agent):
    code, so, _ = run(["paseo", "logs", agent, "--filter", "text", "--tail", "1"], timeout=30)
    return one_line(so, 400) if code == 0 else ""


def minutes_since(iso):
    """Whole minutes since an ISO timestamp such as paseo's `UpdatedAt`, or None if unreadable."""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if then.tzinfo is None:
        return None
    return int((datetime.now(timezone.utc) - then).total_seconds() // 60)


def check_waiting(t):
    """(lines that need the foreman, labels of the other open questions)"""
    flags, open_ = [], []
    now = datetime.now(timezone.utc)
    for i, text in t.waiting():
        label, d = question_label(text), default_of(text)
        if d and d[1] and d[1] <= now:
            flags.append(f"! {label}: DEFAULT DUE since {d[1]:%Y-%m-%d %H:%M %z} → take {d[0]!r} as "
                         "the user's answer (§7) and say so in one line")
        elif d and not d[1]:
            flags.append(f"* {label}: default without a readable deadline (line {i + 1}) → write it "
                         "as `default: <option> by YYYY-MM-DD HH:MM +HH:MM`")
        else:
            open_.append(label)
    return flags, open_


def cmd_check(a):
    t = Todo(a.todo)
    running = []
    for i, _, text, r in t.items():
        if r:
            ws = re.search(r"wks_\w+", r)
            ag = re.search(r"agent\s+([0-9a-f-]{6,})", r)
            running.append((i, text, ws.group(0) if ws else None, ag.group(1) if ag else None))
    wait_flags, wait_open = check_waiting(t)
    wait_note = f"waiting on the user: {', '.join(wait_open)}" if wait_open else ""
    if not running:
        return out("running: none → start the next item, or finish the cycle (§8) when all are ticked",
                   *wait_flags, *(["  " + wait_note] if wait_note else []))

    workspaces, err = paseo_json(["workspace", "ls"])
    if workspaces is None:
        return out(f"paseo unreachable ({err}): is the daemon down? check its log, then resume (§6)",
                   *wait_flags)
    live_ws = {w.get("workspaceId") for w in workspaces}

    lines, idle_no_pr, actionable = [], 0, False

    for i, text, ws, ag in running:
        label = KEY_RE.search(text).group(0) if KEY_RE.search(text) else one_line(text, 40)
        if not ag:
            lines.append(f"? {label}: no agent id in the marker on line {i + 1}")
            actionable = True
            continue
        info, err = paseo_json(["inspect", ag])
        if info is None:
            lines.append(f"? {label}: agent {ag[:8]} not found ({err})")
            actionable = True
            continue
        status = (info.get("Status") or "?").lower()
        provider = (info.get("Provider") or "?").lower()
        perms = info.get("PendingPermissions") or []
        upd = info.get("UpdatedAt") or ""
        ws_note = "" if ws in live_ws else " · WORKSPACE GONE (archived or lost?)"
        actionable |= bool(ws_note)
        if perms:
            actionable = True
            for p in perms:
                lines.append(f"! {label} ({provider}): PERMISSION pending · {one_line(json.dumps(p, ensure_ascii=False), 300)}"
                             " → inspect the target, then respond_to_permission")
        if status == "running":
            silent = minutes_since(upd)
            stall = ""
            if provider == "codex" and silent is not None and silent > CODEX_SILENT_MINUTES:
                actionable = True
                stall = (f" · no update for {silent} min: may be waiting on auto-review (a denial"
                         " doesn't reach paseo) → get_agent_activity, then nudge (§6)")
            mark = "!" if ws_note else "*" if stall else " "
            lines.append(f"{mark} {label}: running ({provider}, {upd[11:16]}Z){ws_note}{stall}")
            continue
        actionable = True
        msg = last_text(ag)
        prs = re.findall(r"(?:PR\s*#|/pull/)(\d+)", msg)
        verdict = ""
        if prs:
            code, so, _ = run(["gh", "pr", "view", prs[0], "--json", "state"], timeout=30)
            state = json.loads(so).get("state") if code == 0 and so else "?"
            verdict = f" · PR #{prs[0]} {state}"
            if state == "MERGED":
                verdict += " → looks done: `verify-pr`, archive, `state done` (§6)"
        else:
            idle_no_pr += 1
        lines.append(f"* {label}: {status} ({provider}){ws_note}{verdict}"
                     f" · last: {msg or '(no text)'}")


    if idle_no_pr == len(running) and len(running) > 1:
        lines.append("! ALL workers idle without a PR: likely a daemon restart (check its log for an OOM), "
                     "resume each with what was running (§6)")
    elif idle_no_pr:
        lines.append("  idle without a PR: waiting on a background step, or stopped → nudge as a continuation (§6)")
    lines.extend(wait_flags)
    if not (actionable or wait_flags):
        lines.insert(0, f"NO CHANGE: all {len(running)} workers running, no permission pending"
                     + (f" · {wait_note}" if wait_note else ""))
    elif wait_note:
        lines.append("  " + wait_note)
    out(*lines)


# ---------------------------------------------------------------------------- verify-pr

def cmd_verify_pr(a):
    fields = "number,title,state,mergedAt,mergeCommit,baseRefName,headRefName,url,files,additions,deletions"
    code, so, se = run(["gh", "pr", "view", str(a.pr), "--json", fields], timeout=60)
    if code != 0:
        return out(f"PR #{a.pr}: cannot read it ({one_line(se, 200)})")
    pr = json.loads(so)
    if pr["state"] != "MERGED":
        return out(f"NOT MERGED: PR #{a.pr} is {pr['state']} · {pr['title']} · {pr['url']}",
                   "→ don't tick the item; leave its ticket where it is")
    base = pr["baseRefName"]
    want = Todo(a.todo).field("default branch") if a.todo else None
    want = want.split()[0] if want else None
    sha = (pr.get("mergeCommit") or {}).get("oid", "")
    run(["git", "fetch", "-q", "origin", base], timeout=120)
    on_base, _, _ = run(["git", "merge-base", "--is-ancestor", sha, f"origin/{base}"]) if sha else (1, "", "")
    out(f"MERGED: PR #{a.pr} {pr['title']} · {pr['mergedAt']} · into {base} @ {sha[:9]}"
        f" ({'on' if on_base == 0 else 'NOT on'} origin/{base})"
        + (f" · WARNING: default branch is {want}" if want and want != base else ""),
        f"diff: {len(pr['files'])} files, +{pr['additions']} −{pr['deletions']}")
    for f in sorted(pr["files"], key=lambda f: -(f["additions"] + f["deletions"]))[: a.limit]:
        out(f"  {f['path']}  +{f['additions']} −{f['deletions']}")
    if len(pr["files"]) > a.limit:
        out(f"  … {len(pr['files']) - a.limit} more")
    out(f"key hunks: gh pr diff {a.pr}  (or git show {sha[:9]} -- <file>)")


# ---------------------------------------------------------------------------- capacity

def meminfo():
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) / 1024 / 1024  # GiB
    except OSError:
        pass
    return info


DEFAULT_PARALLEL = 3
LIGHT_GIB = 0.4  # a regular worker peaks at about this much RAM
HEAVY_GIB = 1.3  # one with headless Chrome or a large test suite; the foreman decides which items are heavy
RESERVE_GIB = 0.5  # kept free for the system; at least a tenth of the total
PSI_SOME_WARN = 10.0  # % of the last minute that some task stalled on memory
PSI_FULL_NO_ZRAM = 5.0  # % of the last 10 s that every task stalled: zram is working hard already
SWAPIN_BUSY = 1000  # pages per second swapped in, about 4 MiB/s: the machine is thrashing


def read_pressure():
    """/proc/pressure/memory as {"some": {"avg10": …, "avg60": …}, "full": {…}}; {} without PSI."""
    pressure = {}
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            kind, *fields = line.split()
            pressure[kind] = {k: float(v) for k, v in (f.split("=") for f in fields) if k.startswith("avg")}
    except (OSError, ValueError):
        return {}
    return pressure


def swap_in_rate(seconds=1.0):
    """Pages swapped in per second, over a short sample; None when /proc/vmstat can't say."""
    def pswpin():
        for line in Path("/proc/vmstat").read_text().splitlines():
            if line.startswith("pswpin "):
                return int(line.split()[1])
    try:
        before, start = pswpin(), time.monotonic()
        time.sleep(seconds)
        after, end = pswpin(), time.monotonic()
    except (OSError, ValueError):
        return None
    return None if before is None or after is None else (after - before) / (end - start)


def zram_room():
    """(GiB that zram can still take, compression ratio) over the zram devices in use as swap, or
    None without any. The ratio is clamped, so a stretch of data that compresses well doesn't
    promise more than the next stretch delivers. A resident-memory limit on a device caps its room."""
    try:
        swaps = {l.split()[0] for l in Path("/proc/swaps").read_text().splitlines()[1:] if l.strip()}
    except OSError:
        return None
    devs = []
    for dev in sorted(Path("/sys/block").glob("zram*")):
        if f"/dev/{dev.name}" not in swaps:
            continue
        try:
            size = int((dev / "disksize").read_text())
            orig, compr, used, limit = (int(x) for x in (dev / "mm_stat").read_text().split()[:4])
        except (OSError, ValueError):
            continue
        devs.append((size, orig, compr, used, limit))
    if not devs:
        return None
    orig, compr = sum(d[1] for d in devs), sum(d[2] for d in devs)
    ratio = orig / compr if compr and orig >= 2**26 else 2.0  # under 64 MiB there is too little data to tell
    ratio = min(3.0, max(1.5, ratio))
    room = sum(max(0, min(size - o, (limit - used) * ratio) if limit else size - o)
               for size, o, _, used, limit in devs)
    return room / 2**30, ratio


def cmd_capacity(a):
    cores = os.cpu_count() or 1
    mem = meminfo()
    total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
    swap_used = mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0
    code, fstype, _ = run(["findmnt", "-n", "-o", "FSTYPE", "/tmp"])
    tmp_tmpfs = code == 0 and fstype == "tmpfs"
    du = shutil.disk_usage("/tmp")
    agents, _ = paseo_json(["ls", "-g"])
    busy = sum(1 for x in agents or [] if x.get("status") == "running")
    psi = read_pressure()
    some60, full10 = psi.get("some", {}).get("avg60"), psi.get("full", {}).get("avg10")
    swapin = swap_in_rate()
    thrashing = swapin is not None and swapin > SWAPIN_BUSY
    stressed = thrashing or (full10 or 0) > PSI_FULL_NO_ZRAM

    # Size on the memory that is free now, not the total: other processes already hold their share.
    # Behind a reserve for the system, the kernel can free more by compressing cold anonymous pages
    # into zram: half of the anonymous memory, no more than zram has room for, and each page stays
    # in RAM at 1/ratio of its size. None of that while the machine is already struggling.
    reserve = max(RESERVE_GIB, 0.1 * total)
    zram = zram_room()
    bonus = 0.0
    if zram and not stressed:
        room, ratio = zram
        bonus = min(room, 0.5 * mem.get("AnonPages", 0)) * (1 - 1 / ratio)
    headroom = max(0.0, avail - reserve + bonus)
    light = int(headroom / LIGHT_GIB)
    fit = max(1, min(cores, light))
    if headroom >= HEAVY_GIB:
        extra = int((headroom - HEAVY_GIB) / LIGHT_GIB)
        fits = f"{light} light, or 1 heavy" + (f" + {extra} light" if extra else "")
    else:
        fits = f"{light} light, no heavy (it needs {HEAVY_GIB} GiB)"

    if zram:
        zram_line = f"zram: {zram[0]:.1f} GiB room, compresses {zram[1]:.1f}:1 · counted: +{bonus:.1f} GiB"
        zram_line += " (not while under pressure)" if stressed else ""
    else:
        zram_line = "zram: not in use as swap"
    if psi:
        stall = f"memory stalls some {some60:.1f}% (60 s), full {full10:.1f}% (10 s)"
    else:
        stall = "no PSI on this kernel"
    out(f"cores: {cores} · load(1m): {load:.1f} · running agents: {busy if agents is not None else '?'}",
        f"memory: {total:.1f} GiB total, {avail:.1f} GiB available · swap used: {swap_used:.1f} GiB",
        zram_line,
        f"pressure: {stall}" + (f" · swap-in {swapin:.0f} pages/s" if swapin is not None else ""),
        f"headroom: {headroom:.1f} GiB (available {avail:.1f} − reserve {reserve:.1f} + zram {bonus:.1f})",
        f"a worker counts {LIGHT_GIB} GiB, a heavy one (headless Chrome, a large test suite) {HEAVY_GIB} GiB;"
        " at most one heavy at a time",
        f"fits in memory: {fits}",
        f"/tmp: {'tmpfs (counts as RAM)' if tmp_tmpfs else fstype or '?'} · "
        f"{du.used / 2**30:.1f} of {du.total / 2**30:.1f} GiB used")
    warn = []
    if some60 is not None and some60 > PSI_SOME_WARN:
        warn.append(f"memory pressure ({some60:.0f}% of the last minute stalled)")
    if thrashing:
        warn.append(f"swap is thrashing ({swapin:.0f} pages/s in)")
    if not psi and swap_used > total / 2:  # without PSI the size of the swap is all there is to go by
        warn.append("heavy swap use")
    if load > cores * 1.5:
        warn.append("load well above the core count")
    if tmp_tmpfs and du.used > du.total / 2:
        warn.append("/tmp is over half full and lives in RAM")
    if warn:
        out("warning: " + "; ".join(warn) + " → clean stale caches, keep the limit low")
    suggest = 1 if warn else min(DEFAULT_PARALLEL, fit)
    out(f"parallel: suggest {suggest}" + (f" (the machine fits {fit}; raise only when the user asks)" if fit > DEFAULT_PARALLEL else "")
        + " · project instructions may lower it")
    if a.caches or warn:
        code, so, _ = run("du -sxm /tmp/* /tmp/.[!.]* 2>/dev/null | sort -rn | head -5", shell=True, timeout=20)
        if so:
            out("largest in /tmp (MiB):", *("  " + l for l in so.splitlines()))


# ---------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="foreman.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("find-todo", help="pick the TODO file")
    p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_find_todo)

    p = sub.add_parser("state", help="read or change the foreman block and the checklist")
    ss = p.add_subparsers(dest="action", required=True)
    s = ss.add_parser("show"); s.add_argument("todo"); s.add_argument("--json", action="store_true")
    s = ss.add_parser("set", help="set one `key: value` line in the block")
    s.add_argument("todo"); s.add_argument("key"); s.add_argument("value")
    s = ss.add_parser("start", help="mark an item running, move its ticket")
    s.add_argument("todo"); s.add_argument("item"); s.add_argument("--ws", required=True)
    s.add_argument("--agent", required=True); s.add_argument("--profile", default="own settings")
    s.add_argument("--no-ticket", action="store_true")
    s = ss.add_parser("unmark", help="drop an item's running marker (failed merge, restart)")
    s.add_argument("todo"); s.add_argument("item")
    s = ss.add_parser("done", help="tick an item, move its ticket")
    s.add_argument("todo"); s.add_argument("item"); s.add_argument("--pr")
    s.add_argument("--no-ticket", action="store_true")
    p.set_defaults(fn=cmd_state)

    p = sub.add_parser("name", help="name the own workspace `Foreman (DONE/TOTAL)`, or read the name")
    p.add_argument("done", nargs="?", type=int); p.add_argument("total", nargs="?", type=int)
    p.add_argument("--ws", help="workspace id; default: the one whose cwd is this directory")
    p.set_defaults(fn=cmd_name)

    p = sub.add_parser("ticket", help="detect the tracker, move a ticket, or comment on it")
    p.add_argument("action", choices=["detect", "move", "comment"])
    p.add_argument("key", nargs="?")
    p.add_argument("which", nargs="?", metavar="start|done|TEXT",
                   help="move: start or done; comment: the text, as one quoted argument")
    p.add_argument("--todo")
    p.set_defaults(fn=cmd_ticket)

    p = sub.add_parser("check", help="scan every running workspace and open question")
    p.add_argument("todo")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("verify-pr", help="is the PR merged, and what did it change")
    p.add_argument("pr"); p.add_argument("--todo"); p.add_argument("--limit", type=int, default=12)
    p.set_defaults(fn=cmd_verify_pr)

    p = sub.add_parser("capacity", help="machine headroom and a parallel limit")
    p.add_argument("--caches", action="store_true", help="also list the largest entries in /tmp")
    p.set_defaults(fn=cmd_capacity)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
