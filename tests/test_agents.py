"""Setup finds the installed agents itself, and `brain skill import` adds to the dev's own kit."""
import json
import shutil
import unittest

from helpers import BrainTestCase


class AgentsTest(BrainTestCase):
    def test_both_agents_detected(self):
        self.make_claude()
        self.make_codex()
        self.brain("setup")
        hooks = json.loads((self.home / ".codex" / "hooks.json").read_text())
        self.assertTrue(any("context --json" in h["command"]
                            for e in hooks["hooks"]["SessionStart"] for h in e["hooks"]))

    def test_only_claude_detected(self):
        self.make_claude()
        self.brain("setup")
        self.assertFalse((self.home / ".codex").exists())

    def test_no_agent_is_an_error(self):
        self.assertIn("--agents", self.brain_fails("setup"))

    def test_skill_import_goes_to_vault_and_wired_targets(self):
        claude = self.make_claude()
        other = self.make_claude(".claude-other", link=False)  # never set up
        self.brain("setup")
        src = self.home / "mine"
        src.mkdir()
        (src / "SKILL.md").write_text("---\nname: mine\n---\n")
        self.brain("skill", "import", str(src))
        self.assertTrue((self.home / "brain" / "_meta" / "skills" / "mine" / "SKILL.md").exists())
        self.assertTrue((claude / "skills" / "mine" / "SKILL.md").exists())
        self.assertTrue((self.home / ".agents" / "skills" / "mine" / "SKILL.md").exists())
        self.assertFalse((other / "skills" / "mine").exists())

    def test_skill_import_keeps_unsynced_kit(self):  # final review #2
        self.make_claude()
        vault = self.make_vault(kit=("planner",))
        self.brain("setup", "--vault", str(vault))
        shutil.rmtree(vault / "_meta" / "skills")  # this machine's vault hasn't synced the kit yet
        src = self.home / "mine"
        src.mkdir()
        (src / "SKILL.md").write_text("---\nname: mine\n---\n")
        self.brain("skill", "import", str(src))
        self.assertTrue((self.home / ".agents" / "skills" / "planner" / "SKILL.md").exists())
        self.assertTrue((self.home / ".agents" / "skills" / "mine" / "SKILL.md").exists())

    def test_help_describes_the_kit(self):  # final review #8
        out = self.brain("--help")
        self.assertIn("add a skill folder to your kit", out)
        self.assertNotIn("editable", out)


if __name__ == "__main__":
    unittest.main()
