import os
from typing import Optional
from .runner import GitRunner, GitCommandError
from .models import (
    CommitRecord, FileStatusEntry, BranchInfo, TagInfo,
    StashInfo, RemoteInfo
)
from .parser import (
    parse_commits, parse_file_status, parse_branches,
    parse_tags, parse_stashes, parse_remotes,
    LOG_FORMAT, RECORD_SEP
)
from .graph_layout import compute_graph_layout


class GitRepo:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.runner = GitRunner(self.path)
        self._validate()

    def _validate(self):
        self.runner.run(["rev-parse", "--git-dir"])

    # ------------------------------------------------------------------ Log

    def get_commits(
        self,
        skip: int = 0,
        limit: int = 200,
        branch: str = "",
        search: str = "",
    ) -> list[CommitRecord]:
        args = [
            "log",
            f"--format={LOG_FORMAT}{RECORD_SEP}",
            "--topo-order",
            f"--skip={skip}",
            f"--max-count={limit}",
        ]
        if search:
            args += ["--all-match", f"--grep={search}", f"--author={search}", "-i"]
            # Use a more flexible search
            args = [
                "log",
                f"--format={LOG_FORMAT}{RECORD_SEP}",
                "--topo-order",
                f"--skip={skip}",
                f"--max-count={limit}",
                f"--grep={search}",
                "-i",
            ]
        if branch:
            args.append(branch)
        raw = self.runner.run(args)
        commits = parse_commits(raw)
        return compute_graph_layout(commits)

    def get_commit_detail(self, hash: str) -> CommitRecord:
        fmt = "%H%x00%h%x00%P%x00%an%x00%ae%x00%aI%x00%s%x00%D%x00%b"
        raw = self.runner.run(["show", f"--format={fmt}", "--no-patch", hash])
        from .parser import _parse_commit_block, FIELD_SEP
        commit = _parse_commit_block(raw.strip())
        if commit:
            parts = raw.strip().split(FIELD_SEP)
            if len(parts) >= 9:
                commit.body = parts[8].strip()
        return commit

    def get_commit_files(self, hash: str) -> list[FileStatusEntry]:
        raw = self.runner.run([
            "diff-tree", "--no-commit-id", "-r", "--name-status", "--diff-filter=ACDMRT", hash
        ])
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]
                if len(parts) == 3:
                    entries.append(FileStatusEntry(status=status, path=parts[2], old_path=parts[1]))
                else:
                    entries.append(FileStatusEntry(status=status, path=parts[1]))
        return entries

    def get_diff(self, hash: str, file_path: str = "") -> str:
        args = ["show", "--format=", hash]
        if file_path:
            args += ["--", file_path]
        return self.runner.run(args)

    def get_working_copy_status(self) -> tuple[list[FileStatusEntry], list[FileStatusEntry]]:
        raw = self.runner.run(["status", "--porcelain=v1", "-u"])
        staged = []
        unstaged = []
        for line in raw.splitlines():
            if len(line) < 2:
                continue
            x, y = line[0], line[1]
            path_part = line[3:]
            old_path = ""
            if " -> " in path_part:
                old_path, path = path_part.split(" -> ", 1)
            else:
                path = path_part
            path = path.strip('"')
            old_path = old_path.strip('"')

            if x != " " and x != "?":
                staged.append(FileStatusEntry(status=x, path=path, old_path=old_path, staged=True))
            if y != " " and y != "?":
                unstaged.append(FileStatusEntry(status=y, path=path, old_path=old_path, staged=False))
            elif y == "?" and x == "?":
                unstaged.append(FileStatusEntry(status="?", path=path, staged=False))
        return staged, unstaged

    def get_working_copy_diff(self, path: str, staged: bool) -> str:
        if staged:
            return self.runner.run(["diff", "--cached", "--", path])
        else:
            return self.runner.run(["diff", "--", path])

    # --------------------------------------------------------------- Staging

    def stage_file(self, path: str) -> None:
        self.runner.run(["add", "--", path])

    def unstage_file(self, path: str) -> None:
        try:
            self.runner.run(["restore", "--staged", "--", path])
        except GitCommandError:
            self.runner.run(["reset", "HEAD", "--", path])

    def stage_all(self) -> None:
        self.runner.run(["add", "-A"])

    def unstage_all(self) -> None:
        try:
            self.runner.run(["restore", "--staged", "."])
        except GitCommandError:
            self.runner.run(["reset", "HEAD"])

    def stage_hunk(self, patch: str) -> None:
        self.runner.run(["apply", "--cached"], input=patch)

    def commit(self, message: str, amend: bool = False) -> str:
        args = ["commit", "-m", message]
        if amend:
            args.append("--amend")
        return self.runner.run(args)

    # -------------------------------------------------------------- Branches

    def get_branches(self) -> list[BranchInfo]:
        raw = self.runner.run(["branch", "-vv", "-a"])
        return parse_branches(raw)

    def checkout(self, name: str) -> None:
        self.runner.run(["checkout", name])

    def create_branch(self, name: str, from_ref: str = "HEAD") -> None:
        self.runner.run(["checkout", "-b", name, from_ref])

    def delete_branch(self, name: str, force: bool = False) -> None:
        flag = "-D" if force else "-d"
        self.runner.run(["branch", flag, name])

    def rename_branch(self, old: str, new: str) -> None:
        self.runner.run(["branch", "-m", old, new])

    def merge(self, branch: str, no_ff: bool = False, squash: bool = False) -> None:
        args = ["merge"]
        if no_ff:
            args.append("--no-ff")
        if squash:
            args.append("--squash")
        args.append(branch)
        self.runner.run(args, timeout=60)

    def rebase(self, branch: str) -> None:
        self.runner.run(["rebase", branch], timeout=60)

    # --------------------------------------------------------------- Remotes

    def get_remotes(self) -> list[RemoteInfo]:
        raw = self.runner.run(["remote", "-v"])
        return parse_remotes(raw)

    def fetch(self, remote: str = "", prune: bool = False) -> str:
        args = ["fetch"]
        if prune:
            args.append("--prune")
        if remote:
            args.append(remote)
        else:
            args.append("--all")
        return self.runner.run(args, timeout=120)

    def pull(self, remote: str = "", branch: str = "", rebase: bool = False) -> str:
        args = ["pull"]
        if rebase:
            args.append("--rebase")
        if remote:
            args.append(remote)
        if branch:
            args.append(branch)
        return self.runner.run(args, timeout=120)

    def push(
        self,
        remote: str = "",
        branch: str = "",
        force: bool = False,
        tags: bool = False,
    ) -> str:
        args = ["push"]
        if force:
            args.append("--force-with-lease")
        if tags:
            args.append("--tags")
        if remote:
            args.append(remote)
        if branch:
            args.append(branch)
        return self.runner.run(args, timeout=120)

    # ----------------------------------------------------------------- Stash

    def get_stashes(self) -> list[StashInfo]:
        raw = self.runner.run(["stash", "list"])
        return parse_stashes(raw)

    def stash_save(self, message: str = "", include_untracked: bool = True) -> None:
        args = ["stash", "push"]
        if include_untracked:
            args.append("-u")
        if message:
            args += ["-m", message]
        self.runner.run(args)

    def stash_pop(self, index: int = 0) -> None:
        self.runner.run(["stash", "pop", f"stash@{{{index}}}"])

    def stash_apply(self, index: int = 0) -> None:
        self.runner.run(["stash", "apply", f"stash@{{{index}}}"])

    def stash_drop(self, index: int = 0) -> None:
        self.runner.run(["stash", "drop", f"stash@{{{index}}}"])

    def stash_diff(self, index: int = 0) -> str:
        return self.runner.run(["stash", "show", "-p", f"stash@{{{index}}}"])

    # ------------------------------------------------------------------ Tags

    def get_tags(self) -> list[TagInfo]:
        raw = self.runner.run(["tag", "-l", "--format=%(objectname:short) %(refname:short)"])
        return parse_tags(raw)

    def create_tag(self, name: str, ref: str = "HEAD", message: str = "") -> None:
        if message:
            self.runner.run(["tag", "-a", name, ref, "-m", message])
        else:
            self.runner.run(["tag", name, ref])

    def delete_tag(self, name: str) -> None:
        self.runner.run(["tag", "-d", name])

    # ---------------------------------------------------------- Commit actions

    def reset_to_commit(self, hash: str, mode: str = "mixed") -> None:
        """Reset current branch HEAD to hash. mode: soft | mixed | hard."""
        self.runner.run(["reset", f"--{mode}", hash])

    def cherry_pick(self, hash: str) -> None:
        self.runner.run(["cherry-pick", hash])

    def revert_commit(self, hash: str) -> None:
        self.runner.run(["revert", "--no-edit", hash])

    def checkout_detached(self, hash: str) -> None:
        self.runner.run(["checkout", hash])

    # ---------------------------------------------------------- Git identity

    def get_identity(self, global_: bool = True) -> tuple[str, str]:
        """Return (user.name, user.email) from git config."""
        scope = ["--global"] if global_ else []
        def _get(key):
            try:
                return self.runner.run(["config"] + scope + [key]).strip()
            except GitCommandError:
                return ""
        return _get("user.name"), _get("user.email")

    def set_identity(self, name: str, email: str, global_: bool = True) -> None:
        scope = ["--global"] if global_ else []
        if name:
            self.runner.run(["config"] + scope + ["user.name", name])
        if email:
            self.runner.run(["config"] + scope + ["user.email", email])

    # ----------------------------------------------------------------- Utils

    def get_head(self) -> str:
        try:
            return self.runner.run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        except GitCommandError:
            return "HEAD"

    def is_clean(self) -> bool:
        raw = self.runner.run(["status", "--porcelain"])
        return not raw.strip()

    def get_repo_name(self) -> str:
        return os.path.basename(self.path)

    @staticmethod
    def is_git_repo(path: str) -> bool:
        try:
            GitRunner(path).run(["rev-parse", "--git-dir"])
            return True
        except (GitCommandError, Exception):
            return False
