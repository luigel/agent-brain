"""`brain`: CLI for the Agent's Brain vault (~/brain), shared by all of the user's coding agents.

  brain query "<question>" [N] [--all | --project NAME]
                                              graph traversal, N-token budget (default 1500); scoped to the
                                              project for the current folder unless --all/--project is given
  brain find <words...>                       notes anywhere in the vault containing all the words
  brain project [dir]                         print the project hub path for a folder (exit 1 if none)
  brain init-project "<Name>" <repo-dir>...   create Projects/<Name>/ with a hub note mapped to those folders
  brain rebuild [--if-stale]                  rebuild the whole-vault graph and every project graph (no LLM),
                                              then commit + push note changes in the background
  brain sync                                  commit local note changes, pull --rebase, push

  brain context [dir] [--json]                session-start hook: context for a folder (hooks pass {"cwd":...}
                                              on stdin; --json wraps it as hookSpecificOutput.additionalContext)
  brain stop-check                            Stop hook: once per session, after real work, asks the agent to
                                              record learnings before finishing

  brain setup [--vault DIR] [--vault-repo URL] [--agents claude,codex] [--claude-dir DIR ...]
              [--adopt SKILL ...] [--third-party] [--no-universal] [--dry-run]
                                              wire this machine: the vault (created or cloned), the ~/brain
                                              link, skills, hooks and instructions
  brain doctor                                check the vault, graphify, graphs, skills and agent wiring
  brain skills                                status of agent-brain's and your kit's skills everywhere
  brain skill import <dir> [--name N]         add a skill folder to your kit (<vault>/_meta/skills) and
                                              install it on this machine
  brain version
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VAULT = Path.home() / "brain"
OUT_ROOT = Path.home() / ".graphify" / "brain"
MAX_CONTEXT = 8000  # SessionStart output is capped at 10k chars
TYPE_DIRS = ("Decisions", "Gotchas", "Patterns", "Preferences", "References")
# graphify drops files with these words in the name as possible key dumps
BANNED_NAME = re.compile(r"secret|password|passwd|token|credential|service.?account", re.I)
# Each dev's own kit lives in the vault and syncs with it; it isn't notes, so recall skips it.
KIT_SKILLS = Path("_meta") / "skills"
KIT_MANIFEST = Path("_meta") / "third-party.json"


def root():
    return VAULT.resolve()


def graphify_bin():
    # graphify is a dependency, so it sits next to this interpreter in the uv tool venv
    bundled = Path(sys.executable).parent / "graphify"
    if bundled.exists():
        return str(bundled)
    return shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def notes(base=None):
    base = base or root()
    for p in base.rglob("*.md"):
        rel = p.relative_to(root())
        if any(part.startswith(".") for part in rel.parts) or rel.parts[:2] == KIT_SKILLS.parts:
            continue
        yield p, rel


def frontmatter(text):
    """Minimal YAML frontmatter reader: scalars, inline lists, block lists."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    data, key = {}, None
    for line in m.group(1).splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(item.group(1).strip().strip("\"'"))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        elif val:
            data[key] = val.strip("\"'")
        else:
            data[key] = []
    return data, text[m.end():]


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def summary_line(body):
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "**Why", "**How", "Related:", "```", "|", "---")):
            s = re.sub(r"\s+", " ", s)
            return s[:180] + ("…" if len(s) > 180 else "")
    return ""


# ── projects ──────────────────────────────────────────────────────────────────

def projects():
    """Yield (name, folder, hub) for every Projects/<Name>/<Name>.md."""
    base = root() / "Projects"
    if not base.is_dir():
        return
    for d in sorted(base.iterdir()):
        hub = d / f"{d.name}.md"
        if d.is_dir() and hub.is_file():
            yield d.name, d, hub


def project_for(cwd):
    cwd = os.path.realpath(os.path.expanduser(cwd))
    best, best_len = None, -1
    for name, folder, hub in projects():
        paths = frontmatter(read(hub))[0].get("paths", [])
        for raw in paths if isinstance(paths, list) else [paths]:
            r = os.path.realpath(os.path.expanduser(raw))
            if (cwd == r or cwd.startswith(r + os.sep)) and len(r) > best_len:
                best, best_len = (name, folder, hub), len(r)
    return best


def find_project(name):
    for p in projects():
        if p[0].lower() == name.lower() or slug(p[0]) == slug(name):
            return p
    return None


# ── graphs ────────────────────────────────────────────────────────────────────

def scopes():
    yield "all", root(), OUT_ROOT / "all"
    for name, folder, _ in projects():
        yield name, folder, OUT_ROOT / "projects" / slug(name)


def newest_mtime(base):
    # directory mtimes catch deletions and renames, not just edits
    newest = base.stat().st_mtime
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        newest = max(newest, os.stat(dirpath).st_mtime)
        for f in filenames:
            if f.endswith(".md"):
                newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime)
    return newest


def build(src, out):
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GRAPHIFY_OUT=str(out))
    try:
        r = subprocess.run([graphify_bin(), "update", str(src), "--force"],
                           env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, r.stderr or r.stdout
    line = next((l for l in r.stdout.splitlines() if "Rebuilt:" in l), "rebuilt")
    return True, line.replace("[graphify watch] Rebuilt: ", "")


def rebuild(if_stale=False):
    ok = True
    for name, src, out in scopes():
        graph = out / "graph.json"
        if if_stale and graph.exists() and graph.stat().st_mtime >= newest_mtime(src):
            continue
        good, msg = build(src, out)
        ok &= good
        if not good:
            print(f"brain: rebuild of {name} failed: {msg}", file=sys.stderr)
        elif not if_stale:
            print(f"brain: {name}: {msg}")
    # drop graphs of projects that no longer exist
    live = {slug(n) for n, _, _ in projects()}
    for d in (OUT_ROOT / "projects").glob("*") if (OUT_ROOT / "projects").is_dir() else []:
        if d.is_dir() and d.name not in live:
            shutil.rmtree(d)
    return ok


def query(args):
    question = args[0]
    budget = next((a for a in args[1:] if a.isdigit()), "1500")
    rebuild(if_stale=True)
    if "--all" in args:
        proj = None
    elif "--project" in args:
        i = args.index("--project")
        proj = find_project(args[i + 1]) if i + 1 < len(args) else None
        if not proj:
            print("brain: no such project; known: " + ", ".join(n for n, _, _ in projects()))
            return 1
    else:
        proj = project_for(os.getcwd())
    if proj:
        graph = OUT_ROOT / "projects" / slug(proj[0]) / "graph.json"
        print(f"Scope: project {proj[0]} (pass --all to search the whole vault). "
              f"src= paths are relative to ~/brain/Projects/{proj[0]}/")
    else:
        graph = OUT_ROOT / "all" / "graph.json"
        print("Scope: whole vault. src= paths are relative to ~/brain/")
    r = subprocess.run([graphify_bin(), "query", question, "--graph", str(graph), "--budget", budget],
                       capture_output=True, text=True)
    print(r.stdout or r.stderr)
    return 0


def find(words):
    words = [w.lower() for w in words]
    for p, rel in sorted(notes(), key=lambda x: str(x[1])):
        if all(w in read(p).lower() or w in str(rel).lower() for w in words):
            print(VAULT / rel)


def init_project(name, dirs):
    if BANNED_NAME.search(name):
        print("brain: project name contains a word graphify skips; pick another", file=sys.stderr)
        return 1
    folder = root() / "Projects" / name
    hub = folder / f"{name}.md"
    if hub.exists():
        print(f"brain: {VAULT / hub.relative_to(root())} already exists", file=sys.stderr)
        return 1
    home = str(Path.home())
    paths = [os.path.realpath(os.path.expanduser(d)).replace(home, "~", 1) for d in dirs]
    today = datetime.date.today().isoformat()
    folder.mkdir(parents=True)
    hub.write_text(
        "---\n"
        "type: project\n"
        f"paths: [{', '.join(paths)}]\n"
        "aliases: []\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "status: active\n"
        "---\n"
        f"# {name}\n\n"
        "What this project is, in a sentence or two.\n\n"
        "## How to run things\n\n"
        "## Notes\n",
        encoding="utf-8",
    )
    print(VAULT / hub.relative_to(root()))
    rebuild(if_stale=True)
    spawn_sync()
    return 0


# ── git sync ──────────────────────────────────────────────────────────────────
# The vault is a git repo: pull at session start, commit + push after writes. Failures (offline,
# conflicts, a concurrent sync holding the index lock) never block an agent; they are logged and
# retried on the next sync.

SYNC_LOG = Path.home() / ".cache" / "agent-brain" / "sync.log"


def git(*args, timeout=20, cwd=None):
    """Run git in the vault (or `cwd`); None if git couldn't run or timed out."""
    try:
        return subprocess.run(["git", "-C", str(cwd or root()), *args], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def ok(r):
    return bool(r and r.returncode == 0)


def is_repo(vault=None):
    if vault is not None:
        return (Path(vault) / ".git").exists()
    return VAULT.exists() and (root() / ".git").exists()


def has_remote(vault=None):
    r = git("remote", cwd=vault)
    return bool(ok(r) and r.stdout.strip())


def ensure_upstream(vault=None):
    """True when the branch tracks a remote branch that exists. Adopts origin/<branch> if it's there but not
    tracked yet. False means nothing was ever pushed: there's nothing to pull, and the next push sets it up."""
    if ok(git("rev-parse", "--verify", "-q", "@{u}", cwd=vault)):
        return True
    branch = git("symbolic-ref", "--short", "-q", "HEAD", cwd=vault)
    if not ok(branch) or not branch.stdout.strip():
        return False
    name = branch.stdout.strip()
    if not ok(git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}", cwd=vault)):
        return False
    return ok(git("branch", "-q", "--set-upstream-to", f"origin/{name}", cwd=vault))


def machine_name():
    if sys.platform == "darwin":  # nodename can be an IP on macOS; LocalHostName is the readable one
        try:
            r = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return os.uname().nodename


def dirty_files():
    r = git("status", "--porcelain", "--untracked-files=all")
    if not r or r.returncode != 0:
        return []
    return [line[3:].strip().strip('"') for line in r.stdout.splitlines() if line.strip()]


def commit():
    changed = dirty_files()
    if not changed:
        return False
    host = machine_name()
    names = [Path(c.split(" -> ")[-1]).stem for c in changed]  # renames read "old -> new"
    msg = f"Update {len(changed)} note{'s' if len(changed) != 1 else ''} from {host}: " + ", ".join(names[:5]) \
        + (", …" if len(names) > 5 else "")
    git("add", "-A")
    r = git("commit", "-q", "-m", msg)
    return bool(r and r.returncode == 0)


def pull(timeout=20, vault=None):
    """Return None on success (or nothing to do), else a short warning."""
    if not is_repo(vault) or not has_remote(vault):
        return None
    if not ok(git("fetch", "-q", "origin", timeout=timeout, cwd=vault)):
        return "couldn't reach the vault's git remote (offline?); using the local notes"
    if not ensure_upstream(vault):
        return None
    if not ok(git("rebase", "--autostash", "-q", "@{u}", cwd=vault)):
        git("rebase", "--abort", cwd=vault)
        return "pulling the vault failed, probably a merge conflict; run `brain sync` and resolve it"
    return None


def push(timeout=20):
    if not is_repo() or not has_remote():
        return None
    if not ok(git("push", "-q", "-u", "origin", "HEAD", timeout=timeout)):  # -u: the first push sets tracking
        return "pushing the vault failed; the next sync retries"
    return None


def sync(quiet=False):
    if not is_repo():
        if not quiet:
            print("brain: ~/brain is not a git repo; nothing to sync")
        return 0
    committed = commit()
    warnings = [w for w in (pull(),) if w]
    if not warnings:
        warnings += [w for w in (push(),) if w]
    if quiet:
        if warnings:
            SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SYNC_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {'; '.join(warnings)}\n")
    else:
        print("brain: " + ("; ".join(warnings) if warnings else
                           ("committed and synced" if committed else "in sync")))
    return 1 if warnings else 0


def spawn_sync():
    """Commit + push in the background so agents never wait on the network."""
    if not is_repo() or not dirty_files():
        return
    try:
        subprocess.Popen([sys.executable, "-m", "agent_brain", "sync", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


# ── session context ───────────────────────────────────────────────────────────

def preference_lines(folder):
    lines = []
    if not folder.is_dir():
        return lines
    for p in sorted(folder.glob("*.md")):
        meta, body = frontmatter(read(p))
        if meta.get("status", "active") == "active":
            lines.append(f"- [[{p.stem}]] — {summary_line(body)}")
    return lines


def context(args):
    hook = {}
    if not sys.stdin.isatty():  # hooks pipe JSON in; a manual run must not block on stdin
        try:
            hook = json.load(sys.stdin)
        except (ValueError, OSError):
            pass
    positional = [a for a in args if not a.startswith("--")]
    cwd = (positional[0] if positional else None) or hook.get("cwd") \
        or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if not VAULT.exists():
        return
    pulled = pull(timeout=8)  # pick up notes other machines pushed; short timeout keeps startup fast
    rebuild(if_stale=True)

    out = [
        "Agent's Brain (the user's Obsidian vault at ~/brain) is your long-term memory, shared by all of "
        "the user's coding agents, and replaces any built-in memory. Each project has its own area "
        "(~/brain/Projects/<Name>/) and graph; cross-project knowledge lives in ~/brain/Global/. Use the "
        "`brain` command (`brain query`, `brain find`, `brain init-project`, `brain rebuild`) and the rules "
        "in ~/brain/_meta/Conventions.md. The vault is a git repo; writes are committed automatically, "
        "and pushed when it has a remote. Facts below were true when written; verify file/flag names "
        "before relying on them.",
    ]
    if pulled:
        out.append(f"\nVault sync: {pulled}.")

    proj = project_for(cwd)
    if proj:
        name, folder, hub = proj
        _, body = frontmatter(read(hub))
        out.append(f"\n## Project: {name} (hub ~/brain/{hub.relative_to(root())})\n{body.strip()}")
        prefs = preference_lines(folder / "Preferences")
        if prefs:
            out.append(f"\n## {name} preferences\n" + "\n".join(prefs))
    else:
        out.append(f"\nNo project area matches {cwd}. If this is a real project, create one with "
                   "`brain init-project \"<Name>\" <repo-dir>` once something worth keeping comes up.")

    prefs = preference_lines(root() / "Global" / "Preferences")
    if prefs:
        out.append("\n## Global preferences\n" + "\n".join(prefs))

    text = "\n".join(out)
    if len(text) > MAX_CONTEXT:
        text = text[:MAX_CONTEXT] + "\n… (truncated; open the hub note for the rest)"
    if "--json" in args:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": text}}))
    else:
        print(text)


# ── end-of-reply reminder ─────────────────────────────────────────────────────

STATE = Path.home() / ".cache" / "agent-brain" / "stop-reminded"
WORK_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
MIN_TOOL_CALLS = 8  # below this a session is a quick question, not real work
STOP_REASON = (
    "Before you finish: check whether this session produced anything worth keeping in Agent's Brain "
    "(~/brain). That means a correction or preference from the user, a decision and its reason, a gotcha "
    "that cost time, a reusable recipe, an external reference, or a project fact that isn't in the repo. "
    "If something qualifies, record it now following the brain skill: the right project area or Global/, "
    "update rather than duplicate, brain rebuild. Then end with the one-line 'Saved to brain: …' "
    "summary. If nothing qualifies, end your turn without mentioning the brain."
)


def tool_calls(transcript):
    """Yield (name, input) for every tool call in a JSONL transcript."""
    try:
        f = open(transcript, encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        yield block.get("name", ""), block.get("input") or {}


def touches_brain(name, inp):
    vault = str(root())
    if name in WORK_TOOLS:
        path = os.path.realpath(os.path.expanduser(str(inp.get("file_path", ""))))
        return path.startswith(vault + os.sep)
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        return bool(re.search(r"\bbrain(\.py)?\s+(rebuild|init-project)\b", cmd)) or "/brain/" in cmd and ">" in cmd
    return False


def stop_check():
    """Stop hook: once per session, after real work, ask the agent to record learnings."""
    try:
        hook = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    session = re.sub(r"[^\w-]", "", str(hook.get("session_id", "")))
    if not VAULT.exists():
        return 0
    spawn_sync()  # push whatever this reply wrote, even if the agent forgot `brain rebuild`
    if hook.get("stop_hook_active") or not session:
        return 0
    marker = STATE / session
    if marker.exists():
        return 0

    calls = list(tool_calls(hook.get("transcript_path", "")))
    recorded = any(touches_brain(n, i) for n, i in calls)  # already wrote to the brain this session
    real_work = any(n in WORK_TOOLS for n, _ in calls) or len(calls) >= MIN_TOOL_CALLS
    if not real_work and not recorded:
        return 0  # nothing yet; check again after the next reply

    STATE.mkdir(parents=True, exist_ok=True)
    marker.touch()
    for old in STATE.iterdir():  # markers only matter for live sessions
        if old.stat().st_mtime < marker.stat().st_mtime - 14 * 86400:
            old.unlink(missing_ok=True)
    if not recorded:
        print(json.dumps({"decision": "block", "reason": STOP_REASON}))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 1
    cmd, args = argv[0], argv[1:]
    if cmd in ("setup", "doctor", "skills", "skill", "version"):
        from . import install  # imported lazily: hooks run on every session and never need it
        return install.main(cmd, args)
    if cmd == "rebuild":
        ok = rebuild(if_stale="--if-stale" in args)
        spawn_sync()  # rebuild is the "I just wrote notes" step, so publish them
        return 0 if ok else 1
    if cmd == "sync":
        return sync(quiet="--quiet" in args)
    if cmd == "query" and args:
        return query(args)
    if cmd == "find" and args:
        find(args)
        return 0
    if cmd == "project":
        proj = project_for(args[0] if args else os.getcwd())
        if not proj:
            return 1
        print(VAULT / proj[2].relative_to(root()))
        return 0
    if cmd == "init-project" and len(args) >= 2:
        return init_project(args[0], args[1:])
    if cmd == "context":
        context(args)
        return 0
    if cmd == "stop-check":
        return stop_check()
    print(__doc__)
    return 1


def entry():
    sys.exit(main())
