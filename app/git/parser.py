from datetime import datetime, timezone
from .models import CommitRecord, FileStatusEntry, BranchInfo, TagInfo, StashInfo, RemoteInfo

# Record separator used between commits in git log output
RECORD_SEP = "\x1e"
FIELD_SEP = "\x00"

# git log format: hash\0short_hash\0parents\0author\0email\0isodate\0subject\0refs
LOG_FORMAT = "%H%x00%h%x00%P%x00%an%x00%ae%x00%aI%x00%s%x00%D"


def parse_commits(raw: str) -> list[CommitRecord]:
    records = []
    for block in raw.split(RECORD_SEP):
        block = block.strip()
        if not block:
            continue
        commit = _parse_commit_block(block)
        if commit:
            records.append(commit)
    return records


def _parse_commit_block(block: str) -> CommitRecord | None:
    parts = block.split(FIELD_SEP)
    if len(parts) < 8:
        return None
    hash_, short_hash, parents_str, author, email, date_str, subject, refs_str = parts[:8]
    parents = [p for p in parents_str.split() if p]
    refs = _parse_refs(refs_str)
    date = _parse_date(date_str)
    return CommitRecord(
        hash=hash_.strip(),
        short_hash=short_hash.strip(),
        parents=parents,
        author=author,
        author_email=email,
        date=date,
        message=subject,
        refs=refs,
    )


def _parse_refs(refs_str: str) -> list[str]:
    if not refs_str.strip():
        return []
    result = []
    for ref in refs_str.split(","):
        ref = ref.strip()
        if ref:
            result.append(ref)
    return result


def _parse_date(date_str: str) -> datetime:
    date_str = date_str.strip()
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        # ISO 8601 with timezone
        return datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.now(timezone.utc)


def parse_file_status(raw: str, staged: bool = False) -> list[FileStatusEntry]:
    entries = []
    for line in raw.splitlines():
        if not line:
            continue
        entry = _parse_status_line(line, staged)
        if entry:
            entries.append(entry)
    return entries


def _parse_status_line(line: str, staged: bool) -> FileStatusEntry | None:
    # git status --porcelain=v1 format: XY PATH or XY OLD -> NEW
    if len(line) < 3:
        return None
    xy = line[:2]
    path_part = line[3:]

    if staged:
        status_char = xy[0]
    else:
        status_char = xy[1]

    if status_char == " ":
        return None

    old_path = ""
    if " -> " in path_part:
        old_path, path = path_part.split(" -> ", 1)
    else:
        path = path_part

    # Strip quotes added by git for paths with spaces
    path = path.strip('"').strip("'")
    old_path = old_path.strip('"').strip("'")

    return FileStatusEntry(
        status=status_char,
        path=path,
        old_path=old_path,
        staged=staged,
    )


def parse_branches(raw: str) -> list[BranchInfo]:
    branches = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        branch = _parse_branch_line(line)
        if branch:
            branches.append(branch)
    return branches


def _parse_branch_line(line: str) -> BranchInfo | None:
    # git branch -vv --format output
    # Format: "%(HEAD) %(refname:short) %(objectname:short) %(upstream:short) %(upstream:track)"
    # We parse git branch -vv output:
    # * main  abc1234 [origin/main: ahead 1] commit msg
    #   feat  def5678 commit msg
    is_current = line.startswith("*")
    line = line.lstrip("* ").strip()

    parts = line.split(None, 2)
    if not parts:
        return None
    name = parts[0]
    commit_hash = parts[1] if len(parts) > 1 else ""

    is_remote = name.startswith("remotes/")
    remote = ""
    if is_remote:
        name = name[len("remotes/"):]
        remote = name.split("/")[0]

    tracking = ""
    ahead = 0
    behind = 0
    if len(parts) > 2:
        rest = parts[2]
        if rest.startswith("["):
            bracket_end = rest.find("]")
            if bracket_end > 0:
                tracking_info = rest[1:bracket_end]
                tracking_parts = tracking_info.split(":")
                tracking = tracking_parts[0].strip()
                if len(tracking_parts) > 1:
                    detail = tracking_parts[1].strip()
                    for token in detail.split(","):
                        token = token.strip()
                        if token.startswith("ahead"):
                            try:
                                ahead = int(token.split()[1])
                            except (IndexError, ValueError):
                                pass
                        elif token.startswith("behind"):
                            try:
                                behind = int(token.split()[1])
                            except (IndexError, ValueError):
                                pass

    return BranchInfo(
        name=name,
        is_current=is_current,
        is_remote=is_remote,
        remote=remote,
        tracking=tracking,
        ahead=ahead,
        behind=behind,
        commit_hash=commit_hash,
    )


def parse_tags(raw: str) -> list[TagInfo]:
    tags = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            tags.append(TagInfo(name=parts[1], commit_hash=parts[0]))
    return tags


def parse_stashes(raw: str) -> list[StashInfo]:
    stashes = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # format: index:stash@{N}: On branch: message
        parts = line.split(":", 3)
        if len(parts) < 3:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        name = f"stash@{{{index}}}"
        branch = ""
        message = parts[2].strip() if len(parts) > 2 else ""
        if message.lower().startswith("on "):
            branch_and_msg = message[3:].split(":", 1)
            branch = branch_and_msg[0].strip()
            message = branch_and_msg[1].strip() if len(branch_and_msg) > 1 else ""
        stashes.append(StashInfo(index=index, name=name, message=message, branch=branch))
    return stashes


def parse_remotes(raw: str) -> list[RemoteInfo]:
    remotes_dict: dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        name, url, rtype = parts[0], parts[1], parts[2].strip("()")
        if name not in remotes_dict:
            remotes_dict[name] = {"fetch_url": "", "push_url": ""}
        if rtype == "fetch":
            remotes_dict[name]["fetch_url"] = url
        elif rtype == "push":
            remotes_dict[name]["push_url"] = url
    return [RemoteInfo(name=n, **v) for n, v in remotes_dict.items()]
