"""Each dev's own skills and third-party packs live in their vault (`_meta/skills/`, `_meta/third-party.json`)."""
import json
import shutil
import unittest

from helpers import SRC, BrainTestCase


class KitTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.claude = self.make_claude()
        self.vault = self.make_vault(kit=("planner",))

    def test_repo_ships_only_the_brain_skill(self):
        skills = SRC / "agent_brain" / "skills"
        self.assertEqual(sorted(p.name for p in skills.iterdir() if (p / "SKILL.md").exists()), ["brain"])
        self.assertFalse((SRC / "agent_brain" / "third_party.json").exists())

    def test_kit_skills_installed_everywhere(self):
        self.brain("setup", "--vault", str(self.vault))
        for target in (self.claude / "skills", self.home / ".agents" / "skills"):
            self.assertTrue((target / "planner" / "SKILL.md").exists(), target)

    def test_kit_brain_loses_to_bundled(self):
        (self.vault / "_meta" / "skills" / "brain").mkdir()
        (self.vault / "_meta" / "skills" / "brain" / "SKILL.md").write_text("---\nname: brain\n---\nkit brain\n")
        out = self.brain("setup", "--vault", str(self.vault))
        self.assertIn("skip kit skill brain", out)
        self.assertNotIn("kit brain", (self.home / ".agents" / "skills" / "brain" / "SKILL.md").read_text())

    def test_missing_kit_folder_keeps_installed_kit(self):
        self.brain("setup", "--vault", str(self.vault))
        shutil.rmtree(self.vault / "_meta" / "skills")
        self.brain("setup")
        self.assertTrue((self.home / ".agents" / "skills" / "planner" / "SKILL.md").exists())
        (self.vault / "_meta" / "skills").mkdir()
        self.brain("setup")
        self.assertFalse((self.home / ".agents" / "skills" / "planner").exists())

    def test_setup_pulls_kit_from_other_machine(self):
        remote = self.bare_remote(seed={"_meta/Conventions.md": "# C\n"})
        self.brain("setup", "--vault", str(self.home / "Documents" / "Synced"), "--vault-repo", str(remote))
        other = self.home / "other"
        self.git("clone", "-q", str(remote), str(other))
        (other / "_meta" / "skills" / "fresh").mkdir(parents=True)
        (other / "_meta" / "skills" / "fresh" / "SKILL.md").write_text("---\nname: fresh\n---\n")
        self.git("add", "-A", cwd=other)
        self.git("commit", "-qm", "kit", cwd=other)
        self.git("push", "-q", cwd=other)
        self.brain("setup")
        self.assertTrue((self.home / ".agents" / "skills" / "fresh" / "SKILL.md").exists())

    def test_setup_pulls_before_topping_up(self):  # final review #4
        remote = self.bare_remote(seed={"_meta/Conventions.md": "# C\n"})
        vault = self.home / "Documents" / "Synced"
        self.git("clone", "-q", str(remote), str(vault))  # an older clone, without the starter files
        (self.home / "brain").symlink_to(vault)
        other = self.home / "other"
        self.git("clone", "-q", str(remote), str(other))
        (other / ".graphifyignore").write_text("_meta/skills/\n_meta/third-party.json\n")
        (other / "_meta" / "skills" / "fresh").mkdir(parents=True)
        (other / "_meta" / "skills" / "fresh" / "SKILL.md").write_text("---\nname: fresh\n---\n")
        self.git("add", "-A", cwd=other)
        self.git("commit", "-qm", "kit", cwd=other)
        self.git("push", "-q", cwd=other)
        out = self.brain("setup")
        self.assertNotIn("pulling the vault failed", out)
        self.assertTrue((self.home / ".agents" / "skills" / "fresh" / "SKILL.md").exists())

    def test_third_party_without_manifest(self):
        self.assertIn("no third-party packs listed", self.brain("setup", "--vault", str(self.vault), "--third-party"))

    def test_third_party_from_vault_manifest(self):
        pack = self.bare_remote("pack.git", seed={"skills/x/SKILL.md": "---\nname: x\n---\n"})
        (self.vault / "_meta" / "third-party.json").write_text(json.dumps(
            {"git": [{"name": "pack", "repo": str(pack), "dest": "~/.packs/pack"}]}))
        self.brain("setup", "--vault", str(self.vault), "--third-party")
        self.assertTrue((self.home / ".packs" / "pack" / "skills" / "x" / "SKILL.md").exists())

    def test_find_skips_kit(self):
        self.brain("setup", "--vault", str(self.vault))
        self.assertEqual(self.brain("find", "planner").strip(), "")

    @unittest.skipUnless(shutil.which("graphify"), "graphify not on PATH")
    def test_graph_skips_kit(self):
        (self.vault / "Global").mkdir()
        (self.vault / "Global" / "A note.md").write_text("# A note\n")
        self.brain("setup", "--vault", str(self.vault))
        g = json.loads((self.home / ".graphify" / "brain" / "all" / "graph.json").read_text())
        sources = {n.get("source_file", "") for n in g["nodes"]}
        self.assertIn("Global/A note.md", sources)
        self.assertFalse([s for s in sources if s.startswith("_meta/skills")])


if __name__ == "__main__":
    unittest.main()
