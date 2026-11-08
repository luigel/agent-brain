"""Shared fixtures: every test runs `brain` against a throwaway HOME."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
GIT_IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in Path(root).rglob("*")
            if p.is_file() and ".graphify" not in p.parts and ".cache" not in p.parts}


class BrainTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **extra):
        return {**os.environ, "HOME": str(self.home), "PYTHONPATH": str(SRC), **GIT_IDENT, **extra}

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env(), check=True,
                              capture_output=True, text=True).stdout

    def run_brain(self, *args, env=None, input=None, cwd=None):
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run([sys.executable, "-m", "agent_brain", *args], env=env or self.env(),
                              capture_output=True, text=True, timeout=120, cwd=cwd, **stdin)

    def brain(self, *args, cwd=None):
        r = self.run_brain(*args, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def brain_fails(self, *args):
        r = self.run_brain(*args)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def make_claude(self, name=".claude-work", link=True):
        d = self.home / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text("{}\n")
        if link:
            (self.home / ".claude").symlink_to(d)
        return d

    def make_codex(self):
        d = self.home / ".codex"
        d.mkdir(parents=True, exist_ok=True)
        (d / "hooks.json").write_text("{}\n")
        return d

    def make_vault(self, rel="Documents/Brain", kit=()):
        vault = self.home / rel
        (vault / "_meta").mkdir(parents=True, exist_ok=True)
        (vault / "_meta" / "Conventions.md").write_text("# Brain conventions\n")
        for name in kit:
            (vault / "_meta" / "skills" / name).mkdir(parents=True, exist_ok=True)
            (vault / "_meta" / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n{name}\n")
        return vault

    def bare_remote(self, name="remote.git", seed=None):
        remote = self.home / name
        self.git("init", "-q", "--bare", "-b", "main", str(remote))
        if seed:
            work = self.home / f"seed-{name}"
            self.git("clone", "-q", str(remote), str(work))
            self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=work)
            for rel, text in seed.items():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / rel).write_text(text)
            self.git("add", "-A", cwd=work)
            self.git("commit", "-qm", "seed", cwd=work)
            self.git("push", "-q", "origin", "HEAD:main", cwd=work)
        return remote


def load_json(path):
    return json.loads(Path(path).read_text())
