import json
import os
from pathlib import Path

CONFIG_DIR    = Path.home() / ".config" / "OpenSourceTree"
BOOKMARKS_FILE = CONFIG_DIR / "bookmarks.json"
SSH_CONFIG_FILE = CONFIG_DIR / "ssh.json"


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ── Bookmarks ────────────────────────────────────────────────────────────

def load_bookmarks() -> list[str]:
    if not BOOKMARKS_FILE.exists():
        return []
    try:
        with open(BOOKMARKS_FILE) as f:
            data = json.load(f)
        return [p for p in data if os.path.isdir(p)]
    except (json.JSONDecodeError, KeyError):
        return []


def save_bookmarks(paths: list[str]) -> None:
    _ensure_config_dir()
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(paths, f, indent=2)


def add_bookmark(path: str) -> list[str]:
    bookmarks = load_bookmarks()
    if path not in bookmarks:
        bookmarks.append(path)
        save_bookmarks(bookmarks)
    return bookmarks


def remove_bookmark(path: str) -> list[str]:
    bookmarks = load_bookmarks()
    if path in bookmarks:
        bookmarks.remove(path)
        save_bookmarks(bookmarks)
    return bookmarks


# ── SSH Config ───────────────────────────────────────────────────────────

_SSH_DEFAULTS = {
    "key_path": "",               # path to private key file
    "use_agent": True,            # use ssh-agent if available
    "strict_host_checking": "accept-new",  # yes / no / accept-new
    "extra_options": "",          # raw -o options string
}


def load_ssh_config() -> dict:
    if not SSH_CONFIG_FILE.exists():
        return dict(_SSH_DEFAULTS)
    try:
        with open(SSH_CONFIG_FILE) as f:
            data = json.load(f)
        return {**_SSH_DEFAULTS, **data}
    except (json.JSONDecodeError, KeyError):
        return dict(_SSH_DEFAULTS)


def save_ssh_config(cfg: dict) -> None:
    _ensure_config_dir()
    with open(SSH_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def build_git_ssh_command(cfg: dict | None = None) -> str:
    """Build the GIT_SSH_COMMAND value from current SSH config."""
    if cfg is None:
        cfg = load_ssh_config()
    parts = ["ssh"]
    if cfg.get("key_path"):
        import shlex
        parts += ["-i", shlex.quote(str(cfg["key_path"]))]
    strict = cfg.get("strict_host_checking", "accept-new")
    parts += ["-o", f"StrictHostKeyChecking={strict}"]
    if not cfg.get("use_agent", True):
        parts += ["-o", "IdentitiesOnly=yes"]
    extra = cfg.get("extra_options", "").strip()
    if extra:
        for opt in extra.split():
            parts += ["-o", opt]
    return " ".join(parts)
