"""Проверка сравнения версий и ссылок обратной связи."""

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tropa import APP_VERSION, REPO_URL  # noqa: E402
from tropa.updates import bug_url, idea_url, is_newer, parse_version, release_page  # noqa: E402


class UpdateTests(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(parse_version("v1.10.2"), (1, 10, 2))
        self.assertTrue(is_newer("1.10.0", "1.9.9"))
        self.assertFalse(is_newer("1.1.0", "1.1.0"))
        self.assertFalse(is_newer("garbage", "1.0.0"))

    def test_feedback_links(self):
        idea = urlsplit(idea_url())
        self.assertTrue(idea_url().startswith(REPO_URL + "/issues/new?"))
        self.assertEqual(parse_qs(idea.query), {"template": ["idea.yml"], "version": [APP_VERSION]})
        bug = parse_qs(urlsplit(bug_url("26.10.21")).query)
        self.assertEqual(bug["template"], ["bug.yml"])
        self.assertEqual(bug["core"], ["26.10.21"])
        self.assertIn("os", bug)
        self.assertEqual(release_page("1.2.0"), REPO_URL + "/releases/tag/v1.2.0")


if __name__ == "__main__":
    unittest.main()
