"""Recall: `brain query` ranks whole notes (title + body) across the project and Global/,
and `brain context` never loses the preferences to a long hub."""
import re
import unittest

from helpers import BrainTestCase

HUB = "Projects/Shop/Shop.md"
DNS ="Projects/Shop/Gotchas/Docker DNS fails under memory pressure.md"
WORKTREE_TESTS = "Projects/Shop/Patterns/Run tests in a worktree.md"
CONTAINER = "Projects/Shop/References/Container settings.md"
NO_WORKTREES = "Global/Preferences/No worktrees unless asked.md"
OTHER_DNS = "Projects/Other/Gotchas/Other getaddrinfo note.md"


def note(title, body, status="active", projects='["[[Shop]]"]'):
    return (f"---\ntype: gotcha\nprojects: {projects}\ncreated: 2026-11-09\nupdated: 2026-11-09\n"
            f"status: {status}\n---\n# {title}\n\n{body}\n")


def ranked(out):
    return re.findall(r"^\d+\. (.+?\.md)", out, re.M)


def outside(out):
    return re.findall(r"^- (.+?\.md)", out, re.M)


class RecallTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.vault = self.make_vault()
        (self.home / "brain").symlink_to(self.vault)
        self.repo = self.home / "code" / "shop"
        self.repo.mkdir(parents=True)
        self.write("Projects/Shop/Shop.md",
                   f"---\ntype: project\npaths: [{self.repo}]\n---\n# Shop\n\nAn online shop.\n\n## Notes\n"
                   f"- [[Docker DNS fails under memory pressure]]\n- [[Run tests in a worktree]]\n")
        self.write(DNS, note("Docker DNS fails under memory pressure",
                             "When the VM swaps, tests fail with `getaddrinfo for mysql failed`.\n\n"
                             "Related: [[Shop]], [[Container settings]]"))
        self.write(WORKTREE_TESTS, note("Run tests in a worktree", "Use a throwaway container from a worktree."))
        self.write(CONTAINER, note("Container settings", "The VM has 8 GB of RAM.\n\nRelated: [[Shop]]"))
        self.write(NO_WORKTREES, note("No worktrees unless asked",
                                      "Don't create a git worktree unless the user asks for one.", projects="[]"))
        self.write("Projects/Other/Other.md", "---\ntype: project\npaths: [/nowhere]\n---\n# Other\n")
        self.write(OTHER_DNS, note("Other getaddrinfo note", "getaddrinfo again.", projects='["[[Other]]"]'))

    def write(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_query_matches_words_only_in_the_body(self):
        out = self.brain("query", "getaddrinfo for mysql failed", "--project", "Shop")
        self.assertEqual(ranked(out)[0], DNS)

    def test_query_from_repo_folder_includes_global_notes(self):
        out = self.brain("query", "create a git worktree", cwd=self.repo)
        self.assertEqual(ranked(out)[0], NO_WORKTREES)
        self.assertIn(WORKTREE_TESTS, ranked(out))

    def test_project_query_leaves_out_other_projects(self):
        self.assertNotIn(OTHER_DNS, ranked(self.brain("query", "getaddrinfo", "--project", "Shop")))
        self.assertIn(OTHER_DNS, ranked(self.brain("query", "getaddrinfo", "--all")))

    def test_query_without_matches_says_so(self):
        out = self.brain("query", "zzqx", "--project", "Shop")
        self.assertEqual(ranked(out), [])
        self.assertIn("No matching notes", out)

    def test_superseded_note_is_marked(self):
        self.write(WORKTREE_TESTS, note("Run tests in a worktree", "Old advice.", status="superseded"))
        out = self.brain("query", "worktree", "--project", "Shop")
        line = next(l for l in out.splitlines() if WORKTREE_TESTS in l)
        self.assertIn("superseded", line)

    def test_budget_cuts_whole_results(self):
        out = self.brain("query", "worktree", "40", "--project", "Shop")
        self.assertEqual(len(ranked(out)), 1)

    def test_query_leaves_out_the_hub_already_in_context(self):
        self.assertNotIn(HUB, ranked(self.brain("query", "online shop", cwd=self.repo)))
        self.assertIn(HUB, ranked(self.brain("query", "online shop", "--project", "Shop", cwd=self.home)))

    def test_query_points_at_a_better_note_outside_the_project(self):
        out = self.brain("query", "getaddrinfo note", cwd=self.repo)
        self.assertEqual(ranked(out)[0], DNS)
        self.assertEqual(outside(out), [OTHER_DNS])
        self.assertEqual(outside(self.brain("query", "getaddrinfo for mysql failed", cwd=self.repo)), [])

    def test_weak_match_is_flagged(self):
        out = self.brain("query", "worktree zebra giraffe llama", cwd=self.repo)
        self.assertIn("Weak matches", out)
        self.assertIn("(matched 1/4: worktree)", out)
        self.assertNotIn("Weak matches", self.brain("query", "git worktree", cwd=self.repo))


class ContextTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        vault = self.make_vault()
        (self.home / "brain").symlink_to(vault)
        self.repo = self.home / "code" / "shop"
        self.repo.mkdir(parents=True)
        notes = "".join(f"- [[Note number {i}]]: a line about note {i}.\n" for i in range(400))
        (vault / "Projects" / "Shop" / "Preferences").mkdir(parents=True)
        (vault / "Projects" / "Shop" / "Shop.md").write_text(
            f"---\ntype: project\npaths: [{self.repo}]\n---\n# Shop\n\nAn online shop.\n\n## Notes\n{notes}")
        (vault / "Projects" / "Shop" / "Preferences" / "Use pnpm.md").write_text(note("Use pnpm", "Always pnpm."))
        (vault / "Global" / "Preferences").mkdir(parents=True)
        (vault / "Global" / "Preferences" / "No worktrees unless asked.md").write_text(
            note("No worktrees unless asked", "Don't create worktrees.", projects="[]"))

    def test_long_hub_keeps_preferences(self):
        out = self.brain("context", str(self.repo))
        self.assertIn("An online shop.", out)
        self.assertIn("[[Use pnpm]]", out)
        self.assertIn("[[No worktrees unless asked]]", out)
        self.assertLessEqual(len(out), 8100)


if __name__ == "__main__":
    unittest.main()
