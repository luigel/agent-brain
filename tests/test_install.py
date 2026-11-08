"""Runs `brain setup` against a throwaway HOME. Run: python3 -m unittest discover -s tests -p test_install.py"""
import json
import subprocess
import unittest

from helpers import BrainTestCase, snapshot

LEGACY_CMD = 'python3 -I "$HOME/.claude/skills/brain/scripts/brain.py" context 2>/dev/null || true'
SERENA = {"matcher": "startup|resume",
          "hooks": [{"type": "command", "command": "serena-hooks activate --client=codex", "timeout": 5}]}


class SetupTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.vault = self.make_vault("Documents/Brain", kit=("planner", "polish"))

        claude = self.make_claude(".claude-work")
        (claude / "skills" / "brain" / "scripts").mkdir(parents=True)
        (claude / "skills" / "brain" / "scripts" / "brain.py").write_text("# old\n")
        (claude / "skills" / "brain" / "SKILL.md").write_text("---\nname: brain\n---\n<!-- Managed by agent-brain -->\nold\n")
        (claude / "settings.json").write_text(json.dumps({
            "theme": "dark",
            "hooks": {"SessionStart": [
                SERENA,
                {"matcher": "startup|resume|clear|compact",
                 "hooks": [{"type": "command", "command": LEGACY_CMD, "timeout": 30}]},
            ]},
        }, indent=2))
        (claude / "CLAUDE.md").write_text(
            "# graphify\n- stuff\n\n# Agent's Brain (long-term memory)\n- old pointer\n\n# Personal Rules\n- Docker\n")

        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [SERENA]}}, indent=4))
        (codex / "AGENTS.md").write_text("# Personal working agreements\n- Docker\n")

    def test_vault_git_sync(self):
        remote = self.home / "remote.git"
        self.git("init", "-q", "--bare", "-b", "main", str(remote))
        seed = self.home / "seed"
        self.git("clone", "-q", str(remote), str(seed))
        (seed / "_meta").mkdir()
        (seed / "_meta" / "Conventions.md").write_text("# Brain conventions\n")
        self.git("add", "-A", cwd=seed)
        self.git("commit", "-q", "-m", "seed", cwd=seed)
        self.git("push", "-q", "origin", "HEAD:main", cwd=seed)

        vault = self.home / "Documents" / "Synced Brain"
        self.brain("setup", "--vault", str(vault), "--vault-repo", str(remote), "--no-universal")
        self.assertTrue((self.home / "brain" / "_meta" / "Conventions.md").exists())

        (vault / "Global").mkdir(exist_ok=True)  # setup creates it now
        (vault / "Global" / "Here.md").write_text("# Here\n")
        self.assertIn("committed and synced", self.brain("sync"))
        log = subprocess.run(["git", "--git-dir", str(remote), "log", "--format=%s", "-1"],
                             env=self.env(), capture_output=True, text=True).stdout
        self.assertIn("Here", log)

        # another machine pushes a note; the next session start pulls it in
        self.git("pull", "-q", cwd=seed)
        (seed / "Global" / "There.md").write_text("# There\n")
        self.git("add", "-A", cwd=seed)
        self.git("commit", "-q", "-m", "from elsewhere", cwd=seed)
        self.git("push", "-q", cwd=seed)
        self.brain("context", str(self.home))
        self.assertTrue((vault / "Global" / "There.md").exists())

    def test_dry_run_changes_nothing(self):
        before = snapshot(self.home)
        self.brain("setup", "--vault", str(self.vault), "--agents", "claude,codex", "--dry-run")
        self.assertEqual(before, snapshot(self.home))
        self.assertFalse((self.home / "brain").exists())

    def test_claude_wiring(self):
        self.brain("setup", "--vault", str(self.vault))
        claude = self.home / ".claude-work"
        self.assertEqual((self.home / "brain").resolve(), self.vault.resolve())
        self.assertTrue((claude / "skills" / "brain" / "SKILL.md").exists())
        self.assertFalse((claude / "skills" / "brain" / "scripts").exists())

        s = json.loads((claude / "settings.json").read_text())
        self.assertEqual(s["theme"], "dark")
        self.assertIs(s["autoMemoryEnabled"], False)
        start_cmds = [h["command"] for e in s["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertIn(SERENA["hooks"][0]["command"], start_cmds)
        self.assertNotIn(LEGACY_CMD, start_cmds)
        self.assertEqual(sum(c.endswith('" context 2>/dev/null || true') for c in start_cmds), 1)
        stop_cmds = [h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(len(stop_cmds), 1)
        self.assertIn("stop-check", stop_cmds[0])

        md = (claude / "CLAUDE.md").read_text()
        self.assertEqual(md.count("# Agent's Brain"), 1)
        self.assertNotIn("old pointer", md)
        self.assertIn("<!-- agent-brain:start -->", md)
        self.assertIn("# graphify", md)
        self.assertIn("# Personal Rules\n- Docker", md)

    def test_own_hook_keeps_user_fields(self):  # final review #5
        self.brain("setup", "--vault", str(self.vault))
        path = self.home / ".claude-work" / "settings.json"
        s = json.loads(path.read_text())
        for e in s["hooks"]["SessionStart"]:
            for h in e["hooks"]:
                if "context" in h["command"]:
                    h["statusMessage"] = "Loading the brain"
        path.write_text(json.dumps(s, indent=2))
        self.brain("setup")
        s = json.loads(path.read_text())
        ours = [h for e in s["hooks"]["SessionStart"] for h in e["hooks"] if "context" in h["command"]]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].get("statusMessage"), "Loading the brain")

    def test_codex_wiring(self):
        self.brain("setup", "--vault", str(self.vault), "--agents", "codex")
        codex = self.home / ".codex"
        hooks = json.loads((codex / "hooks.json").read_text())
        cmds = [h["command"] for e in hooks["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertIn(SERENA["hooks"][0]["command"], cmds)
        self.assertTrue(any(c.endswith('" context --json 2>/dev/null || true') for c in cmds))
        # Codex reads user skills from ~/.agents/skills, so that's where they go
        self.assertTrue((self.home / ".agents" / "skills" / "brain" / "SKILL.md").exists())
        self.assertFalse((codex / "skills" / "brain").exists())
        agents = (codex / "AGENTS.md").read_text()
        self.assertIn("# Personal working agreements", agents)
        self.assertIn("# Agent's Brain", agents)

    def test_global_skills_everywhere(self):
        self.brain("setup", "--vault", str(self.vault))
        for target in (self.home / ".claude-work" / "skills", self.home / ".agents" / "skills"):
            for name in ("brain", "planner", "polish"):
                self.assertTrue((target / name / "SKILL.md").exists(), f"{target}/{name}")
            self.assertEqual(json.loads((target / ".agent-brain-managed.json").read_text()),
                             ["brain", "planner", "polish"])

    def test_foreign_copy_is_kept_until_adopted(self):
        mine = self.home / ".agents" / "skills" / "planner"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: planner\n---\nhand-made\n")
        out = self.brain("setup", "--vault", str(self.vault))
        self.assertIn("--adopt planner", out)
        self.assertIn("hand-made", (mine / "SKILL.md").read_text())

        self.brain("setup", "--adopt", "planner")
        self.assertNotIn("hand-made", (mine / "SKILL.md").read_text())
        backups = list((self.home / ".cache" / "agent-brain" / "backups").rglob("planner/SKILL.md"))
        self.assertEqual(len(backups), 1)
        self.assertIn("hand-made", backups[0].read_text())

    def test_claude_ai_synced_skill_wins(self):
        synced = self.home / ".claude-work" / "skills" / "synced" / "org_x" / "polish"
        synced.mkdir(parents=True)
        (synced / "SKILL.md").write_text("---\nname: polish\n---\n")
        out = self.brain("setup", "--vault", str(self.vault))
        self.assertIn("claude.ai account already syncs", out)
        self.assertFalse((self.home / ".claude-work" / "skills" / "polish").exists())
        self.assertTrue((self.home / ".agents" / "skills" / "polish").exists())

    def test_codex_copy_blocks_shared_duplicate(self):
        own = self.home / ".codex" / "skills" / "brain"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("---\nname: brain\n---\ncodex's own\n")
        self.brain("setup", "--vault", str(self.vault))
        self.assertFalse((self.home / ".agents" / "skills" / "brain").exists())
        self.assertTrue((self.home / ".agents" / "skills" / "polish").exists())

    def test_dropped_skill_is_removed(self):
        self.brain("setup", "--vault", str(self.vault))
        target = self.home / ".agents" / "skills"
        (target / "retired").mkdir()
        (target / "retired" / "SKILL.md").write_text("x")
        (target / ".agent-brain-managed.json").write_text(json.dumps(["brain", "planner", "retired", "polish"]))
        self.brain("setup")
        self.assertFalse((target / "retired").exists())

    def test_rerun_is_idempotent(self):
        self.brain("setup", "--vault", str(self.vault), "--agents", "claude,codex")
        first = snapshot(self.home)
        out = self.brain("setup", "--agents", "claude,codex")  # vault defaults to where ~/brain points
        self.assertEqual(first, snapshot(self.home))
        self.assertNotIn("write ", out)


if __name__ == "__main__":
    unittest.main()
