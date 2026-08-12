"""Agent-facing journal templates identify which agent created the entry."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestAgentTemplates(unittest.TestCase):
    def test_single_agent_template_names_its_own_agent(self):
        template = (REPO_ROOT / "journal-recorder.md").read_text()
        self.assertIn("agent: claude-code", template)

    def test_shared_skill_lets_the_running_agent_name_itself(self):
        """The skill is installed for every agent, so it must not claim to be one."""
        template = (REPO_ROOT / "codex-skill/SKILL.md").read_text()

        self.assertIn("agent: [which agent you are:", template)
        self.assertNotIn("agent: codex\n", template)


if __name__ == "__main__":
    unittest.main()
