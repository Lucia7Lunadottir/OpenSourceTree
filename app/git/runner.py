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
    for t in ("konsole", "xterm", "alacritty", "kitty", "foot"):
        found = shutil.which(t)
        if found:
            return found
    return ""


class GitRunner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _base_cmd(self, args: list[str]) -> list[str]:
        return ["git", "-C", self.repo_path, "-c", "core.quotePath=false"] + args

    def _build_env(self) -> dict:
        from app.config import get_git_ssh_command, get_askpass_path
        env = os.environ.copy()
        # Fail fast on auth prompts — we detect and retry in terminal instead
        env["GIT_TERMINAL_PROMPT"] = "0"
        ssh_cmd = get_git_ssh_command()
        if ssh_cmd:
            env["GIT_SSH_COMMAND"] = ssh_cmd
        askpass = get_askpass_path()
        if askpass:
            env["GIT_ASKPASS"] = askpass
            env["SSH_ASKPASS"] = askpass
        return env

    def run(self, args: list[str], input: Optional[str] = None, timeout: int = 30) -> str:
        cmd = self._base_cmd(args)
        env = self._build_env()
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
        env = self._build_env()
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            raise GitCommandError(cmd, -1, "Command timed out")
        if result.returncode != 0:
            raise GitCommandError(
                cmd, result.returncode,
                result.stderr.decode("utf-8", errors="replace"),
            )
        return result.stdout

    def run_streaming(self, args: list[str]) -> Iterator[str]:
        import re
        cmd = self._base_cmd(args)
        env = self._build_env()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        collected: list[str] = []
        buf = ""
        try:
            while True:
                chunk = proc.stdout.read(512)
                if not chunk:
                    if buf.strip():
                        collected.append(buf)
                        yield buf
                    break
                buf += chunk
                # Split on \r or \n so git's \r-based progress lines are emitted promptly
                parts = re.split(r"[\r\n]", buf)
                for line in parts[:-1]:
                    if line.strip():
                        collected.append(line)
                        yield line
                buf = parts[-1]
        finally:
            proc.stdout.close()
            proc.wait()
        if proc.returncode != 0:
            raise GitCommandError(cmd, proc.returncode, "\n".join(collected))

    def run_in_terminal(self, args: list[str]) -> None:
        """Open a terminal window and run the git command interactively."""
        terminal = find_terminal()
        if not terminal:
            raise GitCommandError(args, -1, "Не найден эмулятор терминала (konsole, xterm)")

        cmd_parts = self._base_cmd(args)
        shell_cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        script = f'{shell_cmd}; echo ""; echo "──── Нажмите Enter чтобы закрыть ────"; read _'

        term_name = os.path.basename(terminal)
        if term_name == "konsole":
            proc = subprocess.Popen(
                [terminal, "--hide-menubar", "--hide-tabbar", "-e", "bash", "-c", script]
            )
        elif term_name in ("alacritty", "kitty", "foot"):
            proc = subprocess.Popen([terminal, "-e", "bash", "-c", script])
        else:
            proc = subprocess.Popen([terminal, "-e", f"bash -c {shlex.quote(script)}"])
        proc.wait()
