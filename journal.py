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
import contextlib
import secrets
import stat
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
# Runs on the hook path — a wedged git must never stall the session.
GIT_TIMEOUT_SECS = 5

SYSTEM_PROMPT = (
    "You are a journal writer. Your only job is to produce clean markdown "
    "journal entries. Never use tools, never ask questions, never ask for "
    "permissions. Just output the markdown text."
)

PROMPT_TEMPLATE = """Analyze this session log and write a short markdown journal entry. \
The log contains USER/ASSISTANT messages and TOOL[...] lines showing commands run and files edited. \
Output ONLY the markdown, starting directly with the # title.

Write it for a developer who wasn't there and has never seen this project. They should \
finish it understanding what changed and why, not holding an inventory of what moved.

VOICE — caveman. Short words, broken grammar, no fluff. Drop articles (a/an/the) where \
it still reads. Drop filler (just, really, basically, actually, simply) and hedging. \
Fragments fine. "Rename surface two stale-state bug" not "The rename surfaced two \
stale-state bugs". Technical terms stay exact — names, flags, error strings, numbers are \
never reworded. Code blocks stay verbatim. Terse, not vague: every fact survives, only \
the grammar goes.

Hard rules:
- Prose, not bullet soup. The story section is paragraphs.
- No table of files created/modified. Git already records that, exactly and forever.
- Name a file only when the reader genuinely needs it to follow the point.
- Skip any section with nothing real to say. A missing section beats a padded one. \
The one exception is `## Tags` — always end with it, since the tags feed search.
- Aim for under 400 words before the tag line. Cut anything a reader would skim.
- Never echo the metadata block below into the entry. The date is recorded separately; \
a `Date:` line in the body is duplication.
- Explain the reasoning, not the transcript. "Chose X because Y proved wrong" is \
worth keeping; "then I ran the tests" is not.

Shape:

# <specific title naming what actually happened, not "Session Journal">

**In one line:** <one sentence a reader could repeat to someone else>

## The story
<1-3 paragraphs: what prompted this, what turned out true, where it landed. Lead with \
whatever was surprising.>

## Why we chose what we chose
<Each decision plus the reasoning or trade-off behind it. Skip decisions that had no \
alternative worth naming.>

## Gotchas for whoever comes next
<Traps, surprises, things that cost time. Most valuable section — this is what a reader \
cannot get from the diff.>

## Commands worth remembering
<Fenced code block, commands verbatim. Only commands worth running again: repro steps, \
verification, one-liners that were hard to get right. Not the full shell history, and \
not routine edits or file listings.>

## Left undone
<Open threads with enough context to pick up cold. Omit if nothing open.>

Example of the voice:

# Route allowlist guarded paths that never existed

**In one line:** Rename job turn up HTTP boundary exempting routes service never \
register — fail-open. Fixed by booting real service and enumerating.

## The story
Start as plain rename. Rename surface two stale-state bug. Old `.egg-info` from earlier \
build leave dead entry point still visible to `importlib.metadata`, so two plugins load \
at once. Worse, credential middleware allowlist was written from reading source, not from \
observed routes. Source say 7 routes. Real service register 9.

## Tags
`#tag1` `#tag2` `#tag3`
<Required. 3-6 tags: technology, task type, key concepts.>

--- METADATA (context only, never copy into the entry) ---
Session date: {date}

--- SESSION LOG ---
{digest}"""

REDACT_PROMPT = """Rewrite this journal entry so it is safe to publish on a public \
personal website. Output ONLY the rewritten markdown, same structure, same headings.

Remove or generalize anything that identifies an employer, client, or internal system:
- Company and product names -> a neutral description ("the wrapper service", "an \
internal proxy")
- Internal repo, package, service, host, and namespace names -> neutral descriptions
- Internal URLs, hostnames, IPs, ticket IDs, employee names, email addresses
- Internal file paths that carry a company or product name
- Credentials, tokens, and keys of any kind

Keep everything that makes the entry worth reading: the reasoning, the trade-offs, the \
gotchas, the general technology names (Python, Docker, Kubernetes, pytest, git), and \
the shape of any commands. If a command contains an internal name, replace just that \
name with a placeholder rather than dropping the command.

Keep the entry's clipped caveman voice exactly as written — you are removing identifying \
detail, not rewriting the prose. Do not add a note about redaction. Do not shorten the \
entry beyond what removal requires.

ENTRY:
{body}"""


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


def repo_root_name(cwd):
    """Repository directory name for cwd, or None outside a repo.

    Uses the *common* git dir so every worktree of a repo answers with the repo
    name. Conductor names each workspace after its branch, so basename-of-cwd
    would file one repo's sessions under a new project per task."""
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None

    common = res.stdout.strip()
    if not common:
        return None
    # …/imtf-adrs/.git → imtf-adrs; a bare …/imtf-adrs.git → imtf-adrs
    root = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    name = os.path.basename(root.rstrip("/"))
    if name.endswith(".git"):
        name = name[:-len(".git")]
    return name or None


def project_slug(cwd):
    base = repo_root_name(cwd) or os.path.basename((cwd or "").rstrip("/"))
    return slugify(safe_text(base), 40) if base else "misc"


@contextlib.contextmanager
def output_parent(root, path):
    """Hold parent dir handles. Refuse links at output boundary."""
    root = os.path.abspath(root)
    relative = os.path.relpath(os.path.abspath(path), root)
    parts = relative.split(os.sep)
    if relative == "." or ".." in parts or os.path.islink(root):
        raise ValueError("Output path blocked.")
    os.makedirs(root, exist_ok=True)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        try:
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Output path blocked.")
        except FileNotFoundError:
            pass
        yield fd, parts[-1]
    finally:
        os.close(fd)


def save_text(root, path, text, exclusive=False):
    """Save through held dir. New entries use exclusive create."""
    with output_parent(root, path) as (fd, name):
        temp = name if exclusive else ".journal-" + secrets.token_hex(12)
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            if not exclusive:
                os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            if not exclusive:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass


def unique_path(directory, base):
    path = os.path.join(directory, base + ".md")
    n = 2
    while os.path.lexists(path):
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
    save_text(root, marker_path(root, project), f"{int(time.time())} {session_id}\n")


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


def find_codex_rollout(cwd, session_id=""):
    """Newest recent main-thread rollout, preferring one whose cwd matches."""
    import glob as _glob
    pattern = os.path.join(os.path.expanduser(CODEX_SESSIONS),
                           "*", "*", "*", "rollout-*.jsonl")
    now = time.time()
    files = [(os.path.getmtime(p), p) for p in _glob.glob(pattern)]
    files = [(m, p) for m, p in files if now - m < CODEX_ROLLOUT_MAX_AGE_SECS]
    if not session_id or not cwd:
        return None, {}
    for _, path in sorted(files, reverse=True):
        meta = codex_session_meta(path)
        source = meta.get("source")
        if isinstance(source, dict) and "subagent" in source:
            continue
        if (meta.get("cwd") == cwd
                and (meta.get("id") or meta.get("session_id")) == session_id):
            return path, meta
    return None, {}


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
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
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
                try:
                    meta[k.strip()] = json.loads(v)
                except ValueError:
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
    save_text(os.path.dirname(project_dir), os.path.join(project_dir, "INDEX.md"),
              f"# Journal Index: {os.path.basename(project_dir)}\n\n" + "\n".join(rows) + "\n")


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
    with output_parent(root, path):
        if not os.path.exists(path):
            save_text(root, path, HOME_MD, exclusive=True)
            return True
    return False


# ── git ──────────────────────────────────────────────────────────────────────

def git_commit(root, message, paths=None):
    def run(*cmd):
        return subprocess.run(
            ["git", "-C", root, *cmd], capture_output=True, text=True, timeout=60
        )
    try:
        if not os.path.isdir(os.path.join(root, ".git")):
            run("init")
        if not paths:
            log_line("sync blocked: owned paths missing")
            return False
        base = os.path.realpath(root)
        snapshots = []
        try:
            if safe_text(message) != message:
                raise ValueError("Unsafe message.")
            for path in paths:
                full = os.path.join(base, path)
                if (os.path.isabs(path) or path.startswith("-")
                        or os.path.commonpath([base, os.path.realpath(full)]) != base
                        or not os.path.isfile(full) or os.path.islink(full)
                        or safe_text(path) != path):
                    raise ValueError("Unsafe path.")
                with open(full, encoding="utf-8") as f:
                    text = f.read()
                if safe_text(text) != text:
                    raise ValueError("Unsafe content.")
                snapshots.append((path, text))
        except (OSError, ValueError, UnicodeError):
            log_line("sync blocked: privacy scan failed")
            return False
        index_result = run("rev-parse", "--git-path", "index")
        if index_result.returncode:
            return False
        index = os.path.abspath(os.path.join(root, index_result.stdout.strip()))
        lock = index + ".lock"
        with os.fdopen(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600), "wb") as index_lock:
            try:
                staged = run("diff", "--cached", "--name-only", "-z")
                if staged.returncode or staged.stdout:
                    log_line("sync blocked: staged data exists")
                    return False
                head = run("rev-parse", "HEAD")
                if head.returncode:
                    return False
                old = head.stdout.strip()
                with tempfile.TemporaryDirectory(prefix="journal-index-") as tmp:
                    private_index = os.path.join(tmp, "index")
                    env = {**os.environ, "GIT_INDEX_FILE": private_index,
                           "GIT_NO_REPLACE_OBJECTS": "1", "GIT_AUTHOR_NAME": "Journal Recorder",
                           "GIT_AUTHOR_EMAIL": "recorder@localhost",
                           "GIT_COMMITTER_NAME": "Journal Recorder",
                           "GIT_COMMITTER_EMAIL": "recorder@localhost"}
                    def snapshot_git(*cmd, data=None):
                        result = subprocess.run(["git", "-C", root, *cmd], input=data,
                                                env=env, capture_output=True, text=True, timeout=60)
                        if result.returncode:
                            raise ValueError("Snapshot commit blocked.")
                        return result.stdout.strip()
                    snapshot_git("read-tree", old)
                    for path, text in snapshots:
                        oid = snapshot_git("hash-object", "-w", "--stdin", data=text)
                        snapshot_git("update-index", "--add", "--cacheinfo", "100644", oid, path)
                    tree = snapshot_git("write-tree")
                    if tree != snapshot_git("rev-parse", old + "^{tree}"):
                        new = snapshot_git("commit-tree", tree, "-p", old, data=message + "\n")
                        snapshot_git("update-ref", "HEAD", new, old)
                    with open(private_index, "rb") as saved:
                        shutil.copyfileobj(saved, index_lock)
                    index_lock.flush()
                    os.replace(lock, index)
            finally:
                if os.path.exists(lock):
                    os.unlink(lock)
        return git_push(root, run)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        log_line("sync blocked: Git snapshot or lock failed")
        return False


def git_push(root, run):
    """Scan new objects against fetched origin branch before push."""
    def checked(*args):
        result = run("--no-replace-objects", *args)
        if result.returncode:
            raise ValueError("Git check failed.")
        return result.stdout.strip()

    try:
        fetch_urls = checked("remote", "get-url", "--all", "origin").splitlines()
        push_urls = checked("remote", "get-url", "--push", "--all", "origin").splitlines()
        if len(fetch_urls) != 1 or push_urls != fetch_urls:
            raise ValueError("Git destinations differ.")
        branch = checked("symbolic-ref", "--short", "HEAD")
        checked("check-ref-format", "--branch", branch)
        checked("fetch", "--no-tags", "origin", f"refs/heads/{branch}")
        base = checked("rev-parse", "FETCH_HEAD")
        head = checked("rev-parse", "HEAD")
        checked("merge-base", "--is-ancestor", base, head)
        for commit in checked("rev-list", head, f"^{base}").splitlines():
            names = checked("ls-tree", "-rz", "--name-only", commit)
            if safe_text(names) != names:
                raise ValueError("Unsafe tree paths.")
        objects = checked("rev-list", "--objects", head, f"^{base}")
        for row in objects.splitlines():
            oid, _, name = row.partition(" ")
            if safe_text(name) != name:
                raise ValueError("Unsafe path.")
            kind = checked("cat-file", "-t", oid)
            if kind in ("blob", "commit"):
                text = checked("cat-file", kind, oid)
                if safe_text(text) != text:
                    raise ValueError("Unsafe outgoing content.")
        checked("push", "--no-follow-tags", "origin", f"{head}:refs/heads/{branch}")
        return True
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        log_line("push blocked: history scan or Git check failed")
        return False


# ── generation ───────────────────────────────────────────────────────────────

def run_claude(prompt):
    try:
        with tempfile.TemporaryDirectory(prefix="journal-model-") as cwd:
            res = subprocess.run(
                ["claude", "-p", "--system-prompt", SYSTEM_PROMPT,
                 "--model", MODEL, "--output-format", "text", "--tools", "",
                 "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                 "--disable-slash-commands", "--no-session-persistence",
                 "--setting-sources", "", "--settings", '{"disableAllHooks":true}'],
                input=prompt, cwd=cwd, capture_output=True, text=True,
                timeout=CLAUDE_TIMEOUT_SECS,
            )
        if res.returncode != 0:
            log_line(f"claude failed rc={res.returncode}")
            return ""
        return res.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log_line("claude failed: launch or timeout")
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
            log_line(f"codex failed rc={res.returncode}")
            return ""
        with open(out) as f:
            return f.read().strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log_line("codex failed: launch or timeout")
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
    prompt = safe_text(prompt)
    if shutil.which("claude"):
        body = run_claude(prompt)
        if body:
            return safe_text(body), MODEL
    if os.environ.get("JOURNAL_ALLOW_CODEX") == "1" and shutil.which("codex"):
        body = run_codex(prompt)
        if body:
            return safe_text(body), "codex-exec"
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
    digest = safe_text(digest)
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
    logf.close()
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
    rollout, meta = find_codex_rollout(cwd, data.get("thread-id") or data.get("thread_id") or "")
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


def cmd_hook_text(source):
    """Native hooks supply final text. No transcript guess needed."""
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return 0
    if source == "cursor":
        if data.get("hook_event_name") != "afterAgentResponse":
            return 0
        roots = data.get("workspace_roots")
        if not isinstance(roots, list) or len(roots) != 1:
            return 0
        cwd, session = roots[0], data.get("conversation_id")
        text = data.get("text")
    else:
        if data.get("hook_event_name") != "AfterAgent" or data.get("stop_hook_active"):
            return 0
        cwd, session = data.get("cwd"), data.get("session_id")
        text = data.get("prompt_response")
        if isinstance(text, str) and isinstance(data.get("prompt"), str):
            text = data["prompt"] + "\n\n" + text
    if not isinstance(cwd, str) or not isinstance(session, str) or not isinstance(text, str) or not text.strip():
        return 0
    root = journal_root()
    project = project_slug(cwd)
    if not is_duplicate(root, project, int(time.time())):
        spawn_writer(root, project, session, source, safe_text(text))
    return 0


def cmd_record():
    """Any agent sends summary JSON on stdin. Core owns saved files."""
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        raise ValueError("Summary JSON needed.")
    agent = slugify(safe_text(data.get("agent", "agent"))) or "agent"
    args = argparse.Namespace(project=project_slug(data.get("cwd") or os.getcwd()),
                              session_id=str(data.get("session_id", "")),
                              source=agent, summary=data["summary"], agent=agent)
    return cmd_write(args)


def cmd_write(args):
    args = argparse.Namespace(**{
        **vars(args),
        "project": slugify(safe_text(args.project)) or "project",
        "source": slugify(safe_text(args.source)) or "agent",
        "session_id": safe_text(args.session_id).replace("\n", " "),
    })
    root = journal_root()
    project_dir = os.path.join(root, args.project)
    for path in (os.path.join(project_dir, "INDEX.md"),
                 marker_path(root, args.project), os.path.join(root, "HOME.md")):
        with output_parent(root, path):
            pass

    now = datetime.datetime.now().astimezone()
    if hasattr(args, "summary"):
        body, model = safe_text(args.summary), "agent-summary"
    else:
        try:
            with open(args.digest_file) as f:
                digest = f.read()
        except OSError:
            log_line("writer failed: digest unreadable")
            return 1
        finally:
            try:
                os.unlink(args.digest_file)
            except OSError:
                pass
        body, model = run_llm(PROMPT_TEMPLATE.format(
            date=now.strftime("%Y-%m-%d %H:%M"), digest=digest))
    if not body or not body.strip():
        log_line("writer skip: model failed")
        return 1

    body = safe_text(body)
    title = extract_title(body)
    # nested tags (project/…, source/…) render as a tag tree in Obsidian
    tags = [f"project/{args.project}", f"source/{args.source}"] + parse_tags(body)
    meta = {
        "title": title,
        "project": args.project,
        "date": now.isoformat(timespec="seconds"),
        "session_id": args.session_id or "unknown",
        "source": args.source,
        "agent": safe_text(getattr(args, "agent", args.source)),
        "model": model,
        "tags": tags,
    }
    base = f"{now.strftime('%Y-%m-%d_%H-%M')}_{slugify(title)}"
    entry_path = unique_path(project_dir, base)
    footer = f"\n\n---\n**Project:** [[{args.project}/INDEX|{args.project}]]\n"
    save_text(root, entry_path, render_frontmatter(meta) + body + footer, exclusive=True)
    created_home = ensure_home(root)

    stamp_marker(root, args.project, args.session_id)
    regenerate_index(project_dir)
    paths = [os.path.relpath(entry_path, root), os.path.join(args.project, "INDEX.md")]
    if created_home:
        paths.append("HOME.md")
    git_commit(root, f"journal: {args.project}: {title}", paths)
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
    body, _ = run_llm(safe_text(prompt))
    if not body or not body.strip():
        print("digest generation failed (see .journal.log)")
        return 1
    ddir = os.path.join(root, "digests")
    out = os.path.join(ddir, f"{now.strftime('%Y-W%W')}.md")
    save_text(root, out, safe_text(body) + "\n")
    git_commit(root, f"journal: weekly digest {now.strftime('%Y-W%W')}",
               [os.path.relpath(out, root)])
    print(out)
    return 0


def site_root():
    cfg = os.path.expanduser("~/.claude/.journal-site")
    try:
        with open(cfg) as f:
            raw = f.read().strip()
        if raw:
            return os.path.expanduser(raw)
    except OSError:
        pass
    return None


def strip_entry_body(path):
    """Entry body without our frontmatter and the Obsidian project footer."""
    with open(path, errors="replace") as f:
        text = f.read()
    text = re.sub(r"\A---\n.*?\n---\n\s*", "", text, flags=re.S)
    text = re.sub(r"\n---\n\*\*Project:\*\* \[\[.*?\]\]\s*\Z", "\n", text, flags=re.S)
    return text.strip() + "\n"


def extract_excerpt(body):
    m = re.search(r"^\*\*In one line:\*\*\s*(.+?)(?=\n\s*\n|\n##|\Z)", body, re.M | re.S)
    if not m:  # entries written before the narrative template led with TL;DR
        m = re.search(r"^##\s*TL;?DR\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    text = (m.group(1) if m else body).strip()
    for para in text.split("\n\n"):
        para = " ".join(para.split())
        if para and not para.startswith("#"):
            return para[:200].replace('"', "'")
    return ""


def latest_entry(root, project=None):
    candidates = []
    dirs = [os.path.join(root, project)] if project else [
        os.path.join(root, d) for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d))
        and d not in (".git", "digests") and not d.startswith(".")
    ]
    for pdir in dirs:
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for name in names:
            if name.endswith(".md") and name not in ("INDEX.md", "HOME.md"):
                p = os.path.join(pdir, name)
                candidates.append((os.path.getmtime(p), p))
    return max(candidates)[1] if candidates else None


REDACT_CONFIG = "~/.claude/.journal-redact"

# Always-on. Credential shapes and personal identifiers that must never ship,
# regardless of what the user's denylist says.
BUILTIN_REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "<private-key>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "<token>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "<token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "<token>"),
    (re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+@"), "<credential>@"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "<email>"),
    (re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*"), "<credential>"),
    (re.compile(r'''(?ix)\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|aws[_-]?secret[_-]?access[_-]?key|secret|token)["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)'''), "<credential>"),
]


def safe_text(text):
    """Scrub text, then block if replacement leaves known secret."""
    rules, _ = redact_rules()
    clean, _ = redact(str(text), rules)
    if any(rx.search(clean) for rx, _ in rules):
        raise ValueError("Privacy scan blocked text.")
    return clean


def redact_rules():
    """Load the publish denylist. One rule per line:

        internal-service-name => the internal service
        acme-corp
        re:JIRA-\\d+ => <ticket>

    Bare patterns become `<redacted>`. A `re:` prefix makes the pattern a regex;
    anything else is matched literally. Matching is case-insensitive.

    Returns (rules, denylist_exists) — the caller warns when it does not, since
    without one only the built-in credential patterns apply.
    """
    rules = list(BUILTIN_REDACTIONS)
    try:
        with open(os.path.expanduser(REDACT_CONFIG)) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return rules, False
    except OSError:
        raise ValueError("Privacy policy unreadable.") from None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, replacement = line.partition("=>")
        pattern, replacement = pattern.strip(), replacement.strip() or "<redacted>"
        if not pattern:
            continue
        if pattern.startswith("re:"):
            try:
                rules.append((re.compile(pattern[3:].strip(), re.I), replacement))
            except re.error:
                raise ValueError("Privacy rule invalid.") from None
        else:
            rules.append((re.compile(re.escape(pattern), re.I), replacement))
    return rules, True


def redact(text, rules):
    """Apply rules to text. Returns (text, [(pattern, replacement, count)])."""
    hits = []
    for rx, replacement in rules:
        text, n = rx.subn(replacement, text)
        if n:
            hits.append((rx.pattern, replacement, n))
    return text, hits


def cmd_publish(entry, project, site):
    site = site or site_root()
    if not site or not os.path.isdir(os.path.join(site, "journal")):
        print("no site configured — echo '<path-to-site-repo>' > ~/.claude/.journal-site")
        return 1
    root = journal_root()
    path = entry or latest_entry(root, project or None)
    if not path or not os.path.isfile(path):
        print("no entry found to publish")
        return 1

    meta = parse_frontmatter(path)
    body = strip_entry_body(path)
    date = str(meta.get("date", ""))[:10] or datetime.date.today().isoformat()
    try:
        if datetime.date.fromisoformat(date).isoformat() != date:
            raise ValueError("Bad date.")
    except ValueError:
        print("Publish blocked: date invalid.")
        return 1

    # Two-layer scrub. The LLM pass generalizes prose a pattern list cannot see
    # ("we renamed the wrapper" vs a specific package name); the rule pass is the
    # actual guarantee and runs last, so the LLM cannot reintroduce a banned term.
    rules, has_denylist = redact_rules()
    if not has_denylist:
        print("Publish blocked: local privacy policy missing.")
        return 1
    generic, _ = run_llm(REDACT_PROMPT.format(body=safe_text(body)))
    if not generic or not generic.strip():
        log_line("publish blocked: model failed")
        return 1
    body = safe_text(generic)
    body, hits = redact(body, rules)
    for pattern, replacement, n in hits:
        print(f"redacted {n}x  {pattern} -> {replacement}")

    # Derived after redaction — the stored title and tags carry the same leaks.
    title = extract_title(body)
    tags = [t for t in meta.get("tags", [])
            if t and "/" not in t and redact(t, rules)[0] == t]
    excerpt = extract_excerpt(body)

    out_name = f"{date}-{slugify(title)}.md"
    out_path = os.path.join(site, "journal", out_name)
    with output_parent(site, os.path.join(site, "journal", "index.js")):
        pass
    save_text(site, out_path, render_frontmatter({"title": title, "date": date,
              "tags": tags, "excerpt": excerpt}) + body)

    # regenerate index.js — filenames sort newest-first by date prefix
    posts = sorted(
        (n for n in os.listdir(os.path.join(site, "journal"))
         if n.endswith(".md")), reverse=True)
    save_text(site, os.path.join(site, "journal", "index.js"),
              "window.JOURNAL_FILES = " + json.dumps(["journal/" + n for n in posts]) + ";\n")

    if not git_commit(site, f"journal: publish {title}",
                      [os.path.join("journal", out_name), "journal/index.js"]):
        print("publish sync blocked. Check local policy and Git state.")
        return 1
    print(f"published: {out_path}")
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
    print("Direct finalize blocked. Send summary JSON to record.")
    return 1


def main():
    parser = argparse.ArgumentParser(prog="journal.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hook = sub.add_parser("hook")
    p_hook.add_argument("source", choices=["stop", "compact", "codex", "cursor", "gemini"])
    p_hook.add_argument("payload", nargs="?", default="")

    p_write = sub.add_parser("write")
    p_write.add_argument("--digest-file", required=True)
    p_write.add_argument("--project", required=True)
    p_write.add_argument("--session-id", default="")
    p_write.add_argument("--source", default="stop")

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--days", type=int, default=7)
    p_digest.add_argument("--project", default="")

    p_pub = sub.add_parser("publish")
    p_pub.add_argument("entry", nargs="?", default="")
    p_pub.add_argument("--project", default="")
    p_pub.add_argument("--site", default="")

    sub.add_parser("record")
    sub.add_parser("resolve-dir")
    sub.add_parser("check")
    sub.add_parser("finalize")

    args = parser.parse_args()
    if args.cmd == "hook":
        if args.source in ("cursor", "gemini"):
            return cmd_hook_text(args.source)
        if args.source == "codex":
            return cmd_hook_codex(args.payload)
        return cmd_hook(args.source)
    if args.cmd == "record":
        return cmd_record()
    if args.cmd == "write":
        return cmd_write(args)
    if args.cmd == "digest":
        return cmd_digest(args.days, args.project or None)
    if args.cmd == "resolve-dir":
        print(journal_root())
        return 0
    if args.cmd == "publish":
        return cmd_publish(args.entry or None, args.project or None, args.site or None)
    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "finalize":
        return cmd_finalize()
    return 1


if __name__ == "__main__":
    sys.exit(main())
