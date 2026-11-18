"""Archive and restore the skills associated with a vault project."""
import fcntl
import filecmp
import os
import shutil
import stat
import tempfile
from pathlib import Path

from . import core


def validate_name(name):
    if (
        not name
        or name[:1] == "."
        or name != name.strip()
        or name.endswith(".")
        or any(c in name for c in '/\\*?[]:"<>|')
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise ValueError(f"invalid name {name!r}; use a single non-hidden path component")
    return name


def checked_directory(root, relative):
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"expected a real directory at {path}")
    return path


def archive_for(name):
    validate_name(name)
    projects = list(core.projects())
    exact = [project for project in projects if project[0] == name]
    slug = core.slug(name)
    matches = exact or [project for project in projects if slug and core.slug(project[0]) == slug]
    if not matches:
        raise ValueError(f"unknown project {name!r}; create its hub with brain init-project")
    if len(matches) > 1:
        choices = ", ".join(repr(project[0]) for project in matches)
        raise ValueError(f"ambiguous project {name!r}; choose an exact name from {choices}")
    canonical, _, hub = matches[0]
    validate_name(canonical)
    if hub.is_symlink():
        raise ValueError(f"expected a real project hub at {hub}")
    return checked_directory(core.root(), Path("Projects", canonical, core.PROJECT_SKILLS))


def file_kind(path):
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return mode & 0o111
    raise ValueError(f"expected an ordinary file or directory at {path}")


def tree_contents(path):
    kind = file_kind(path)
    yield Path("."), kind
    if kind == "directory":
        for child in sorted(path.iterdir()):
            if child.name.casefold() == ".git":
                raise ValueError(f"cannot archive Git metadata at {child}")
            for relative, child_kind in tree_contents(child):
                yield Path(child.name) / relative, child_kind


def validate_skill(path):
    if file_kind(path) != "directory" or not (path / "SKILL.md").is_file():
        raise ValueError(f"{path} has no regular SKILL.md")
    if file_kind(path / "SKILL.md") == "directory":
        raise ValueError(f"{path} has no regular SKILL.md")


def same_contents(source, destination, contents):
    if contents != list(tree_contents(destination)):
        return False
    filecmp.clear_cache()
    return all(
        filecmp.cmp(source / relative, destination / relative, shallow=False)
        for relative, kind in contents
        if kind != "directory"
    )


def pending_copies(copies):
    pending = []
    seen = set()
    for source, destination in copies:
        key = str(destination).casefold()
        if key in seen:
            raise ValueError(f"multiple assets would use {destination}")
        seen.add(key)
        contents = list(tree_contents(source))
        if not destination.exists() and not destination.is_symlink():
            pending.append((source, destination))
        elif not same_contents(source, destination, contents):
            raise ValueError(f"destination already has different contents at {destination}")
    return pending


def copy_pending(pending):
    for source, destination in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".brain-skill-", dir=destination.parent) as staging:
            staged = Path(staging) / destination.name
            if source.is_dir():
                shutil.copytree(source, staged, symlinks=True)
                list(tree_contents(staged))
                mode = stat.S_IMODE(staged.stat().st_mode)
                # macOS requires write access to update the moved directory's parent entry.
                staged.chmod(mode | stat.S_IWUSR)
                destination.mkdir()
                try:
                    staged.rename(destination)
                except OSError:
                    destination.rmdir()
                    raise
                destination.chmod(mode)
            else:
                shutil.copy2(source, staged, follow_symlinks=False)
                file_kind(staged)
                os.link(staged, destination)


def import_skill(source, project, name, siblings):
    archive = archive_for(project)
    source = Path(source).expanduser().resolve()
    validate_skill(source)
    if archive.is_relative_to(source):
        raise ValueError(f"the archive cannot be inside the source folder {source}")
    name = validate_name(source.name if name is None else name)
    if name.casefold() in {"brain", "skill.md"}:
        raise ValueError(f"reserved skill name {name!r}")

    copies = [(source, archive / name)]
    for item in siblings:
        sibling = Path(item).expanduser()
        if sibling.parent.resolve() != source.parent:
            raise ValueError(f"expected a sibling of {source} at {sibling}")
        if file_kind(sibling) == "directory":
            raise ValueError(f"expected a regular sibling file at {sibling}")
        copies.append((sibling, archive / validate_name(sibling.name)))

    pending = pending_copies(copies)
    core.ensure_project_skill_exclusion(core.root())
    core.ensure_project_skill_exclusion(archive.parent)
    copy_pending(pending)
    if pending:
        print(f"archived {archive / name}")
    else:
        print(f"already archived {archive / name}")
    core.spawn_sync()


def checkout_skill_dirs(checkout):
    agents = checked_directory(checkout, Path(".agents", "skills"))
    claude = checked_directory(checkout, Path(".claude")) / "skills"
    if claude.is_symlink():
        if claude.resolve() != agents:
            raise ValueError(f"expected {claude} to point to {agents}")
        return [agents]
    return [agents, checked_directory(checkout, Path(".claude", "skills"))]


def git_exclusions(checkout, targets, assets):
    if (checkout / ".git").is_symlink():
        raise ValueError(f"expected real Git metadata at {checkout / '.git'}")
    result = core.git("rev-parse", "--show-toplevel", cwd=checkout)
    if result is None:
        raise ValueError(f"could not check Git at {checkout}")
    if result.returncode:
        if "not a git repository" in result.stderr:
            return None
        raise ValueError(result.stderr.strip())

    repo = Path(result.stdout.rstrip("\n")).resolve()
    if (repo / ".git").is_symlink():
        raise ValueError(f"expected real Git metadata at {repo / '.git'}")
    parents = [target.relative_to(repo).as_posix() for target in targets]
    paths = [
        ((target / asset.name).relative_to(repo).as_posix(), asset.is_dir())
        for target in targets for asset in assets
    ]
    if any("\n" in path or "\r" in path for path, _ in paths):
        raise ValueError("cannot add Git exclusions for a path with a line break")
    ancestor_paths = sorted({p.as_posix() for parent in parents for p in Path(parent).parents if p != Path(".")})
    specs = [f":(icase,literal){path}" for path in [*ancestor_paths, *parents]]
    index = core.git("ls-files", "-z", "--", *specs, cwd=repo)
    if not core.ok(index):
        raise ValueError(f"could not inspect tracked paths in {repo}")
    for tracked in index.stdout.split("\0"):
        if not tracked:
            continue
        for path, _ in paths:
            entry, destination = tracked.casefold(), path.casefold()
            if entry == destination or entry.startswith(destination + "/") or destination.startswith(entry + "/"):
                raise ValueError(f"destination overlaps tracked path {repo / tracked}")

    result = core.git("rev-parse", "--path-format=absolute", "--git-path", "info/exclude", cwd=checkout)
    if not core.ok(result):
        raise ValueError(f"could not find Git's local exclude file for {checkout}")
    exclude = Path(result.stdout.rstrip("\n"))
    if exclude.parent.is_symlink() or exclude.is_symlink() or (exclude.exists() and not exclude.is_file()):
        raise ValueError(f"expected a regular exclude file at {exclude}")
    return repo, exclude, [path + ("/" if directory else "") for path, directory in paths]


def ignored_paths(repo, paths):
    result = core.git("check-ignore", "--no-index", "-z", "--stdin", cwd=repo, input="\0".join(paths) + "\0")
    if result is None or result.returncode not in (0, 1):
        raise ValueError(f"could not verify Git exclusions in {repo}")
    return set(result.stdout.split("\0"))


def ensure_git_exclusions(repo, path, paths):
    if not paths:
        return
    rules = {
        target: ("/" + "".join("\\" + c if c in "*?[]\\" else c for c in target)).encode()
        for target in paths
    }
    existed = path.exists()
    content = path.read_bytes() if existed else b""
    if set(rules.values()).issubset(content.splitlines()) and set(paths).issubset(ignored_paths(repo, paths)):
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a+b") as exclude:
            fcntl.flock(exclude, fcntl.LOCK_EX)
            exclude.seek(0)
            original = exclude.read()
            previous_rules = set(original.splitlines())
            already_ignored = ignored_paths(repo, paths)
            extra = [rule for target, rule in rules.items() if rule not in previous_rules or target not in already_ignored]
            if extra:
                separator = b"\n" if original and not original.endswith(b"\n") else b""
                try:
                    exclude.write(separator + b"\n".join(extra) + b"\n")
                    exclude.flush()
                    remaining = set(paths) - ignored_paths(repo, paths)
                    if remaining:
                        target = min(remaining)
                        raise ValueError(f"Git ignore rules keep {target} visible; check the checkout's .gitignore")
                except (OSError, ValueError):
                    exclude.truncate(len(original))
                    raise
    except (OSError, ValueError):
        if not existed:
            path.unlink(missing_ok=True)
        raise


def restore(project, directory):
    archive = archive_for(project)
    if not archive.is_dir():
        raise ValueError(f"no skills archived for {project!r}")
    checkout = Path(directory).expanduser().resolve(strict=True)
    if not checkout.is_dir() or checkout == Path.home().resolve() or checkout.is_relative_to(core.root()):
        raise ValueError(f"expected a checkout directory at {checkout}")

    assets = sorted(archive.iterdir())
    for asset in assets:
        validate_name(asset.name)
        if file_kind(asset) == "directory":
            validate_skill(asset)
            if asset.name.casefold() in {"brain", "skill.md"}:
                raise ValueError(f"reserved skill name {asset.name!r}")
    targets = checkout_skill_dirs(checkout)
    pending = pending_copies([(asset, target / asset.name) for target in targets for asset in assets])
    exclusions = git_exclusions(checkout, targets, assets)
    if exclusions is not None:
        ensure_git_exclusions(*exclusions)
    copy_pending(pending)
    print(f"{'restored' if pending else 'already restored'} {sum(asset.is_dir() for asset in assets)} skills in {checkout}")
