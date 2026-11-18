import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.git.remote_attach import EmptyRepoAdvisor, EmptyRepoState, RemoteHistoryAttacher
from app.git.repo import GitRepo

_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, env=_ENV,
                          capture_output=True, text=True).stdout


class EmptyRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _remote_with_initial_commit(self) -> Path:
        seed = self.root / "seed"
        seed.mkdir()
        _git(seed, "init", "-q", "-b", "main")
        (seed / ".gitignore").write_text("*.log\n")
        (seed / "README.md").write_text("hello\n")
        _git(seed, "add", ".")
        _git(seed, "commit", "-q", "-m", "Initial commit")
        bare = self.root / "remote.git"
        _git(self.root, "clone", "-q", "--bare", str(seed), str(bare))
        return bare

    def _new_repo(self) -> GitRepo:
        folder = self.root / "work"
        folder.mkdir()
        return GitRepo.init(str(folder), "main")

    def test_init_makes_an_unborn_repository_on_the_chosen_branch(self):
        repo = self._new_repo()
        self.assertTrue(repo.is_unborn())
        self.assertEqual(repo.get_head(), "main")
        self.assertEqual([b.name for b in repo.get_branches()], ["main"])

    def test_states_follow_the_remote(self):
        repo = self._new_repo()
        advisor = EmptyRepoAdvisor(repo)
        self.assertIs(advisor.state(), EmptyRepoState.NO_REMOTE)

        empty = self.root / "empty.git"
        _git(self.root, "init", "-q", "--bare", str(empty))
        repo.add_remote("origin", str(empty))
        self.assertIs(advisor.state(), EmptyRepoState.NEEDS_FETCH)
        repo.fetch("origin")
        self.assertIs(advisor.state(fetched=True), EmptyRepoState.REMOTE_EMPTY)

        repo.set_remote_url("origin", str(self._remote_with_initial_commit()))
        repo.fetch("origin")
        self.assertIs(advisor.state(), EmptyRepoState.REMOTE_HAS_HISTORY)
        self.assertEqual(advisor.remote_branch(), "origin/main")

    def test_a_repository_with_commits_needs_no_advice(self):
        repo = self._new_repo()
        (Path(repo.path) / "a.txt").write_text("a")
        _git(repo.path, "add", ".")
        _git(repo.path, "commit", "-q", "-m", "first")
        self.assertIsNone(EmptyRepoAdvisor(repo).state())

    def test_attach_keeps_the_users_files_and_staging_and_restores_missing_ones(self):
        repo = self._new_repo()
        work = Path(repo.path)
        (work / ".gitignore").write_text("mine\n")     # exists on the remote too, differs
        (work / "game.cs").write_text("code")
        _git(work, "add", ".gitignore", "game.cs")
        repo.add_remote("origin", str(self._remote_with_initial_commit()))
        repo.fetch("origin")

        branch = RemoteHistoryAttacher(repo).attach("origin/main")

        self.assertEqual(branch, "main")
        self.assertFalse(repo.is_unborn())
        self.assertEqual((work / ".gitignore").read_text(), "mine\n")     # not overwritten
        self.assertEqual((work / "README.md").read_text(), "hello\n")     # restored
        status = _git(work, "status", "--porcelain").splitlines()
        self.assertIn("A  game.cs", status)
        self.assertIn("M  .gitignore", status)
        self.assertFalse([l for l in status if l.startswith("D") or l.startswith(" D")])
        self.assertEqual(_git(work, "rev-parse", "--abbrev-ref", "main@{u}").strip(), "origin/main")


if __name__ == "__main__":
    unittest.main()
