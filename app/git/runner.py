import os
import shlex
import shutil
import subprocess
from typing import Iterator, Optional


class GitCommandError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str, stdout: str = ""):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(f"git {' '.join(cmd[1:])} failed (exit {returncode}): {stderr}")


# Patterns that indicate an interactive auth prompt is needed
_AUTH_PATTERNS = (
    "authentication failed",
    "permission denied",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "enter passphrase",
    "bad credentials",
    "repository not found",
    "403",
    "401",
)


def is_auth_error(stderr: str) -> bool:
    lower = stderr.lower()
    return any(p in lower for p in _AUTH_PATTERNS)


def find_terminal() -> str:
    """Return path to preferred terminal emulator."""
    for t in ("konsole", "xterm", "alacritty", "kitty", "foot"):
        found = shutil.which(t)
        if found:
            return found
    return ""


class GitRunner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _base_cmd(self, args: list[str]) -> list[str]:
        return ["git", "-C", self.repo_path] + args

    def _ssh_env(self) -> dict:
        """Build env dict with GIT_SSH_COMMAND if SSH key is configured."""
        from app.config import load_ssh_config, build_git_ssh_command
        cfg = load_ssh_config()
        env = os.environ.copy()
        # Disable interactive terminal prompts so auth failures are caught fast
        env["GIT_TERMINAL_PROMPT"] = "0"
        ssh_cmd = build_git_ssh_command(cfg)
        # Only override GIT_SSH_COMMAND if we have a key or extra config
        if cfg.get("key_path") or cfg.get("extra_options"):
            env["GIT_SSH_COMMAND"] = ssh_cmd
        return env

    def run(
        self,
        args: list[str],
        input: Optional[str] = None,
        timeout: int = 30,
    ) -> str:
        cmd = self._base_cmd(args)
        env = self._ssh_env()
        try:
            result = subprocess.run(
                cmd,
                input=input,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise GitCommandError(cmd, -1, "Command timed out")
        except FileNotFoundError:
            raise GitCommandError(cmd, -1, "git not found in PATH")

        if result.returncode != 0:
            raise GitCommandError(cmd, result.returncode, result.stderr, result.stdout)
        return result.stdout

    def run_bytes(self, args: list[str], timeout: int = 30) -> bytes:
        cmd = self._base_cmd(args)
        env = self._ssh_env()
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            raise GitCommandError(cmd, -1, "Command timed out")
        if result.returncode != 0:
            raise GitCommandError(
                cmd, result.returncode,
                result.stderr.decode("utf-8", errors="replace"),
            )
        return result.stdout

    def run_streaming(self, args: list[str]) -> Iterator[str]:
        cmd = self._base_cmd(args)
        env = self._ssh_env()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        try:
            for line in proc.stdout:
                yield line
        finally:
            proc.stdout.close()
            proc.wait()

    def run_in_terminal(self, args: list[str]) -> None:
        """
        Run a git command interactively in a terminal window.
        Blocks until the terminal window is closed.
        Used when auth prompts (SSH passphrase, HTTPS password) are needed.
        """
        terminal = find_terminal()
        if not terminal:
            raise GitCommandError(args, -1, "No terminal emulator found (tried konsole, xterm)")

        cmd_parts = self._base_cmd(args)
        shell_cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        # Keep terminal open until user presses Enter so they can read any output
        script = f'{shell_cmd}; echo ""; echo "──── Нажмите Enter чтобы закрыть ────"; read _'

        term_name = os.path.basename(terminal)
        if term_name == "konsole":
            proc = subprocess.Popen([terminal, "--hide-menubar", "--hide-tabbar", "-e", "bash", "-c", script])
        elif term_name in ("alacritty", "kitty", "foot"):
            proc = subprocess.Popen([terminal, "-e", "bash", "-c", script])
        else:  # xterm and everything else
            proc = subprocess.Popen([terminal, "-e", f"bash -c {shlex.quote(script)}"])

        proc.wait()
