#!/usr/bin/env python3
"""journal.py — journal-recorder engine.

Single source of truth behind the Stop/PostCompact hooks and the
journal-recorder agent. Stdlib only.

Subcommands:
  hook stop|compact   fast path: dedup + substance check, extract transcript,
                      spawn detached writer, exit immediately
  write               background writer: claude -p (haiku, falls back to
                      codex exec on Codex-only machines) -> entry file,
                      INDEX.md, git commit, dedup marker
  digest              roll last N days of entries into digests/YYYY-Wnn.md
  resolve-dir         print journal root (for the agent)
  check               print SKIP/PROCEED dedup verdict for current project
  finalize            stamp marker + rebuild INDEX.md + git commit
                      (for agent-written entries)
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

MODEL = "claude-haiku-4-5-20251001"
DEDUP_WINDOW_SECS = 1800
DIGEST_BUDGET_CHARS = 40_000
MIN_SUBSTANTIVE_MSGS = 4
SUBSTANTIVE_TEXT_CHARS = 50
CLAUDE_TIMEOUT_SECS = 300
FALLBACK_EXCERPT_CHARS = 15_000

SYSTEM_PROMPT = (
    "You are a journal writer. Your only job is to produce clean markdown "
    "journal entries. Never use tools, never ask questions, never ask for "
    "permissions. Just output the markdown text."
)

PROMPT_TEMPLATE = """Analyze this session log and write a structured markdown journal entry. \
The log contains USER/ASSISTANT messages and TOOL[...] lines showing commands run and files edited. \
Output ONLY the markdown, starting directly with the # title.

Required sections:
# <descriptive title>
## TL;DR
## What Was Accomplished
## Commands & Scripts Run
## Files Created / Modified
## Key Decisions
## Problems & Solutions
## Action Items
## Tags

Date: {date}

SESSION LOG:
{digest}"""


# ── paths & logging ──────────────────────────────────────────────────────────

def journal_root():
    cfg = os.path.expanduser("~/.claude/.journal-folder")
    try:
        with open(cfg) as f:
            raw = f.read().strip()
        if raw:
            return os.path.expanduser(raw)
    except OSError:
        pass
    return os.path.expanduser("~/claude-journal")


def log_line(msg):
    root = journal_root()
    try:
        os.makedirs(root, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(root, ".journal.log"), "a") as f:
            f.write(f"{stamp} {msg}\n")
    except OSError:
        pass


def slugify(text, max_len=60):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].rstrip("-") or "session"


def project_slug(cwd):
    base = os.path.basename((cwd or "").rstrip("/"))
    return slugify(base, 40) if base else "misc"


def unique_path(directory, base):
    path = os.path.join(directory, base + ".md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{n}.md")
        n += 1
    return path


# ── dedup marker (per project) ───────────────────────────────────────────────

def marker_path(root, project):
    return os.path.join(root, project, ".last-written")


def is_duplicate(root, project, now_ts):
    try:
        with open(marker_path(root, project)) as f:
            last_ts = int(f.read().split()[0])
        return now_ts - last_ts < DEDUP_WINDOW_SECS
    except (OSError, ValueError, IndexError):
        return False


def stamp_marker(root, project, session_id=""):
    os.makedirs(os.path.join(root, project), exist_ok=True)
    with open(marker_path(root, project), "w") as f:
        f.write(f"{int(time.time())} {session_id}\n")


# ── transcript extraction ────────────────────────────────────────────────────

def format_tool_use(block):
    name = block.get("name", "?")
    inp = block.get("input") or {}
    if name == "Bash":
        cmd = str(inp.get("command", ""))[:300]
        desc = str(inp.get("description", ""))
        return f"TOOL[Bash]: {cmd}" + (f"  # {desc}" if desc else "")
    if name in ("Edit", "Write", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or "?"
        return f"TOOL[{name}]: {path}"
    return f"TOOL[{name}]"


def extract_digest(transcript_path):
    """Return (digest_text, substantive_msg_count) from a transcript JSONL."""
    entries = []
    substantive = 0
    try:
        f = open(transcript_path, errors="replace")
    except OSError:
        return "", 0
    with f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message") or {}
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", "")
            texts, tools = [], []
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text":
                        texts.append(c.get("text", ""))
                    elif c.get("type") == "tool_use":
                        tools.append(format_tool_use(c))
            else:
                texts.append(str(content))
            text = " ".join(t for t in texts if t).strip()
            if "<local-command" in text or "<system-reminder" in text:
                text = ""
            if len(text) > SUBSTANTIVE_TEXT_CHARS:
                substantive += 1
            if len(text) >= 10:
                entries.append(f"{role.upper()}: {text[:2000]}")
            entries.extend(tools)
    return elide(entries), substantive


def elide(entries):
    """Join entries; over budget keeps head 1/3 + tail 2/3, elides the middle."""
    total = sum(len(e) + 2 for e in entries)
    if total <= DIGEST_BUDGET_CHARS:
        return "\n\n".join(entries)
    head_budget = DIGEST_BUDGET_CHARS // 3
    tail_budget = DIGEST_BUDGET_CHARS - head_budget
    head, used = [], 0
    for e in entries:
        if used + len(e) + 2 > head_budget:
            break
        head.append(e)
        used += len(e) + 2
    tail, used = [], 0
    for e in reversed(entries[len(head):]):
        if used + len(e) + 2 > tail_budget:
            break
        tail.append(e)
        used += len(e) + 2
    tail.reverse()
    n_elided = len(entries) - len(head) - len(tail)
    middle = [f"[... {n_elided} items elided ...]"] if n_elided > 0 else []
    return "\n\n".join(head + middle + tail)


# ── codex rollout extraction ─────────────────────────────────────────────────

CODEX_SESSIONS = "~/.codex/sessions"
CODEX_ROLLOUT_MAX_AGE_SECS = 1800
TEXT_SKIP_MARKERS = ("<local-command", "<system-reminder",
                     "<user_instructions", "<environment_context")


def codex_session_meta(path):
    """Return session_meta payload from a rollout file (first few lines)."""
    try:
        with open(path, errors="replace") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "session_meta":
                    return obj.get("payload") or {}
    except OSError:
        pass
    return {}


def find_codex_rollout(cwd):
    """Newest recent main-thread rollout, preferring one whose cwd matches."""
    import glob as _glob
    pattern = os.path.join(os.path.expanduser(CODEX_SESSIONS),
                           "*", "*", "*", "rollout-*.jsonl")
    now = time.time()
    files = [(os.path.getmtime(p), p) for p in _glob.glob(pattern)]
    files = [(m, p) for m, p in files if now - m < CODEX_ROLLOUT_MAX_AGE_SECS]
    fallback = None
    for _, path in sorted(files, reverse=True):
        meta = codex_session_meta(path)
        source = meta.get("source")
        if isinstance(source, dict) and "subagent" in source:
            continue
        if cwd and meta.get("cwd") == cwd:
            return path, meta
        if fallback is None:
            fallback = (path, meta)
    return fallback or (None, {})


def extract_codex_digest(rollout_path):
    """Return (digest_text, substantive_msg_count) from a Codex rollout JSONL."""
    entries = []
    substantive = 0
    try:
        f = open(rollout_path, errors="replace")
    except OSError:
        return "", 0
    with f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "response_item":
                continue
            p = obj.get("payload") or {}
            ptype = p.get("type")
            if ptype == "message":
                role = str(p.get("role", ""))
                if role not in ("user", "assistant"):
                    continue
                texts = [c.get("text", "") for c in (p.get("content") or [])
                         if isinstance(c, dict)
                         and c.get("type") in ("input_text", "output_text")]
                text = " ".join(t for t in texts if t).strip()
                if any(m in text for m in TEXT_SKIP_MARKERS):
                    continue
                if len(text) > SUBSTANTIVE_TEXT_CHARS:
                    substantive += 1
                if len(text) >= 10:
                    entries.append(f"{role.upper()}: {text[:2000]}")
            elif ptype == "custom_tool_call":
                name = p.get("name", "?")
                entries.append(f"TOOL[{name}]: {str(p.get('input', ''))[:300]}")
            elif ptype == "function_call":
                name = p.get("name", "?")
                entries.append(f"TOOL[{name}]: {str(p.get('arguments', ''))[:200]}")
    return elide(entries), substantive


# ── frontmatter & index ──────────────────────────────────────────────────────

def render_frontmatter(meta):
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def parse_frontmatter(path):
    meta = {}
    try:
        with open(path) as f:
            if f.readline().strip() != "---":
                return meta
            for line in f:
                if line.strip() == "---":
                    break
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip()
                if v.startswith("[") and v.endswith("]"):
                    meta[k.strip()] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                else:
                    meta[k.strip()] = v
    except OSError:
        pass
    return meta


def parse_tags(body):
    m = re.search(r"^##\s*Tags\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    if not m:
        return []
    return re.findall(r"#([A-Za-z0-9][\w-]*)", m.group(1))[:8]


def extract_title(body):
    m = re.search(r"^#\s+(.+)$", body, re.M)
    if m:
        return m.group(1).strip()
    first = body.strip().splitlines()[0] if body.strip() else "Session Journal"
    return re.sub(r"^#+\s*", "", first).strip() or "Session Journal"


def regenerate_index(project_dir):
    rows = []
    try:
        names = sorted(os.listdir(project_dir), reverse=True)
    except OSError:
        return
    for name in names:
        if not name.endswith(".md") or name == "INDEX.md":
            continue
        meta = parse_frontmatter(os.path.join(project_dir, name))
        date = str(meta.get("date", ""))[:16].replace("T", " ")
        title = meta.get("title") or name
        tags = " ".join(f"#{t}" for t in meta.get("tags", []) if t and "/" not in t)
        rows.append(f"- {date} — [{title}]({name})" + (f" — {tags}" if tags else ""))
    with open(os.path.join(project_dir, "INDEX.md"), "w") as f:
        f.write(f"# Journal Index — {os.path.basename(project_dir)}\n\n")
        f.write("\n".join(rows) + "\n")


HOME_MD = """# § Journal

## Recent entries
```dataview
TABLE WITHOUT ID file.link AS Entry, project AS Project, dateformat(date(date), "yyyy-MM-dd HH:mm") AS Written, source AS Source
WHERE project
SORT date DESC
LIMIT 20
```

## Open action items
```dataview
TASK
WHERE !completed AND contains(file.tags, "#project")
GROUP BY file.link
```

## Entries per project
```dataview
TABLE WITHOUT ID project AS Project, length(rows) AS Entries
WHERE project
GROUP BY project
SORT length(rows) DESC
```

> Requires the **Dataview** community plugin. Without it this page shows raw queries; everything else works.
"""


def ensure_home(root):
    """Create the Obsidian Dataview dashboard once; never overwrite user edits."""
    path = os.path.join(root, "HOME.md")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(HOME_MD)


# ── git ──────────────────────────────────────────────────────────────────────

def git_commit(root, message):
    def run(*cmd):
        return subprocess.run(
            ["git", "-C", root, *cmd], capture_output=True, text=True, timeout=60
        )
    try:
        if not os.path.isdir(os.path.join(root, ".git")):
            run("init")
        run("add", "-A")
        res = run("commit", "-m", message)
        out = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0 and "nothing to commit" not in out:
            log_line(f"git commit failed: {out.strip()[:200]}")
            return
        git_push(root, run)
    except (OSError, subprocess.TimeoutExpired) as e:
        log_line(f"git unavailable: {e}")


def git_push(root, run):
    """Push to the first configured remote, if any. Failures only logged."""
    try:
        remote = run("remote").stdout.split()
        if not remote:
            return
        res = run("push", remote[0], "HEAD", "--quiet")
        if res.returncode != 0:
            log_line(f"git push failed: {(res.stderr or res.stdout).strip()[:200]}")
    except (OSError, subprocess.TimeoutExpired) as e:
        log_line(f"git push error: {e}")


# ── generation ───────────────────────────────────────────────────────────────

def run_claude(prompt):
    try:
        res = subprocess.run(
            ["claude", "-p", "--system-prompt", SYSTEM_PROMPT,
             "--model", MODEL, "--output-format", "text", prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECS,
        )
        if res.returncode != 0:
            log_line(f"claude -p failed rc={res.returncode}: {res.stderr.strip()[:300]}")
            return ""
        return res.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log_line(f"claude -p error: {e}")
        return ""


def run_codex(prompt):
    """Generate via `codex exec` on Codex-only machines. Codex has no
    --system-prompt flag, so the system prompt is prepended; the final agent
    message lands in --output-last-message (stdout carries event logs)."""
    out = None
    try:
        fd, out = tempfile.mkstemp(prefix="journal-codex-", suffix=".md")
        os.close(fd)
        res = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
             "--output-last-message", out, SYSTEM_PROMPT + "\n\n" + prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECS,
        )
        if res.returncode != 0:
            log_line(f"codex exec failed rc={res.returncode}: {res.stderr.strip()[:300]}")
            return ""
        with open(out) as f:
            return f.read().strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log_line(f"codex exec error: {e}")
        return ""
    finally:
        if out:
            try:
                os.unlink(out)
            except OSError:
                pass


def run_llm(prompt):
    """Try claude -p first; fall back to codex exec when claude is missing or
    returns nothing. Returns (body, model_label) — model_label goes into the
    entry frontmatter so entries record which CLI wrote them."""
    if shutil.which("claude"):
        body = run_claude(prompt)
        if body:
            return body, MODEL
    if shutil.which("codex"):
        body = run_codex(prompt)
        if body:
            return body, "codex-exec"
    return "", MODEL


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_hook(source):
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        log_line(f"skip source={source} reason=bad-hook-json")
        return 0
    if not isinstance(data, dict):
        data = {}

    cwd = data.get("cwd") or os.getcwd()
    project = project_slug(cwd)
    session_id = data.get("session_id") or ""
    root = journal_root()

    if is_duplicate(root, project, int(time.time())):
        log_line(f"skip project={project} source={source} reason=recent-journal")
        return 0

    transcript = data.get("transcript_path") or ""
    digest, substantive = "", 0
    if transcript and os.path.isfile(transcript):
        digest, substantive = extract_digest(transcript)

    if digest and substantive < MIN_SUBSTANTIVE_MSGS:
        log_line(f"skip project={project} source={source} reason=trivial msgs={substantive}")
        return 0

    if not digest and source == "compact":
        # transcript gone after compaction — fall back to the compact summary
        digest = data.get("summary") or ""

    if not digest:
        log_line(f"skip project={project} source={source} reason=no-content")
        return 0

    spawn_writer(root, project, session_id, source, digest)
    return 0


def spawn_writer(root, project, session_id, source, digest):
    fd, tmp = tempfile.mkstemp(prefix="journal-digest-", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(digest)

    os.makedirs(root, exist_ok=True)
    logf = open(os.path.join(root, ".journal.log"), "a")
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "write",
         "--digest-file", tmp, "--project", project,
         "--session-id", session_id, "--source", source],
        stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
        start_new_session=True,
    )
    log_line(f"spawned writer project={project} source={source} chars={len(digest)}")


def cmd_hook_codex(payload_arg):
    """Codex notify adapter. Codex passes the notification JSON as an argv
    argument, not stdin; the payload has no transcript path, so we locate the
    newest main-thread rollout ourselves."""
    data = {}
    if payload_arg:
        try:
            data = json.loads(payload_arg)
        except ValueError:
            pass
    if not isinstance(data, dict):
        data = {}
    ntype = data.get("type", "")
    if ntype and ntype != "agent-turn-complete":
        return 0

    cwd = data.get("cwd") or os.getcwd()
    rollout, meta = find_codex_rollout(cwd)
    if not rollout:
        log_line("skip source=codex reason=no-recent-rollout")
        return 0

    project = project_slug(meta.get("cwd") or cwd)
    root = journal_root()
    if is_duplicate(root, project, int(time.time())):
        log_line(f"skip project={project} source=codex reason=recent-journal")
        return 0

    digest, substantive = extract_codex_digest(rollout)
    if not digest:
        log_line(f"skip project={project} source=codex reason=no-content")
        return 0
    if substantive < MIN_SUBSTANTIVE_MSGS:
        log_line(f"skip project={project} source=codex reason=trivial msgs={substantive}")
        return 0

    session_id = meta.get("id") or meta.get("session_id") or ""
    spawn_writer(root, project, session_id, "codex", digest)
    return 0


def cmd_write(args):
    root = journal_root()
    project_dir = os.path.join(root, args.project)
    os.makedirs(project_dir, exist_ok=True)

    try:
        with open(args.digest_file) as f:
            digest = f.read()
    except OSError as e:
        log_line(f"writer failed: digest file unreadable: {e}")
        return 1
    try:
        os.unlink(args.digest_file)
    except OSError:
        pass

    now = datetime.datetime.now().astimezone()
    body, model = run_llm(PROMPT_TEMPLATE.format(
        date=now.strftime("%Y-%m-%d %H:%M"), digest=digest))
    if not body:
        body = (
            f"# Session Journal — {now.strftime('%Y-%m-%d %H:%M')}\n\n"
            "_Journal generation failed; raw session digest below._\n\n"
            "```\n" + digest[:FALLBACK_EXCERPT_CHARS] + "\n```\n"
        )

    title = extract_title(body)
    # nested tags (project/…, source/…) render as a tag tree in Obsidian
    tags = [f"project/{args.project}", f"source/{args.source}"] + parse_tags(body)
    meta = {
        "title": title,
        "project": args.project,
        "date": now.isoformat(timespec="seconds"),
        "session_id": args.session_id or "unknown",
        "source": args.source,
        "model": model,
        "tags": tags,
    }
    base = f"{now.strftime('%Y-%m-%d_%H-%M')}_{slugify(title)}"
    entry_path = unique_path(project_dir, base)
    footer = f"\n\n---\n**Project:** [[{args.project}/INDEX|{args.project}]]\n"
    with open(entry_path, "w") as f:
        f.write(render_frontmatter(meta) + body + footer)
    ensure_home(root)

    stamp_marker(root, args.project, args.session_id)
    regenerate_index(project_dir)
    git_commit(root, f"journal: {args.project} — {title}")
    log_line(f"ok wrote {entry_path} source={args.source}")
    return 0


def cmd_digest(days, project):
    root = journal_root()
    cutoff = datetime.datetime.now().astimezone() - datetime.timedelta(days=days)
    chunks = []
    try:
        projects = [project] if project else sorted(
            d for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d))
            and d not in (".git", "digests") and not d.startswith(".")
        )
    except OSError:
        projects = []
    for proj in projects:
        pdir = os.path.join(root, proj)
        for name in sorted(os.listdir(pdir)):
            if not name.endswith(".md") or name == "INDEX.md":
                continue
            path = os.path.join(pdir, name)
            meta = parse_frontmatter(path)
            try:
                entry_date = datetime.datetime.fromisoformat(str(meta.get("date", "")))
            except ValueError:
                continue
            if entry_date < cutoff:
                continue
            with open(path, errors="replace") as f:
                text = f.read()
            text = re.sub(r"\A---.*?---\s*", "", text, flags=re.S)
            chunks.append(f"### {proj}/{name}\n{text[:4000]}")
    if not chunks:
        print("no entries in window")
        return 0

    combined = "\n\n".join(chunks)[:DIGEST_BUDGET_CHARS]
    now = datetime.datetime.now().astimezone()
    prompt = (
        "Write a weekly digest in markdown from these journal entries. "
        "Sections: # Weekly Digest <date range>, ## Highlights, ## Per Project, "
        "## Open Action Items, ## Themes. Output only the markdown.\n\n"
        f"ENTRIES:\n{combined}"
    )
    body, _ = run_llm(prompt)
    if not body:
        print("digest generation failed (see .journal.log)")
        return 1
    ddir = os.path.join(root, "digests")
    os.makedirs(ddir, exist_ok=True)
    out = os.path.join(ddir, f"{now.strftime('%Y-W%W')}.md")
    with open(out, "w") as f:
        f.write(body + "\n")
    git_commit(root, f"journal: weekly digest {now.strftime('%Y-W%W')}")
    print(out)
    return 0


def cmd_check():
    root = journal_root()
    project = project_slug(os.getcwd())
    if is_duplicate(root, project, int(time.time())):
        print(f"SKIP: recent journal exists for {project}")
    else:
        print(f"PROCEED: {os.path.join(root, project)}")
    return 0


def cmd_finalize():
    root = journal_root()
    project = project_slug(os.getcwd())
    stamp_marker(root, project)
    project_dir = os.path.join(root, project)
    if os.path.isdir(project_dir):
        regenerate_index(project_dir)
    git_commit(root, f"journal: {project} — manual entry")
    print(f"finalized {project_dir}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="journal.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hook = sub.add_parser("hook")
    p_hook.add_argument("source", choices=["stop", "compact", "codex"])
    p_hook.add_argument("payload", nargs="?", default="")

    p_write = sub.add_parser("write")
    p_write.add_argument("--digest-file", required=True)
    p_write.add_argument("--project", required=True)
    p_write.add_argument("--session-id", default="")
    p_write.add_argument("--source", default="stop")

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--days", type=int, default=7)
    p_digest.add_argument("--project", default="")

    sub.add_parser("resolve-dir")
    sub.add_parser("check")
    sub.add_parser("finalize")

    args = parser.parse_args()
    if args.cmd == "hook":
        if args.source == "codex":
            return cmd_hook_codex(args.payload)
        return cmd_hook(args.source)
    if args.cmd == "write":
        return cmd_write(args)
    if args.cmd == "digest":
        return cmd_digest(args.days, args.project or None)
    if args.cmd == "resolve-dir":
        print(journal_root())
        return 0
    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "finalize":
        return cmd_finalize()
    return 1


if __name__ == "__main__":
    sys.exit(main())
