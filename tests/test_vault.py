"""Where the vault lives, the starter vault, and every `--vault-repo` case."""
import unittest

from helpers import BrainTestCase, snapshot

STARTER = "Start the vault from the agent-brain starter"


class LocalVaultTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.make_claude()

    def test_fresh_setup_creates_starter_vault(self):
        self.brain("setup", "--no-universal")
        vault = self.home / "Documents" / "Agent Brain"
        self.assertEqual((self.home / "brain").resolve(), vault.resolve())
        for rel in ("Home.md", "_meta/Conventions.md", ".gitignore", ".graphifyignore"):
            self.assertTrue((vault / rel).is_file(), rel)
        self.assertTrue((vault / "Global").is_dir() and (vault / "Projects").is_dir())
        self.assertEqual(self.git("-C", str(vault), "log", "--format=%s").split("\n")[0], STARTER)
        self.assertEqual(self.git("-C", str(vault), "branch", "--show-current").strip(), "main")

    def test_existing_files_are_never_overwritten(self):
        vault = self.make_vault()
        (vault / "_meta" / "Conventions.md").write_text("# Mine\n")
        (vault / ".graphifyignore").write_text("drafts/\n")
        self.brain("setup", "--vault", str(vault), "--no-universal")
        self.assertEqual((vault / "_meta" / "Conventions.md").read_text(), "# Mine\n")
        self.assertTrue((vault / "Home.md").is_file())
        ignore = (vault / ".graphifyignore").read_text()
        self.assertTrue(ignore.startswith("drafts/\n"))
        self.assertIn("_meta/skills/", ignore)
        self.assertIn("_meta/third-party.json", ignore)

    def test_plain_folder_is_not_made_a_repo(self):
        vault = self.make_vault()
        out = self.brain("setup", "--vault", str(vault), "--no-universal")
        self.assertFalse((vault / ".git").exists())
        self.assertIn("brain setup --vault-repo", out)

    def test_plain_folder_sync_advice_works(self):  # final review #3
        vault = self.make_vault()
        out = self.brain("setup", "--vault", str(vault), "--no-universal")
        self.assertIn("init -b main", out)
        self.assertIn("init -b main", self.run_brain("doctor").stdout)
        self.git("-C", str(vault), "init", "-q", "-b", "main")
        self.git("-C", str(vault), "add", "-A")
        self.git("-C", str(vault), "commit", "-qm", "Start the vault")
        remote = self.bare_remote()
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertIn("_meta/Conventions.md", self.git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main"))

    def test_vault_path_with_apostrophe(self):  # Review Focus 1
        vault = self.home / "Documents" / "It's Mine" / "It's Mine"
        self.brain("setup", "--vault", str(vault), "--no-universal")
        self.assertEqual((self.home / "brain").resolve(), vault.resolve())
        self.assertIn("Start the vault", self.git("-C", str(vault), "log", "--format=%s"))

    def test_missing_git_identity_still_sets_up(self):  # Review Focus 2
        r = self.run_brain("setup", "--no-universal", env=self.env(GIT_AUTHOR_NAME="", GIT_COMMITTER_NAME=""))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("brain sync", r.stdout)
        self.assertTrue((self.home / "Documents" / "Agent Brain" / "Home.md").is_file())

    def test_dangling_brain_link_is_an_error(self):  # Review Focus 3
        (self.home / "brain").symlink_to(self.home / "gone")
        self.assertIn("--vault", self.brain_fails("setup", "--no-universal"))
        self.assertFalse((self.home / "gone").exists())


class SyncRepoTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.make_claude()
        self.vault = self.home / "Documents" / "Agent Brain"

    def files(self, remote):
        return self.git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main")

    def test_empty_remote_is_seeded_and_pushed(self):
        remote = self.bare_remote()
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertIn("Start the vault", self.git("--git-dir", str(remote), "log", "--format=%s", "main"))

    def test_non_brain_remote_gets_starter_files(self):
        remote = self.bare_remote(seed={"README.md": "# hi\n"})
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertIn("README.md", self.files(remote))
        self.assertIn("_meta/Conventions.md", self.files(remote))

    def test_existing_brain_is_cloned_as_is(self):
        remote = self.bare_remote(seed={"Home.md": "# Mine\n", "_meta/Conventions.md": "# C\n"})
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertEqual((self.home / "brain" / "Home.md").read_text(), "# Mine\n")
        self.assertEqual(self.git("--git-dir", str(remote), "rev-list", "--count", "main").strip(), "1")

    def test_local_vault_gets_remote_added(self):
        self.brain("setup", "--no-universal")
        (self.vault / "Global" / "Mine.md").write_text("# Mine\n")
        self.brain("sync")
        remote = self.bare_remote()
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertIn("Global/Mine.md", self.files(remote))
        self.assertEqual(self.git("-C", str(self.vault), "rev-parse", "--abbrev-ref", "@{u}").strip(), "origin/main")

    def test_untouched_starter_is_replaced_by_clone(self):
        self.brain("setup", "--no-universal")
        remote = self.bare_remote(seed={"Home.md": "# Other machine\n", "_meta/Conventions.md": "# C\n"})
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertEqual((self.vault / "Home.md").read_text(), "# Other machine\n")
        self.assertEqual(len(list((self.home / ".cache" / "agent-brain" / "backups").rglob("Home.md"))), 1)

    def test_local_notes_and_remote_history_stop(self):
        self.brain("setup", "--no-universal")
        (self.vault / "Global" / "Mine.md").write_text("# Mine\n")
        self.brain("sync")
        remote = self.bare_remote(seed={"Home.md": "# Other\n"})
        out = self.brain_fails("setup", "--vault-repo", str(remote), "--no-universal")
        self.assertIn("--allow-unrelated-histories", out)
        self.assertEqual(self.git("-C", str(self.vault), "remote").strip(), "")

    def test_different_remote_is_an_error(self):
        a, b = self.bare_remote("a.git"), self.bare_remote("b.git")
        self.brain("setup", "--vault-repo", str(a), "--no-universal")
        self.brain_fails("setup", "--vault-repo", str(b), "--no-universal")
        self.brain("setup", "--vault-repo", str(a) + "/", "--no-universal")  # same URL, trailing slash
        self.assertEqual(self.git("-C", str(self.home / "brain"), "remote", "get-url", "origin").strip(), str(a))

    def test_plain_folder_with_repo_is_an_error(self):
        vault = self.make_vault()
        self.brain_fails("setup", "--vault", str(vault), "--vault-repo", str(self.bare_remote()), "--no-universal")
        self.assertFalse((vault / ".git").exists())

    def test_unreachable_repo_leaves_nothing(self):  # Review Focus 4
        self.brain_fails("setup", "--vault-repo", str(self.home / "nope.git"), "--no-universal")
        self.assertFalse(self.vault.exists())
        self.assertFalse((self.home / "brain").is_symlink())

    def test_dry_run_with_repo_changes_nothing(self):  # Review Focus 5
        remote = self.bare_remote()
        before = snapshot(self.home)
        self.brain("setup", "--vault-repo", str(remote), "--dry-run", "--no-universal")
        self.assertEqual(before, snapshot(self.home))

    def test_failed_first_push_recovers_on_sync(self):  # final review #1
        remote = self.bare_remote()
        r = self.run_brain("setup", "--vault-repo", str(remote), "--no-universal",
                           env=self.env(GIT_AUTHOR_NAME="", GIT_COMMITTER_NAME=""))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("committed and synced", self.brain("sync"))
        self.assertIn("Home.md", self.files(remote))

    def test_rejected_push_recovers_on_sync(self):  # final review #1
        self.brain("setup", "--no-universal")
        remote = self.bare_remote()
        hook = remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.brain("setup", "--vault-repo", str(remote), "--no-universal")
        hook.unlink()
        self.assertNotIn("failed", self.brain("sync"))
        self.assertIn("Home.md", self.files(remote))

    def test_doctor_accepts_local_only(self):
        self.brain("setup", "--no-universal")
        out = self.run_brain("doctor").stdout
        self.assertIn("local only", out)
        self.assertNotIn("✗ vault git remote", out)


if __name__ == "__main__":
    unittest.main()
