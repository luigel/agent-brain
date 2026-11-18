"""Project skills are archived in a vault and restored into an explicit checkout."""
import json
import shutil
import stat
import unittest

from helpers import BrainTestCase, snapshot


class ProjectSkillsTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.vault = self.make_vault(kit=("global-skill",))
        (self.home / "brain").symlink_to(self.vault)
        self.project = self.vault / "Projects" / "Better World"
        self.project.mkdir(parents=True)
        (self.project / "Better World.md").write_text(
            "---\ntype: project\npaths: [~/old-checkout]\n---\n# Better World hub\n"
        )
        self.source = self.home / "sources" / "planner"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "SKILL.md").write_text("# Archive-only unique-skill-marker\n")
        self.asset = self.source / "scripts" / "run"
        self.asset.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.asset.chmod(0o755)
        self.shared = self.source.parent / "shared.md"
        self.shared.write_text("# Archive-only shared-marker\n")
        self.archive = self.project / "Skills"

    def import_skill(self, *args):
        return self.brain("skill", "import", str(self.source), "--project", "better-world", *args)

    def test_import_archives_full_folder_and_explicit_sibling(self):
        self.import_skill("--name", "bw-planner", "--include-sibling", str(self.shared))
        target = self.archive / "bw-planner"
        self.assertEqual(snapshot(target), snapshot(self.source))
        self.assertTrue((target / "scripts" / "run").stat().st_mode & stat.S_IXUSR)
        self.assertEqual((self.archive / "shared.md").read_bytes(), self.shared.read_bytes())
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.vault / "_meta" / "skills" / "bw-planner").exists())

    def test_restore_copies_to_both_agents_in_a_different_checkout(self):
        self.import_skill("--include-sibling", str(self.shared))
        checkout = self.home / "new-machine" / "bw-workspace"
        checkout.mkdir(parents=True)
        self.brain("skills", "restore", "--project", "Better World", "--directory", str(checkout))
        for agent in (".agents", ".claude"):
            target = checkout / agent / "skills"
            self.assertEqual(snapshot(target / "planner"), snapshot(self.source))
            self.assertTrue((target / "planner" / "scripts" / "run").stat().st_mode & stat.S_IXUSR)
            self.assertEqual((target / "shared.md").read_bytes(), self.shared.read_bytes())
            self.assertFalse((target / "planner").is_symlink())
        self.assertFalse((self.home / "old-checkout").exists())
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".claude").exists())

    def test_restore_hides_only_restored_paths_in_linked_worktree(self):
        self.import_skill("--include-sibling", str(self.shared))
        repo = self.home / "repo"
        repo.mkdir()
        self.git("init", "-q", cwd=repo)
        (repo / ".gitignore").write_text("# tracked rules\n")
        self.git("add", ".gitignore", cwd=repo)
        self.git("commit", "-qm", "initial", cwd=repo)
        checkout = self.home / "checkout"
        self.git("worktree", "add", "-q", "-b", "restored", str(checkout), cwd=repo)
        exclude = repo / ".git" / "info" / "exclude"
        exclude.write_text("# local rules\nkeep-local")
        (checkout / ".claude").mkdir()
        alias = checkout / ".claude" / "skills"
        alias.symlink_to("../.agents/skills")
        self.brain("skills", "restore", "--project", "Better World", cwd=checkout)
        expected = "# local rules\nkeep-local\n/.agents/skills/planner/\n/.agents/skills/shared.md\n"
        self.assertEqual(exclude.read_text(), expected)
        target = checkout / ".agents" / "skills"
        self.assertTrue(alias.is_symlink())
        self.assertEqual(snapshot(alias / "planner"), snapshot(self.source))
        before = (target / "planner" / "SKILL.md").stat().st_mtime_ns
        self.assertIn("already restored", self.brain("skills", "restore", "--project", "Better World", cwd=checkout))
        self.assertEqual((target / "planner" / "SKILL.md").stat().st_mtime_ns, before)
        self.assertEqual(exclude.read_text(), expected)
        self.assertEqual((checkout / ".gitignore").read_text(), "# tracked rules\n")
        (target / "unrelated.md").write_text("unrelated\n")
        status = self.git("status", "--porcelain", "--untracked-files=all", cwd=checkout)
        self.assertEqual(status.splitlines(), ["?? .agents/skills/unrelated.md", "?? .claude/skills"])

    def test_restore_refuses_identical_tracked_destination(self):
        self.import_skill()
        checkout = self.home / "repo"
        checkout.mkdir()
        self.git("init", "-q", cwd=checkout)
        tracked = checkout / ".agents" / "skills" / "planner"
        (tracked / "scripts").mkdir(parents=True)
        (tracked / "SKILL.md").write_bytes((self.source / "SKILL.md").read_bytes())
        (tracked / "scripts" / "run").write_bytes(self.asset.read_bytes())
        (tracked / "scripts" / "run").chmod(0o755)
        self.git("add", "--", ".agents", cwd=checkout)
        exclude = checkout / ".git" / "info" / "exclude"
        before = exclude.read_bytes()
        result = self.run_brain("skills", "restore", "--project", "Better World", cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked", result.stderr)
        self.assertFalse((checkout / ".claude").exists())
        self.assertEqual(exclude.read_bytes(), before)

    def test_recall_skips_archived_skills_and_siblings(self):
        self.import_skill("--include-sibling", str(self.shared))
        self.assertEqual(self.brain("find", "unique-skill-marker").strip(), "")
        self.assertEqual(self.brain("find", "shared-marker").strip(), "")
        self.assertNotIn("Skills/", self.brain("query", "unique-skill-marker", "--all"))

    @unittest.skipUnless(shutil.which("graphify"), "graphify not on PATH")
    def test_archive_graphs_exclude_markdown_and_code_even_in_an_older_vault(self):
        (self.vault / ".graphifyignore").write_text("# keep vault rule\nOther/")
        (self.project / ".graphifyignore").write_text("# keep project rule\nDrafts/")
        (self.project / "A project note.md").write_text("# A project note\n")
        (self.source / "helper.py").write_text("def archived_helper():\n    return True\n")
        self.import_skill("--include-sibling", str(self.shared))
        for root in (self.vault, self.project):
            ignore = root / ".graphifyignore"
            self.assertIn("Skills/", ignore.read_text())
            ignore.write_text(ignore.read_text().split("\nSkills/")[0].split("\nProjects/*/Skills/")[0])
        self.brain("rebuild")
        graphs = self.home / ".graphify" / "brain"
        for scope in ("all", "projects/better-world"):
            graph = json.loads((graphs / scope / "graph.json").read_text())
            sources = [node.get("source_file") or "" for node in graph["nodes"]]
            self.assertTrue(any(path.endswith("A project note.md") for path in sources))
            self.assertFalse([path for path in sources if "Skills/" in path])
        self.assertEqual((self.vault / ".graphifyignore").read_text(), "# keep vault rule\nOther/\nProjects/*/Skills/\n")
        self.assertEqual((self.project / ".graphifyignore").read_text(), "# keep project rule\nDrafts/\nSkills/\n")

    def test_restore_preflights_conflicts_across_all_skills_and_agents(self):
        self.import_skill()
        self.import_skill("--name", "earlier")
        checkout = self.home / "checkout"
        local = checkout / ".claude" / "skills" / "planner"
        local.mkdir(parents=True)
        (local / "SKILL.md").write_text("local edits\n")
        result = self.run_brain("skills", "restore", "--project", "Better World", cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different contents", result.stderr)
        self.assertEqual((local / "SKILL.md").read_text(), "local edits\n")
        self.assertFalse((local.parent / "earlier").exists())
        self.assertFalse((checkout / ".agents").exists())

    def test_import_rerun_is_noop_and_conflicting_sibling_is_atomic(self):
        self.import_skill("--include-sibling", str(self.shared))
        first = self.archive / "planner" / "SKILL.md"
        mtime = first.stat().st_mtime_ns
        self.assertIn("already archived", self.import_skill("--include-sibling", str(self.shared)))
        self.assertEqual(first.stat().st_mtime_ns, mtime)
        self.shared.write_text("new sibling version\n")
        self.assertIn("different contents", self.brain_fails(
            "skill", "import", str(self.source), "--project", "Better World",
            "--name", "new-planner", "--include-sibling", str(self.shared),
        ))
        self.assertFalse((self.archive / "new-planner").exists())
        self.assertEqual((self.archive / "shared.md").read_text(), "# Archive-only shared-marker\n")

    def test_import_rejects_invalid_names_and_unknown_hubs(self):
        for args in (
            ("--name", "../escape"), ("--name", ".agent-brain-managed.json"),
            ("--name", ""), ("--name", "brain"), ("--force",),
            ("--project", "../Better World"), ("--project", "Unknown"),
        ):
            with self.subTest(args=args):
                self.brain_fails("skill", "import", str(self.source), "--project", "Better World", *args)
        self.assertFalse(self.archive.exists())

    def test_import_rejects_nested_symlinks_special_files_and_non_sibling_files(self):
        outside = self.home / "outside.md"
        outside.write_text("local only\n")
        link = self.source / "scripts" / "external.md"
        link.symlink_to(outside)
        self.brain_fails("skill", "import", str(self.source), "--project", "Better World")
        link.unlink()
        self.brain_fails(
            "skill", "import", str(self.source), "--project", "Better World", "--include-sibling", str(outside)
        )
        import os
        os.mkfifo(link)
        self.brain_fails("skill", "import", str(self.source), "--project", "Better World")
        self.assertFalse(self.archive.exists())

    def test_restore_refuses_escaping_symlinks_and_global_home(self):
        self.import_skill()
        checkout = self.home / "checkout"
        checkout.mkdir()
        outside = self.home / "outside"
        outside.mkdir()
        (checkout / ".agents").symlink_to(outside)
        self.brain_fails("skills", "restore", "--project", "Better World", "--directory", str(checkout))
        (checkout / ".agents").unlink()
        claude = checkout / ".claude"
        claude.mkdir()
        (claude / "skills").symlink_to(outside)
        self.brain_fails("skills", "restore", "--project", "Better World", "--directory", str(checkout))
        self.brain_fails("skills", "restore", "--project", "Better World", "--directory", str(self.home))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((checkout / ".agents").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_restore_refuses_a_symlink_in_a_synced_archive(self):
        self.import_skill()
        (self.archive / "external.md").symlink_to(self.shared)
        checkout = self.home / "checkout"
        checkout.mkdir()
        self.brain_fails("skills", "restore", "--project", "Better World", "--directory", str(checkout))
        self.assertEqual(list(checkout.iterdir()), [])

    def test_setup_and_global_status_only_manage_the_global_kit(self):
        self.import_skill()
        self.make_claude()
        self.make_codex()
        self.brain("setup")
        self.assertIn("global-skill", self.brain("skills"))
        self.assertNotIn("planner", self.brain("skills"))
        self.assertTrue((self.home / ".agents" / "skills" / "global-skill" / "SKILL.md").is_file())
        self.assertFalse((self.home / ".agents" / "skills" / "planner").exists())

    def test_copy_preserves_readonly_directory_modes(self):
        self.source.chmod(0o555)
        (self.source / "scripts").chmod(0o555)
        self.import_skill()
        checkout = self.home / "checkout"
        checkout.mkdir()
        self.brain("skills", "restore", "--project", "Better World", cwd=checkout)
        for folder in (
            self.archive / "planner",
            checkout / ".agents" / "skills" / "planner",
            checkout / ".claude" / "skills" / "planner",
        ):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o555)
            self.assertEqual(stat.S_IMODE((folder / "scripts").stat().st_mode), 0o555)
            self.assertEqual(snapshot(folder), snapshot(self.source))

    def test_restore_rejects_higher_priority_gitignore_negation(self):
        self.import_skill()
        checkout = self.home / "repo"
        checkout.mkdir()
        self.git("init", "-q", cwd=checkout)
        gitignore = checkout / ".gitignore"
        gitignore.write_text("!.agents/skills/planner/\n!.agents/skills/planner/**\n")
        self.git("add", "--", ".gitignore", cwd=checkout)
        exclude = checkout / ".git" / "info" / "exclude"
        before = exclude.read_bytes()
        result = self.run_brain("skills", "restore", "--project", "Better World", cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".agents/skills/planner", result.stderr)
        self.assertFalse((checkout / ".agents").exists())
        self.assertFalse((checkout / ".claude").exists())
        self.assertEqual(exclude.read_bytes(), before)
        self.assertEqual(gitignore.read_text(), "!.agents/skills/planner/\n!.agents/skills/planner/**\n")

    def test_restore_rejects_symlinked_git_metadata(self):
        self.import_skill()
        checkout = self.home / "repo"
        checkout.mkdir()
        outside = self.home / "elsewhere"
        self.git("init", "-q", "--separate-git-dir", str(outside), cwd=checkout)
        (checkout / ".git").unlink()
        (checkout / ".git").symlink_to(outside, target_is_directory=True)
        exclude = outside / "info" / "exclude"
        before = exclude.read_bytes()
        result = self.run_brain("skills", "restore", "--project", "Better World", cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".git", result.stderr)
        self.assertFalse((checkout / ".agents").exists())
        self.assertFalse((checkout / ".claude").exists())
        self.assertEqual(exclude.read_bytes(), before)

    def test_import_accepts_an_explicit_source_directory_alias(self):
        alias = self.home / "source-alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.brain("skill", "import", str(alias), "--project", "Better World")
        self.assertEqual(snapshot(self.archive / "planner"), snapshot(self.source))

    def test_exact_project_name_takes_priority_over_matching_slug(self):
        other = self.vault / "Projects" / "Better-World"
        other.mkdir()
        (other / "Better-World.md").write_text("# The other project\n")
        self.brain("skill", "import", str(self.source), "--project", "Better-World")
        self.assertEqual(snapshot(other / "Skills" / "planner"), snapshot(self.source))
        self.assertFalse(self.archive.exists())
        checkout = self.home / "checkout"
        checkout.mkdir()
        self.brain("skills", "restore", "--project", "Better-World", cwd=checkout)
        self.assertEqual(snapshot(checkout / ".agents" / "skills" / "planner"), snapshot(self.source))

    def test_ambiguous_slug_cannot_import_or_restore(self):
        other = self.vault / "Projects" / "Better-World"
        other_archive = other / "Skills"
        other_archive.mkdir(parents=True)
        (other / "Better-World.md").write_text("# The other project\n")
        shutil.copytree(self.source, other_archive / "existing")
        self.assertIn("ambiguous", self.brain_fails("skill", "import", str(self.source), "--project", "better-world"))
        self.assertFalse(self.archive.exists())
        self.assertEqual([p.name for p in other_archive.iterdir()], ["existing"])
        checkout = self.home / "checkout"
        checkout.mkdir()
        self.assertIn("ambiguous", self.brain_fails(
            "skills", "restore", "--project", "better-world", "--directory", str(checkout),
        ))
        self.assertEqual(list(checkout.iterdir()), [])
