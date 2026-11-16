import os
import unittest
from unittest.mock import patch

from app.launch_args import repositories_from_arguments


class LaunchArgumentsTests(unittest.TestCase):
    def test_folders_are_made_absolute_from_where_the_user_started(self):
        with patch.dict(os.environ, OPENSOURCETREE_CWD="/home/pony/work"):
            self.assertEqual(repositories_from_arguments(["game", "/srv/repo", "~/x"]),
                             ["/home/pony/work/game", "/srv/repo", os.path.expanduser("~/x")])

    def test_options_are_not_folders(self):
        self.assertEqual(repositories_from_arguments(["--verbose", "", "repo"], start="/a"), ["/a/repo"])


if __name__ == "__main__":
    unittest.main()
