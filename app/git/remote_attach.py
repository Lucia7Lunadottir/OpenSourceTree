"""Helping a repository that has no commits yet: what to do next, and joining
the history that already exists on its remote.

A fresh `git init` next to a remote that already holds a commit (GitHub's
"Initial commit" with README / .gitignore) is a trap: the first local commit
shares no history with it and the first push is rejected. Attaching the local
branch to the remote one *before* the first commit avoids that.
"""
import os
from enum import Enum

from .repo import GitRepo

_PATHS_PER_CALL = 200


class EmptyRepoState(Enum):
    NO_REMOTE = "no_remote"              # nothing to push to or pull from yet
    NEEDS_FETCH = "needs_fetch"          # a remote is set, but nothing was fetched from it
    REMOTE_HAS_HISTORY = "has_history"   # origin/<branch> exists: attach to it
    REMOTE_EMPTY = "remote_empty"        # fetched, the remote has no branches either


class EmptyRepoAdvisor:
    """Decides which advice an unborn repository needs."""

    def __init__(self, repo: GitRepo):
        self._repo = repo

    def state(self, fetched: bool = False) -> EmptyRepoState | None:
        """None when the repository already has commits (no advice needed)."""
        if not self._repo.is_unborn():
            return None
        remote = self.remote_name()
        if not remote:
            return EmptyRepoState.NO_REMOTE
        if self._repo.get_remote_branches(remote):
            return EmptyRepoState.REMOTE_HAS_HISTORY
        return EmptyRepoState.REMOTE_EMPTY if fetched else EmptyRepoState.NEEDS_FETCH

    def remote_name(self) -> str:
        names = [r.name for r in self._repo.get_remotes()]
        return "origin" if "origin" in names else (names[0] if names else "")

    def remote_branch(self) -> str:
        """The `remote/name` ref to attach to: the branch HEAD is already named
        after, else the remote's default branch, else main / master / the first."""
        remote = self.remote_name()
        refs = self._repo.get_remote_branches(remote) if remote else []
        if not refs:
            return ""
        own = f"{remote}/{self._repo.get_head()}"
        preferred = [own, f"{remote}/main", f"{remote}/master"]
        return next((r for r in preferred if r in refs), refs[0])


class RemoteHistoryAttacher:
    """Points the unborn local branch at a fetched remote branch and sets its upstream.

    Nothing in the working folder is overwritten: the index (what the user has
    already staged) is kept, and only files that the remote has and the folder
    lacks are restored.
    """

    def __init__(self, repo: GitRepo):
        self._repo = repo

    def attach(self, remote_ref: str) -> str:
        """Attach to `remote_ref` (`origin/main`); returns the local branch name."""
        branch = remote_ref.split("/", 1)[1]
        run = self._repo.runner.run
        run(["symbolic-ref", "HEAD", f"refs/heads/{branch}"])
        run(["reset", "--soft", remote_ref])
        self._keep_remote_files()
        run(["branch", f"--set-upstream-to={remote_ref}", branch])
        return branch

    def _keep_remote_files(self) -> None:
        # --soft leaves the index as it was, so every remote file the user has not
        # staged shows up as a staged deletion: bring those entries back, and the
        # files themselves where the folder lacks them.
        run = self._repo.runner.run
        raw = run(["diff", "--cached", "--name-only", "--diff-filter=D", "-z"])
        paths = [p for p in raw.split("\0") if p]
        for i in range(0, len(paths), _PATHS_PER_CALL):
            run(["reset", "-q", "--", *paths[i:i + _PATHS_PER_CALL]])
        missing = [p for p in paths if not os.path.lexists(os.path.join(self._repo.path, p))]
        for i in range(0, len(missing), _PATHS_PER_CALL):
            run(["checkout", "--", *missing[i:i + _PATHS_PER_CALL]])
