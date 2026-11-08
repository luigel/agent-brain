"""`brain setup`, `doctor`, `skills`, `skill import`, `version`: wire a machine to the Agent's Brain.

Every step is idempotent: re-running setup after an upgrade refreshes skills and hooks in place.
Config files are backed up (`<name>.bak-agent-brain-<timestamp>`) before their first change in a run;
replaced skill folders that setup didn't own go to ~/.cache/agent-brain/backups/<timestamp>/.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from importlib import metadata, resources
from pathlib import Path

from . import bootstrap, core
from .bootstrap import BACKUPS, STAMP

LINK = Path.home() / "brain"
MARK_START = "<!-- agent-brain:start -->"
MARK_END = "<!-- agent-brain:end -->"
# Matches our hook commands, including the pre-package `.../scripts/brain.py" context` form.
OUR_HOOK = re.compile(r'brain(\.py)?"?\s+(context|stop-check)\b')
# ~/.agents/skills is the user-level skills folder for Codex, Cursor, Gemini CLI and other agents
UNIVERSAL = Path.home() / ".agents" / "skills"
CODEX_SKILLS = Path.home() / ".codex" / "skills"  # older Codex location; a skill here shadows ours
RECORD = ".agent-brain-managed.json"  # names of the skills setup installed into a folder


class Run:
    def __init__(self, dry):
        self.dry = dry
        self.backed_up = set()

    def say(self, msg):
        print(("would " if self.dry else "") + msg)

    def write(self, path, text, backup=True, quiet=False):
        path = Path(path)
        if path.exists() and path.read_text(encoding="utf-8") == text:
            if not quiet:
                print(f"unchanged {path}")
            return
        self.say(f"write {path}")
        if self.dry:
            return
        if backup and path.exists() and path not in self.backed_up:
            shutil.copy2(path, path.with_name(f"{path.name}.bak-agent-brain-{STAMP}"))
            self.backed_up.add(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def data(name):
    return (resources.files("agent_brain") / "data" / name).read_text(encoding="utf-8")


def brain_exe():
    # hooks run with a minimal PATH, so they get an absolute path; ~/.local/bin/brain survives upgrades
    found = shutil.which("brain")
    return found or str(Path.home() / ".local" / "bin" / "brain")


def hook_command(sub):
    return f'"{brain_exe()}" {sub} 2>/dev/null || true'


# ── pieces ────────────────────────────────────────────────────────────────────

def link_vault(run, vault):
    target = Path(os.path.expanduser(vault)).resolve()
    if not target.is_dir():
        if run.dry:  # a dry run that would have cloned it first
            run.say(f"link {LINK} -> {target}")
            return
        raise SystemExit(f"brain setup: vault folder not found: {target}")
    if LINK.is_symlink():
        if LINK.resolve() == target:
            print(f"unchanged {LINK} -> {target}")
        else:
            run.say(f"repoint {LINK} -> {target}")
            if not run.dry:
                LINK.unlink()
                LINK.symlink_to(target)
    elif LINK.exists():
        raise SystemExit(f"brain setup: {LINK} exists and is not a symlink; move it aside first")
    else:
        run.say(f"link {LINK} -> {target}")
        if not run.dry:
            LINK.symlink_to(target)


def merge_hook(settings, event, command, timeout, matcher=None):
    """Replace our hook for `event`, keeping every other hook untouched."""
    entries = settings.setdefault("hooks", {}).setdefault(event, [])
    kept, extras = [], {}
    for entry in entries:
        hooks = []
        for h in entry.get("hooks", []):
            if OUR_HOOK.search(str(h.get("command", ""))):
                extras.update({k: v for k, v in h.items() if k not in ("type", "command", "timeout")})
            else:
                hooks.append(h)
        if hooks:
            kept.append({**entry, "hooks": hooks})
    ours = {"hooks": [{"type": "command", "command": command, **extras, "timeout": timeout}]}
    if matcher:
        ours = {"matcher": matcher, **ours}
    kept.append(ours)
    settings["hooks"][event] = kept


def upsert_block(text, block):
    """Put `block` between our markers; adopts a hand-written '# Agent's Brain' section."""
    wrapped = f"{MARK_START}\n{block.strip()}\n{MARK_END}"
    if MARK_START in text and MARK_END in text:
        return re.sub(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), lambda _: wrapped, text,
                      count=1, flags=re.S)
    m = re.search(r"^# Agent's Brain.*?(?=^# |\Z)", text, flags=re.S | re.M)
    if m:
        return text[:m.start()] + wrapped + "\n\n" + text[m.end():].lstrip("\n")
    return text.rstrip("\n") + ("\n\n" if text.strip() else "") + wrapped + "\n"


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"brain setup: {path} is not valid JSON ({e}); fix it first")


# ── skills ────────────────────────────────────────────────────────────────────

def skill_dirs(base):
    base = Path(base)
    return {d.name: d for d in sorted(base.iterdir()) if (d / "SKILL.md").is_file()} if base.is_dir() else {}


def bundled_skills():
    return skill_dirs(resources.files("agent_brain") / "skills")


def skill_sources(vault, warn=False):
    """Bundled skills plus the dev's kit in <vault>/_meta/skills, and whether that kit folder was there.

    A missing kit folder (no vault yet, not synced yet) means "unknown", never "empty": callers must not
    remove installed kit skills on that basis.
    """
    skills = bundled_skills()
    kit_dir = Path(vault) / core.KIT_SKILLS if vault else None
    kit_known = bool(kit_dir and kit_dir.is_dir())
    for name, src in (skill_dirs(kit_dir) if kit_known else {}).items():
        if name in skills:
            if warn:
                print(f"skip kit skill {name}: agent-brain ships its own {name}")
            continue
        skills[name] = src
    return skills, kit_known


def digest(folder):
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file() and p.name != ".DS_Store":
            h.update(str(p.relative_to(folder)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def read_record(target):
    try:
        return set(json.loads((target / RECORD).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def skill_status(target, name, src, managed, shadow_dirs=(), synced_root=None):
    """missing | current | outdated | conflict | synced | shadowed:<path>"""
    if synced_root and any(Path(synced_root).glob(f"*/{name}/SKILL.md")):
        return "synced"  # claude.ai already provides a skill with this name in this profile
    for sd in shadow_dirs:
        if (sd / name).exists() and name not in read_record(sd):
            return f"shadowed:{sd / name}"
    dest = target / name
    if not dest.exists() and not dest.is_symlink():
        return "missing"
    legacy = (dest / "SKILL.md").is_file() and "Managed by agent-brain" in (dest / "SKILL.md").read_text(
        encoding="utf-8", errors="replace")
    if name in managed or legacy:
        return "current" if not dest.is_symlink() and digest(dest) == digest(src) else "outdated"
    return "conflict"


def install_skills(run, target, skills, kit_known, adopt=(), shadow_dirs=(), synced_root=None):
    target = Path(target)
    print(f"-- skills -> {target}")
    record = read_record(target)
    managed = set()
    for name, src in skills.items():
        st = skill_status(target, name, src, record, shadow_dirs, synced_root)
        dest = target / name
        if st == "synced":
            print(f"skip {name}: your claude.ai account already syncs a skill with this name here; "
                  "turn it off on claude.ai to use the repo's copy")
            continue
        if st.startswith("shadowed:"):
            print(f"skip {name}: {st[9:]} would duplicate it for Codex; remove that copy to use the repo's")
            continue
        if st == "conflict" and name not in adopt:
            print(f"skip {name}: {dest} exists and wasn't installed by agent-brain; "
                  f"re-run with --adopt {name} to replace it (the old copy is backed up)")
            continue
        managed.add(name)
        if st == "current":
            print(f"unchanged skill {name}")
            continue
        run.say(f"{'replace' if st != 'missing' else 'install'} skill {name} -> {dest}")
        if run.dry:
            continue
        if dest.is_symlink():
            dest.unlink()
        elif dest.exists():
            if st == "conflict":  # someone else's copy: keep it
                keep = BACKUPS / str(target).strip("/").replace("/", "_") / name
                keep.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(keep))
                print(f"  backed up the old copy to {keep}")
            else:
                shutil.rmtree(dest)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    if kit_known:  # without the kit folder we can't tell a dropped skill from one not synced yet
        for name in sorted(record - set(skills)):
            if (target / name).exists():
                run.say(f"remove skill {name} (no longer in agent-brain or your kit)")
                if not run.dry:
                    shutil.rmtree(target / name)
    else:  # keep them on the record so they stay ours once the kit shows up
        managed |= {n for n in record if (target / n).exists()}
    if managed or record:
        run.write(target / RECORD, json.dumps(sorted(managed), indent=2) + "\n", backup=False, quiet=True)


# ── third-party skills ────────────────────────────────────────────────────────

def read_manifest(vault):
    path = Path(vault) / core.KIT_MANIFEST if vault else None
    return read_json(path) if path and path.exists() else None


def third_party(run, vault):
    print("\n== Third-party skills (from their authors)")
    manifest = read_manifest(vault)
    if manifest is None:
        print(f"no third-party packs listed in your vault ({core.KIT_MANIFEST})")
        return
    for entry in manifest.get("skills_cli", []):
        missing = [s for s in entry["skills"] if not (UNIVERSAL / s).exists()]
        if not missing:
            print(f"unchanged {entry['source']} ({len(entry['skills'])} skills)")
            continue
        cmd = ["npx", "-y", "skills", "add", entry["source"], "-g", "-y"]
        for a in entry.get("agents", []):
            cmd += ["-a", a]
        for s in missing:
            cmd += ["-s", s]
        run.say(f"install {len(missing)} skills from {entry['source']} with the skills CLI")
        if run.dry:
            continue
        if not shutil.which("npx"):
            print("  skipped: npx not found (install Node.js, then re-run with --third-party)")
            continue
        subprocess.run(cmd, check=False)
    for entry in manifest.get("git", []):
        dest = Path(os.path.expanduser(entry["dest"]))
        if not dest.exists():
            run.say(f"clone {entry['repo']} -> {dest}")
            if not run.dry:
                subprocess.run(["git", "clone", "--depth", "1", entry["repo"], str(dest)], check=False)
        link = entry.get("link")
        if link:
            path = Path(os.path.expanduser(link["path"]))
            if not path.exists() and not path.is_symlink():
                run.say(f"link {path} -> {dest / link['target']}")
                if not run.dry:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(dest / link["target"])
            else:
                print(f"unchanged {entry['name']}")
    for entry in manifest.get("manual", []):
        print(f"manual: {entry['name']}: {entry['how']}")


def wire_claude(run, claude_dir, adopt, skills, kit_known):
    d = Path(os.path.expanduser(claude_dir))
    if not d.is_dir():
        raise SystemExit(f"brain setup: Claude config dir not found: {d}")
    print(f"\n== Claude Code: {d}")
    install_skills(run, d / "skills", skills, kit_known, adopt, synced_root=d / "skills" / "synced")
    settings_path = d / "settings.json"
    settings = read_json(settings_path)
    merge_hook(settings, "SessionStart", hook_command("context"), 30, "startup|resume|clear|compact")
    merge_hook(settings, "Stop", hook_command("stop-check"), 15)
    settings["autoMemoryEnabled"] = False
    run.write(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    md = d / "CLAUDE.md"
    run.write(md, upsert_block(md.read_text(encoding="utf-8") if md.exists() else "", data("pointer.md")))


def wire_codex(run, codex_dir):
    d = Path(os.path.expanduser(codex_dir))
    if not d.is_dir():
        raise SystemExit(f"brain setup: Codex config dir not found: {d}")
    print(f"\n== Codex: {d}  (skills come from {UNIVERSAL})")
    hooks_path = d / "hooks.json"
    hooks = read_json(hooks_path)
    merge_hook(hooks, "SessionStart", hook_command("context --json"), 30, "startup|resume|clear|compact|fork")
    run.write(hooks_path, json.dumps(hooks, indent=4, ensure_ascii=False) + "\n")
    md = d / "AGENTS.md"
    run.write(md, upsert_block(md.read_text(encoding="utf-8") if md.exists() else "", data("pointer.md")))
    vault = LINK.resolve() if LINK.exists() else "<vault>"
    print("manual: if Codex's sandbox blocks writes, add these as writable roots in config.toml: "
          f"{vault} and {core.OUT_ROOT}. If Codex has its own memory feature, decide whether to turn it off.")


# ── commands ──────────────────────────────────────────────────────────────────

def detect_agents(arg, claude_dirs, codex_dir="~/.codex"):
    """--agents if given; otherwise every agent whose config folder exists."""
    if arg:
        agents = {x.strip() for x in arg.split(",") if x.strip()}
        unknown = agents - {"claude", "codex"}
        if unknown:
            raise SystemExit(f"brain setup: unknown agent(s): {', '.join(sorted(unknown))}")
        return agents
    agents = set()
    if claude_dirs or (Path.home() / ".claude").exists():
        agents.add("claude")
    if Path(os.path.expanduser(codex_dir)).is_dir():
        agents.add("codex")
    if not agents:
        raise SystemExit("brain setup: found neither ~/.claude nor ~/.codex; "
                         "install Claude Code or Codex first, or pass --agents")
    return agents


def setup(args):
    p = argparse.ArgumentParser(prog="brain setup")
    p.add_argument("--vault", help="the vault folder (default: where ~/brain points, else ~/Documents/Agent Brain)")
    p.add_argument("--vault-repo", help="git URL of your private vault repo: cloned, or seeded if it's empty")
    p.add_argument("--agents", help="comma list: claude, codex (default: whichever of ~/.claude and ~/.codex exist)")
    p.add_argument("--claude-dir", action="append",
                   help="Claude config dir to wire; repeat for extra profiles (default: ~/.claude)")
    p.add_argument("--codex-dir", default="~/.codex")
    p.add_argument("--adopt", action="append", default=[], metavar="SKILL",
                   help="replace an existing copy of this skill that agent-brain didn't install (backed up)")
    p.add_argument("--no-universal", action="store_true",
                   help=f"don't install skills into {UNIVERSAL} (Codex, Cursor, Gemini CLI, ...)")
    p.add_argument("--third-party", action="store_true",
                   help="also reinstall the third-party skills listed in <vault>/_meta/third-party.json")
    p.add_argument("--dry-run", action="store_true", help="print what would change, change nothing")
    a = p.parse_args(args)

    vault = bootstrap.resolve_vault(a.vault)
    agents = detect_agents(a.agents, a.claude_dir, a.codex_dir)  # before anything changes on disk
    if not shutil.which("brain"):
        print("note: `brain` is not on PATH; hooks will use ~/.local/bin/brain. "
              "Install with `uv tool install` so that path exists.")

    run = Run(a.dry_run)
    bootstrap.prepare_vault(run, vault, a.vault_repo)
    link_vault(run, vault)
    skills, kit_known = skill_sources(vault if vault.is_dir() else None, warn=True)
    if "claude" in agents:
        seen = set()
        for cd in a.claude_dir or ["~/.claude"]:
            real = Path(os.path.expanduser(cd)).resolve()
            if real not in seen:  # ~/.claude is often a symlink to a named profile
                seen.add(real)
                wire_claude(run, cd, a.adopt, skills, kit_known)
    if not a.no_universal:
        print("\n== Shared skills folder (Codex, Cursor, Gemini CLI, ...)")
        install_skills(run, UNIVERSAL, skills, kit_known, a.adopt, shadow_dirs=[CODEX_SKILLS])
    if "codex" in agents:
        wire_codex(run, a.codex_dir)
    if a.third_party:
        third_party(run, vault)
    if not run.dry and LINK.exists():
        core.rebuild(if_stale=True)
    print("\ndone. Start a new agent session to load the hooks." if not run.dry else "\ndry run: nothing changed.")
    return 0


def check(ok, label, hint=""):
    print(f"{'✓' if ok else '✗'} {label}" + (f"  ({hint})" if hint and not ok else ""))
    return ok


def doctor(_args):
    print(f"agent-brain {version_string()}")
    good = check(LINK.is_symlink() and LINK.resolve().is_dir(), f"~/brain -> {LINK.resolve() if LINK.exists() else '?'}",
                 "run brain setup --vault <dir>")
    good &= check((LINK / "_meta" / "Conventions.md").exists(), "vault has _meta/Conventions.md",
                  "wrong vault folder?")
    if core.is_repo():
        remote = core.git("remote", "get-url", "origin")
        if remote and remote.returncode == 0:
            dirty = len(core.dirty_files())
            ahead = core.git("rev-list", "--count", "@{u}..HEAD")
            n_ahead = int(ahead.stdout.strip()) if ahead and ahead.returncode == 0 else -1
            check(True, f"vault git remote {remote.stdout.strip()}")
            check(dirty == 0 and n_ahead == 0, f"vault synced ({dirty} uncommitted, {max(n_ahead, 0)} unpushed)",
                  "run brain sync")
        else:
            print("  local only; add sync with: brain setup --vault-repo <url>")
        if core.SYNC_LOG.exists():
            last = core.SYNC_LOG.read_text(encoding="utf-8").strip().splitlines()[-1:]
            if last:
                print(f"  last background sync problem: {last[0]}")
    else:
        check(False, "vault is a git repo",
              "to sync it: git -C ~/brain init -b main && git -C ~/brain add -A && "
              "git -C ~/brain commit -m 'Start the vault', then brain setup --vault-repo <url>")
    gbin = core.graphify_bin()
    good &= check(Path(gbin).exists(), f"graphify at {gbin}", "reinstall: uv tool install --reinstall agent-brain")
    if good:
        good &= check(core.rebuild(if_stale=True), "graphs build",
                      "see the error above")
        projects = [n for n, _, _ in core.projects()]
        print(f"  projects: {', '.join(projects) or 'none'}")

    dirs = {d.resolve(): d for d in claude_profiles()}
    for real, d in dirs.items():
        settings = read_json(d / "settings.json")
        cmds = [h.get("command", "") for e in settings.get("hooks", {}).values() for x in e for h in x.get("hooks", [])]
        wired = all([
            (d / "skills" / "brain" / "SKILL.md").exists(),
            any(OUR_HOOK.search(c) and "context" in c for c in cmds),
            any(OUR_HOOK.search(c) and "stop-check" in c for c in cmds),
            settings.get("autoMemoryEnabled") is False,
        ])
        check(wired, f"Claude profile {d}" + (f" (-> {real})" if real != d else ""),
              f"brain setup --claude-dir {d}")
    codex = Path.home() / ".codex"
    if codex.is_dir():
        hooks = read_json(codex / "hooks.json")
        cmds = [h.get("command", "") for e in hooks.get("hooks", {}).values() for x in e for h in x.get("hooks", [])]
        has_skill = (UNIVERSAL / "brain" / "SKILL.md").exists() or (CODEX_SKILLS / "brain" / "SKILL.md").exists()
        check(has_skill and any(OUR_HOOK.search(c) for c in cmds), f"Codex {codex}", "brain setup --agents codex")

    problems = [(t, n, s) for t, n, s in skill_report(dirs.values()) if s not in ("current", "synced")]
    check(not problems, f"skills from agent-brain and your kit ({', '.join(skill_sources(vault_or_none())[0])})",
          "see `brain skills`")
    tp_missing = third_party_missing(vault_or_none())
    if tp_missing is not None:
        check(not tp_missing, "third-party skills installed",
              f"{len(tp_missing)} missing; brain setup --third-party")
    return 0 if good else 1


def skill_targets(claude_dirs):
    for d in claude_dirs:
        yield d / "skills", (), d / "skills" / "synced"
    if UNIVERSAL.parent.exists():
        yield UNIVERSAL, (CODEX_SKILLS,), None


def vault_or_none():
    return LINK.resolve() if LINK.is_symlink() and LINK.resolve().is_dir() else None


def skill_report(claude_dirs):
    for target, shadows, synced in skill_targets(claude_dirs):
        record = read_record(target)
        for name, src in skill_sources(vault_or_none())[0].items():
            yield target, name, skill_status(target, name, src, record, shadows, synced)


def third_party_missing(vault):
    """Names of listed packs that aren't installed; None when the vault lists none."""
    manifest = read_manifest(vault)
    if manifest is None:
        return None
    missing = [s for e in manifest.get("skills_cli", []) for s in e["skills"] if not (UNIVERSAL / s).exists()]
    missing += [e["name"] for e in manifest.get("git", []) if not Path(os.path.expanduser(e["dest"])).exists()]
    return missing


def claude_profiles():
    dirs = {}
    for d in [Path.home() / ".claude", *sorted(Path.home().glob(".claude-*"))]:
        if (d / "settings.json").exists() and "backup" not in d.name:
            dirs.setdefault(d.resolve(), d)
    return list(dirs.values())


def skills_cmd(_args):
    labels = {"current": "✓ installed", "outdated": "↻ outdated (brain setup)", "missing": "· not installed",
              "conflict": "! someone else's copy (brain setup --adopt NAME)", "synced": "= synced by claude.ai"}
    last = None
    for target, name, st in skill_report(claude_profiles()):
        if target != last:
            print(f"\n{target}")
            last = target
        label = labels.get(st) or f"! shadowed by {st[9:]}"
        print(f"  {name:<24} {label}")
    return 0


def skill_import(args):
    p = argparse.ArgumentParser(prog="brain skill import")
    p.add_argument("dir", help="an existing skill folder (with SKILL.md)")
    p.add_argument("--name", help="skill name in your kit (default: the folder name)")
    p.add_argument("--force", action="store_true", help="overwrite a kit skill with the same name")
    a = p.parse_args(args)
    src = Path(os.path.expanduser(a.dir)).resolve()
    if not (src / "SKILL.md").is_file():
        p.error(f"{src} has no SKILL.md")
    vault = vault_or_none()
    if not vault:
        raise SystemExit("brain skill import: no vault yet; run brain setup first")
    dest = vault / core.KIT_SKILLS / (a.name or src.name)
    if dest.name in bundled_skills():
        p.error(f"{dest.name} is agent-brain's own skill; pick another --name")
    if dest.exists() and not a.force:
        p.error(f"{dest.name} is already in your kit; pass --force to overwrite")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "node_modules", ".git"))
    count = sum(1 for f in dest.rglob("*") if f.is_file())
    print(f"added {dest} ({count} files)")
    run = Run(False)
    for target, shadows, synced in skill_targets(claude_profiles()):
        if (target / RECORD).exists():  # only folders `brain setup` already manages
            # just this skill, and never a removal: this machine's kit may not have synced yet
            install_skills(run, target, {dest.name: dest}, False, shadow_dirs=shadows, synced_root=synced)
    core.spawn_sync()
    print("it syncs with your vault; run `brain setup` on your other machines to install it there")
    return 0


def version_string():
    try:
        return metadata.version("agent-brain")
    except metadata.PackageNotFoundError:
        return "(not installed)"


def main(cmd, args):
    if cmd == "setup":
        return setup(args)
    if cmd == "doctor":
        return doctor(args)
    if cmd == "skills":
        return skills_cmd(args)
    if cmd == "skill":
        if args[:1] == ["import"]:
            return skill_import(args[1:])
        print("usage: brain skill import <dir> [--name NAME] [--force]")
        return 1
    print(version_string())
    return 0
