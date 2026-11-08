"""Agent-facing text speaks of "the user", never a name."""
import json
import unittest

from helpers import BrainTestCase


class WordingTest(BrainTestCase):
    def setUp(self):
        super().setUp()
        (self.home / "brain").symlink_to(self.make_vault())

    def test_context_names_no_one(self):
        out = self.brain("context", str(self.home))
        self.assertIn("shared by all of the user's coding agents", out)
        self.assertIn("pushed when it has a remote", out)

    def test_stop_reason_names_no_one(self):
        transcript = self.home / "t.jsonl"
        transcript.write_text(json.dumps({"message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x"}}]}}) + "\n")
        r = self.run_brain("stop-check", input=json.dumps({"session_id": "s1", "transcript_path": str(transcript)}))
        self.assertIn("a correction or preference from the user", json.loads(r.stdout)["reason"])


if __name__ == "__main__":
    unittest.main()
