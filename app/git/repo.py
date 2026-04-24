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
        else:
            # Show all branches including remote tracking refs so fetched changes are visible
            args.append("--all")
        raw = self.runner.run(args)
        commits = parse_commits(raw)
        return compute_graph_layout(commits)

    def get_archive_sha256(self, hash: str) -> str:
        """Return sha256 hex digest of a tar.gz archive of the given commit.
        Useful for AUR sha256sums=() entries."""
        import hashlib
        data = self.runner.run_bytes(["archive", "--format=tar.gz", hash], timeout=120)
        return hashlib.sha256(data).hexdigest()

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

    def _is_root_commit(self, sha: str) -> bool:
        try:
            self.runner.run(["rev-parse", "--verify", f"{sha}^"])
            return False
        except GitCommandError:
            return True

    def get_commit_files(self, hash: str) -> list[FileStatusEntry]:
        root_flag = ["--root"] if self._is_root_commit(hash) else []
        raw = self.runner.run(
            ["diff-tree", "--no-commit-id", "-r", "--name-status", "--diff-filter=ACDMRT"]
            + root_flag + [hash]
        )
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

    def delete_remote_tag(self, name: str, remote: str = "origin") -> None:
        self.runner.run(["push", remote, "--delete", f"refs/tags/{name}"])

    def push_tag(self, name: str, remote: str = "origin") -> None:
        self.runner.run(["push", remote, f"refs/tags/{name}"])

    def push_tag_streaming(self, name: str, remote: str = "origin") -> Iterator[str]:
        return self.runner.run_streaming(["push", "--progress", remote, f"refs/tags/{name}"])

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

    def get_merge_msg(self) -> str:
        try:
            git_dir = self.runner.run(["rev-parse", "--git-dir"]).strip()
            if not os.path.isabs(git_dir):
                git_dir = os.path.join(self.path, git_dir)
            msg_file = os.path.join(git_dir, "MERGE_MSG")
            if os.path.exists(msg_file):
                return open(msg_file, encoding="utf-8", errors="replace").read().strip()
        except Exception:
            pass
        return ""

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

    def rebase_continue(self) -> None:
        self.runner.run(["rebase", "--continue"], timeout=60)

    def abort_cherry_pick(self) -> None:
        self.runner.run(["cherry-pick", "--abort"])

    def cherry_pick_continue(self) -> None:
        self.runner.run(["cherry-pick", "--continue"], timeout=60)

    def get_last_commit_message(self) -> str:
        """Return full commit message (subject + body) of HEAD."""
        try:
            return self.runner.run(["log", "-1", "--format=%B"]).strip()
        except GitCommandError:
            return ""

    def get_repo_name(self) -> str:
        return os.path.basename(self.path)

    def cleanup_repo(self) -> dict:
        """Kill stale git processes and remove .lock files.

        Returns a dict with keys:
          'locks_removed'  – list of removed file names (relative to .git/)
          'pids_killed'    – list of killed PIDs (int)
          'errors'         – list of error strings encountered
        """
        import glob as _glob
        import signal
        import subprocess as _sp

        result: dict = {"locks_removed": [], "pids_killed": [], "errors": []}

        # ── 1. Kill stale git processes ──────────────────────────────────────
        try:
            out = _sp.run(
                ["pgrep", "-a", "-x", "git"],
                capture_output=True, text=True,
            )
            for line in out.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                pid_str, cmdline = parts
                # Only kill processes that reference this repo path
                if self.path not in cmdline:
                    continue
                try:
                    pid = int(pid_str)
                    os.kill(pid, signal.SIGTERM)
                    result["pids_killed"].append(pid)
                except (ValueError, ProcessLookupError, PermissionError) as e:
                    result["errors"].append(f"kill {pid_str}: {e}")
        except FileNotFoundError:
            # pgrep not available – try /proc
            try:
                for entry in os.listdir("/proc"):
                    if not entry.isdigit():
                        continue
                    try:
                        cmdline_path = f"/proc/{entry}/cmdline"
                        with open(cmdline_path, "rb") as f:
                            cmdline = f.read().replace(b"\x00", b" ").decode(errors="replace")
                        if "git" in cmdline and self.path in cmdline:
                            pid = int(entry)
                            os.kill(pid, signal.SIGTERM)
                            result["pids_killed"].append(pid)
                    except (OSError, ValueError):
                        pass
            except OSError as e:
                result["errors"].append(f"proc scan: {e}")

        # ── 2. Remove .lock files ────────────────────────────────────────────
        git_dir_raw = ""
        try:
            git_dir_raw = self.runner.run(["rev-parse", "--git-dir"]).strip()
        except GitCommandError:
            pass
        git_dir = os.path.join(self.path, git_dir_raw) if git_dir_raw else os.path.join(self.path, ".git")

        for lock_path in _glob.glob(os.path.join(git_dir, "**", "*.lock"), recursive=True):
            try:
                os.remove(lock_path)
                result["locks_removed"].append(os.path.relpath(lock_path, git_dir))
            except OSError as e:
                result["errors"].append(f"rm {os.path.basename(lock_path)}: {e}")

        return result

    @staticmethod
    def is_git_repo(path: str) -> bool:
        try:
            GitRunner(path).run(["rev-parse", "--git-dir"])
            return True
        except (GitCommandError, Exception):
            return False

    # -------------------------------------------------------- Unpushed / sizes

    def get_unpushed_commits(self) -> list[str]:
        """Return list of full SHAs of commits not yet pushed to upstream."""
        try:
            raw = self.runner.run(["log", "@{u}..HEAD", "--format=%H"])
        except GitCommandError:
            # No upstream configured — fall back to all commits not on any remote
            try:
                raw = self.runner.run(["log", "--not", "--remotes", "--format=%H"])
            except GitCommandError:
                return []
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def is_commit_pushed(self, sha: str) -> bool:
        """Return True if sha is reachable from any remote-tracking branch."""
        try:
            raw = self.runner.run(["branch", "-r", "--contains", sha])
            return bool(raw.strip())
        except GitCommandError:
            return False  # uncertain → allow split

    def get_commit_file_sizes(self, sha: str) -> list[tuple[str, int]]:
        """Return list of (path, size_bytes) for all files in a commit, sorted by size desc."""
        try:
            root_flag = ["--root"] if self._is_root_commit(sha) else []
            raw = self.runner.run(
                ["diff-tree", "--no-commit-id", "-r", "--name-only"] + root_flag + [sha]
            )
        except GitCommandError:
            return []
        lfs_paths = self._get_lfs_tracked_paths(sha)
        results = []
        for path in raw.splitlines():
            path = path.strip()
            if not path:
                continue
            size = self._resolve_file_size(sha, path, lfs_paths)
            results.append((path, size))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    _LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"

    def _get_lfs_tracked_paths(self, sha: str) -> set[str]:
        """Return set of paths stored in LFS for this commit (via .gitattributes filter=lfs)."""
        try:
            raw = self.runner.run(["lfs", "ls-files", "--name-only", sha])
            return {line.strip() for line in raw.splitlines() if line.strip()}
        except GitCommandError:
            return set()

    def _resolve_file_size(self, sha: str, path: str, lfs_paths: set[str]) -> int:
        """Return real file size. For LFS files, parses the pointer; otherwise uses blob size."""
        if path in lfs_paths:
            try:
                pointer = self.runner.run_bytes(["cat-file", "blob", f"{sha}:{path}"])
                for line in pointer.split(b"\n"):
                    if line.startswith(b"size "):
                        try:
                            return int(line[5:].strip())
                        except ValueError:
                            break
            except GitCommandError:
                pass
            return 0
        try:
            size_str = self.runner.run(["cat-file", "-s", f"{sha}:{path}"]).strip()
            return int(size_str)
        except (GitCommandError, ValueError):
            return 0

    def get_staged_file_sizes(self) -> list[tuple[str, int]]:
        """Return list of (path, size_bytes) for files with staged changes only.

        Uses diff-index against HEAD so only files that actually differ from the
        last commit are counted. Falls back to ls-files for the initial commit
        (no HEAD yet).
        """
        try:
            # Files that differ from HEAD — these are the actual staged changes
            raw = self.runner.run(["diff-index", "--cached", "HEAD", "--name-only"])
        except GitCommandError:
            # No HEAD yet (initial commit) — every staged file is new
            try:
                raw = self.runner.run(["ls-files", "--cached"])
            except GitCommandError:
                return []
        results = []
        for path in raw.splitlines():
            path = path.strip()
            if not path:
                continue
            try:
                # ":path" resolves to the staged blob
                size_str = self.runner.run(["cat-file", "-s", f":{path}"]).strip()
                size = int(size_str)
            except (GitCommandError, ValueError):
                size = 0  # Deleted files or errors → treat as 0
            results.append((path, size))
        return results

    def split_commit(self, sha: str, batches: list[list[str]], message: str) -> None:
        """Split a commit into multiple commits, one per batch."""
        _T = 1800  # 30-minute timeout for large staging/commit operations
        n = len(batches)
        # Resolve HEAD sha for comparison
        head_sha = self.runner.run(["rev-parse", "HEAD"]).strip()
        is_head = (sha == head_sha or sha.startswith(head_sha) or head_sha.startswith(sha))

        if is_head:
            if self._is_root_commit(sha):
                # Root commit has no parent — delete the branch ref to get an unborn branch,
                # then recreate history from scratch (working tree stays intact).
                self.runner.run(["rm", "-r", "--cached", "."], timeout=_T)
                self.runner.run(["update-ref", "-d", "HEAD"])
            else:
                self.runner.run(["reset", "--mixed", "HEAD~"], timeout=_T)
            for i, batch in enumerate(batches, 1):
                self.runner.run(["add", "--"] + batch, timeout=_T)
                self.runner.run(["commit", "-m", f"{message} ({i}/{n})"], timeout=_T)
        else:
            # Collect commits after sha
            after_raw = self.runner.run(
                ["log", f"{sha}..HEAD", "--format=%H", "--reverse"]
            )
            after_shas = [s.strip() for s in after_raw.splitlines() if s.strip()]
            # Reset to parent of sha
            self.runner.run(["reset", "--hard", f"{sha}^"], timeout=_T)
            # Cherry-pick sha without committing
            self.runner.run(["cherry-pick", "--no-commit", sha], timeout=_T)
            # Unstage everything (keep in worktree)
            self.runner.run(["reset", "HEAD", "--"], timeout=_T)
            for i, batch in enumerate(batches, 1):
                self.runner.run(["add", "--"] + batch, timeout=_T)
                self.runner.run(["commit", "-m", f"{message} ({i}/{n})"], timeout=_T)
            for after_sha in after_shas:
                self.runner.run(["cherry-pick", after_sha], timeout=_T)

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
