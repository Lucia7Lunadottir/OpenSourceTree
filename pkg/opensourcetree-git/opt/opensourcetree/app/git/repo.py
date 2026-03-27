import os
from typing import Optional, Iterator
from .runner import GitRunner, GitCommandError
from .models import (
    CommitRecord, FileStatusEntry, BranchInfo, TagInfo,
    StashInfo, RemoteInfo, LfsFileEntry
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

    def set_remote_url(self, name: str, url: str) -> None:
        self.runner.run(["remote", "set-url", name, url])

    def add_remote(self, name: str, url: str) -> None:
        self.runner.run(["remote", "add", name, url])

    def remove_remote(self, name: str) -> None:
        self.runner.run(["remote", "remove", name])

    def rename_remote(self, old: str, new: str) -> None:
        self.runner.run(["remote", "rename", old, new])

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

    def push_tag(self, name: str, remote: str = "origin") -> None:
        self.runner.run(["push", remote, f"refs/tags/{name}"])

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

    # --------------------------------------------------------- Conflict resolution

    def get_conflicted_files(self) -> list[str]:
        """Return paths of all files with merge conflicts."""
        raw = self.runner.run(["status", "--porcelain=v1", "-u"])
        paths = []
        for line in raw.splitlines():
            if len(line) < 4:
                continue
            xy = line[:2]
            path = line[3:]
            if "U" in xy or xy in ("AA", "DD"):
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                paths.append(path.strip('"'))
        return paths

    def conflict_content(self, path: str) -> str:
        """Read a conflicted file from the working tree."""
        full = os.path.join(self.path, path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""

    def resolve_ours(self, path: str) -> None:
        self.runner.run(["checkout", "--ours", "--", path])
        self.runner.run(["add", "--", path])

    def resolve_theirs(self, path: str) -> None:
        self.runner.run(["checkout", "--theirs", "--", path])
        self.runner.run(["add", "--", path])

    def mark_resolved(self, path: str) -> None:
        self.runner.run(["add", "--", path])

    def is_merging(self) -> bool:
        try:
            self.runner.run(["rev-parse", "MERGE_HEAD"])
            return True
        except GitCommandError:
            return False

    def is_rebasing(self) -> bool:
        try:
            git_dir = self.runner.run(["rev-parse", "--git-dir"]).strip()
            if not os.path.isabs(git_dir):
                git_dir = os.path.join(self.path, git_dir)
            return (os.path.isdir(os.path.join(git_dir, "rebase-merge")) or
                    os.path.isdir(os.path.join(git_dir, "rebase-apply")))
        except Exception:
            return False

    def is_cherry_picking(self) -> bool:
        try:
            self.runner.run(["rev-parse", "CHERRY_PICK_HEAD"])
            return True
        except GitCommandError:
            return False

    def abort_merge(self) -> None:
        self.runner.run(["merge", "--abort"])

    def abort_rebase(self) -> None:
        self.runner.run(["rebase", "--abort"])

    def abort_cherry_pick(self) -> None:
        self.runner.run(["cherry-pick", "--abort"])

    def get_last_commit_message(self) -> str:
        """Return full commit message (subject + body) of HEAD."""
        try:
            return self.runner.run(["log", "-1", "--format=%B"]).strip()
        except GitCommandError:
            return ""

    def get_repo_name(self) -> str:
        return os.path.basename(self.path)

    @staticmethod
    def is_git_repo(path: str) -> bool:
        try:
            GitRunner(path).run(["rev-parse", "--git-dir"])
            return True
        except (GitCommandError, Exception):
            return False

    # ------------------------------------------------- Streaming remote ops

    def fetch_tags_silent(self) -> None:
        """Fetch tags from all remotes quietly (no output, ignores errors)."""
        try:
            self.runner.run(["fetch", "--tags", "--quiet"], timeout=15)
        except Exception:
            pass

    def fetch_streaming(self, remote: str = "", prune: bool = False, tags: bool = True) -> Iterator[str]:
        args = ["fetch", "--progress"]
        if prune:
            args.append("--prune")
        if tags:
            args.append("--tags")
        args.append(remote if remote else "--all")
        return self.runner.run_streaming(args)

    def pull_streaming(self, remote: str = "", branch: str = "", rebase: bool = False) -> Iterator[str]:
        args = ["pull", "--progress"]
        if rebase:
            args.append("--rebase")
        # If branch specified without a remote, git would treat branch name as remote name.
        # Use "origin" as the fallback so the argument order stays valid.
        effective_remote = remote or ("origin" if branch else "")
        if effective_remote:
            args.append(effective_remote)
        if branch:
            args.append(branch)
        return self.runner.run_streaming(args)

    def push_streaming(self, remote: str = "", branch: str = "", force: bool = False, tags: bool = False) -> Iterator[str]:
        args = ["push", "--progress"]
        if force:
            args.append("--force-with-lease")
        if tags:
            args.append("--tags")
        # If branch specified without a remote, git would treat branch name as remote name.
        # Use "origin" as the fallback so the argument order stays valid.
        effective_remote = remote or ("origin" if branch else "")
        if effective_remote:
            args.append(effective_remote)
        if branch:
            args.append(branch)
        return self.runner.run_streaming(args)

    # ------------------------------------------------------------------ LFS

    def lfs_is_enabled(self) -> bool:
        """Return True if git-lfs is installed and initialized in this repo."""
        import shutil
        if not shutil.which("git-lfs"):
            return False
        try:
            hooks_dir = self.runner.run(["rev-parse", "--git-path", "hooks"]).strip()
            hook_path = os.path.join(hooks_dir, "pre-push")
            # Also check if lfs is listed in the config
            self.runner.run(["lfs", "env"])
            return True
        except (GitCommandError, Exception):
            return False

    def lfs_list_files(self) -> list[LfsFileEntry]:
        """Parse `git lfs ls-files -s` output into LfsFileEntry list."""
        try:
            raw = self.runner.run(["lfs", "ls-files", "-s"])
        except GitCommandError:
            return []
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Format: <oid> <*|-> <path>
            # e.g. "abc123... * assets/logo.psd"
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            oid = parts[0]
            marker = parts[1]   # '*' = downloaded, '-' = pointer only
            path = parts[2]
            downloaded = marker == "*"
            # Size is not in ls-files -s; use 0 unless we can get it
            size = self._lfs_file_size(path)
            entries.append(LfsFileEntry(oid=oid, size=size, path=path, downloaded=downloaded))
        return entries

    def _lfs_file_size(self, path: str) -> int:
        """Return LFS object size from pointer file, or 0 on error."""
        try:
            full = os.path.join(self.path, path)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("size "):
                        return int(line.split()[1])
        except Exception:
            pass
        return 0

    def lfs_pull(self, paths: list[str] = []) -> Iterator[str]:
        args = ["lfs", "pull"]
        if paths:
            args += ["--"] + paths
        return self.runner.run_streaming(args)

    def lfs_fetch(self, remote: str = "", all_: bool = False) -> Iterator[str]:
        args = ["lfs", "fetch"]
        if all_:
            args.append("--all")
        if remote:
            args.append(remote)
        return self.runner.run_streaming(args)

    def lfs_push(self, remote: str = "origin") -> Iterator[str]:
        return self.runner.run_streaming(["lfs", "push", "--all", remote])

    def lfs_track(self, pattern: str) -> None:
        self.runner.run(["lfs", "track", pattern])

    def lfs_untrack(self, pattern: str) -> None:
        self.runner.run(["lfs", "untrack", pattern])

    def lfs_tracked_patterns(self) -> list[str]:
        """Parse .gitattributes for lines containing 'filter=lfs'."""
        attr_path = os.path.join(self.path, ".gitattributes")
        patterns = []
        try:
            with open(attr_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "filter=lfs" in line:
                        patterns.append(line.split()[0])
        except FileNotFoundError:
            pass
        return patterns

    def lfs_prune(self) -> str:
        try:
            return self.runner.run(["lfs", "prune"])
        except GitCommandError as e:
            return str(e)

    def lfs_status(self) -> str:
        try:
            return self.runner.run(["lfs", "status"])
        except GitCommandError as e:
            return str(e)
