"""Where the vault lives, and getting it ready: the starter files, git, and the `--vault-repo` cases.

`brain setup` passes in its dry-run-aware `Run` (say/write); nothing here imports `install`.
"""
import datetime
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from . import core

LINK = Path.home() / "brain"
DEFAULT_VAULT = Path.home() / "Documents" / "Agent Brain"
STARTER_MESSAGE = "Start the vault from the agent-brain starter"
IGNORE_LINES = ("_meta/skills/", "_meta/third-party.json")  # the kit is not notes; keep it out of recall
STAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUPS = Path.home() / ".cache" / "agent-brain" / "backups" / STAMP


def resolve_vault(arg):
    """--vault, else where ~/brain points, else the default folder."""
    if arg:
        return Path(os.path.expanduser(arg))
    if LINK.is_symlink():
        target = LINK.resolve()
        if not target.is_dir():
            raise SystemExit(f"brain setup: ~/brain points to {target}, which doesn't exist; pass --vault <dir>")
        return target
    if LINK.exists():
        raise SystemExit(f"brain setup: {LINK} exists and is not a symlink; move it aside first")
    return DEFAULT_VAULT


def starter_files():
    """Relative path -> text of the starter vault. Package files named `dot-x` become `.x`."""
    out = {}

    def walk(node, prefix):
        for child in node.iterdir():
            if child.name in ("__pycache__", ".DS_Store"):
                continue
            name = "." + child.name[4:] if child.name.startswith("dot-") else child.name
            if child.is_dir():
                walk(child, f"{prefix}{name}/")
            else:
                out[prefix + name] = child.read_text(encoding="utf-8")

    walk(resources.files("agent_brain") / "data" / "vault", "")
    return out


def fill_starter(run, vault):
    """Write the starter files the vault lacks; never overwrite one it has."""
    vault = Path(vault)
    written = []
    for rel, text in sorted(starter_files().items()):
        path = vault / rel
        if rel == ".graphifyignore" and path.exists():
            current = path.read_text(encoding="utf-8")
            missing = [line for line in IGNORE_LINES if line not in current.splitlines()]
            if missing:
                sep = "\n" if current and not current.endswith("\n") else ""
                run.write(path, current + sep + "\n".join(missing) + "\n")
                written.append(rel)
            continue
        if not path.exists():
            run.write(path, text, backup=False)
            written.append(rel)
    for folder in ("Global", "Projects"):
        if not (vault / folder).is_dir():
            run.say(f"create {vault / folder}")
            if not run.dry:
                (vault / folder).mkdir(parents=True, exist_ok=True)
    return written


def vault_git(vault, *args, timeout=120):
    try:
        return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def ok(r):
    return bool(r and r.returncode == 0)


def is_empty(folder):
    return not folder.exists() or (folder.is_dir() and not any(folder.iterdir()))


def commit_all(vault, message):
    vault_git(vault, "add", "-A")
    if ok(vault_git(vault, "commit", "-q", "-m", message)):
        return True
    print("note: couldn't make the first commit (git has no user.name/user.email?); "
          "the next `brain sync` commits it")
    return False


def clone(run, repo, vault):
    run.say(f"clone {repo} -> {vault}")
    if run.dry:
        return
    vault.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "clone", "-q", repo, str(vault)], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise SystemExit(f"brain setup: git clone failed:\n{r.stderr.strip()}")


def same_url(a, b):
    def norm(url):
        return url.strip().rstrip("/").removesuffix(".git").rstrip("/")
    return norm(a) == norm(b)


def remote_is_empty(repo):
    """True for a repo with no commits yet. Runs before anything is created, so a typo changes nothing."""
    try:
        r = subprocess.run(["git", "ls-remote", repo], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SystemExit(f"brain setup: can't reach {repo}:\n{e}")
    if r.returncode != 0:
        raise SystemExit(f"brain setup: can't reach {repo}:\n{r.stderr.strip()}")
    return not r.stdout.strip()


def is_untouched_starter(vault):
    """Only the starter commit and nothing since: safe to swap for a clone."""
    count = vault_git(vault, "rev-list", "--count", "HEAD")
    subject = vault_git(vault, "log", "-1", "--format=%s")
    status = vault_git(vault, "status", "--porcelain")
    return (ok(count) and count.stdout.strip() == "1" and ok(subject)
            and subject.stdout.strip() == STARTER_MESSAGE and ok(status) and not status.stdout.strip())


def pull_first(run, vault):
    """Bring a synced vault up to date before topping it up, so a starter file written here can't block
    the pull of the same file from another machine."""
    if run.dry:
        return
    warning = core.pull(vault=vault)
    if warning:
        print(f"note: {warning}")


def push(vault):
    if not ok(vault_git(vault, "push", "-q", "-u", "origin", "HEAD")):
        print("note: pushing the vault failed; the next `brain sync` retries")


def clone_and_seed(run, repo, vault, empty_remote):
    """Clone; seed the starter (commit + push) when the remote is empty or isn't a brain yet."""
    clone(run, repo, vault)
    if run.dry:
        return
    if empty_remote:
        vault_git(vault, "symbolic-ref", "HEAD", "refs/heads/main")
    is_brain = (vault / "_meta" / "Conventions.md").exists()
    fill_starter(run, vault)
    if not is_brain and commit_all(vault, STARTER_MESSAGE):
        push(vault)


def make_repo_steps(vault):
    return (f'  git -C "{vault}" init -b main\n'
            f'  git -C "{vault}" add -A\n'
            f'  git -C "{vault}" commit -m "Start the vault"\n'
            "  brain setup --vault-repo <url of an empty private repo>")


def merge_hint(vault, repo):
    return (f"brain setup: {repo} already has history and {vault} has notes of its own; "
            "setup won't merge them. To merge by hand:\n"
            f'  git -C "{vault}" remote add origin {repo}\n'
            f'  git -C "{vault}" pull --no-rebase --allow-unrelated-histories origin main\n'
            f'  git -C "{vault}" push -u origin HEAD')


def prepare_with_repo(run, vault, repo):
    empty_remote = remote_is_empty(repo)
    if is_empty(vault):
        clone_and_seed(run, repo, vault, empty_remote)
        return
    if not (vault / ".git").exists():
        raise SystemExit(f"brain setup: {vault} has files but isn't a git repo. Make it one first:\n"
                         + make_repo_steps(vault).replace("<url of an empty private repo>", repo))
    origin = vault_git(vault, "remote", "get-url", "origin")
    if ok(origin):
        current = origin.stdout.strip()
        if not same_url(current, repo):
            raise SystemExit(f"brain setup: {vault} already syncs with {current}; not changing it to {repo}")
        pull_first(run, vault)
        fill_starter(run, vault)
        return
    if empty_remote:
        written = fill_starter(run, vault)
        run.say(f"add {repo} as the vault's remote and push")
        if run.dry:
            return
        if written:
            commit_all(vault, "Add the agent-brain starter files")
        vault_git(vault, "remote", "add", "origin", repo)
        push(vault)
        return
    if is_untouched_starter(vault):
        keep = BACKUPS / vault.name
        run.say(f"move the untouched starter vault {vault} to {keep}")
        if not run.dry:
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(vault), str(keep))
        clone_and_seed(run, repo, vault, empty_remote)
        return
    raise SystemExit(merge_hint(vault, repo))


def prepare_vault(run, vault, repo):
    """Make sure `vault` is a usable brain: create, clone, or top up the starter files."""
    vault = Path(vault)
    if repo:
        prepare_with_repo(run, vault, repo)
        return
    if is_empty(vault):
        run.say(f"create a new vault at {vault}")
        fill_starter(run, vault)
        if run.dry:
            return
        vault_git(vault, "init", "-q")
        vault_git(vault, "symbolic-ref", "HEAD", "refs/heads/main")
        commit_all(vault, STARTER_MESSAGE)
        return
    if (vault / ".git").exists():
        pull_first(run, vault)
    fill_starter(run, vault)
    if not (vault / ".git").exists():
        print(f"note: {vault} isn't a git repo, so it won't sync. To sync it, make it one, "
              "then add an empty private repo:\n" + make_repo_steps(vault))
