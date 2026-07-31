"""Agent-facing journal templates identify which agent created the entry."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestAgentTemplates(unittest.TestCase):
    def test_templates_identify_the_creating_agent(self):
        expected_agents = {
            "journal-recorder.md": "claude-code",
            "codex-skill/SKILL.md": "codex",
        }

        missing = []
        for relative_path, agent in expected_agents.items():
            template = (REPO_ROOT / relative_path).read_text()
            if f"agent: {agent}" not in template:
                missing.append(relative_path)

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
