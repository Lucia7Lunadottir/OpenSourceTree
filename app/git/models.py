from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LaneData:
    node_lane: int
    active_lanes: list[int]
    connections_in: list[tuple[int, int]]   # (from_lane, to_lane)
    connections_out: list[tuple[int, int]]  # (from_lane, to_lane)


@dataclass
class CommitRecord:
    hash: str
    short_hash: str
    parents: list[str]
    author: str
    author_email: str
    date: datetime
    message: str
    body: str = ""
    refs: list[str] = field(default_factory=list)
    lane: int = -1
    lane_data: Optional[LaneData] = None


@dataclass
class FileStatusEntry:
    status: str          # single character: M, A, D, R, C, ?, !, U, T
    path: str
    old_path: str = ""   # for renames/copies
    staged: bool = False


@dataclass
class BranchInfo:
    name: str
    is_current: bool
    is_remote: bool
    remote: str = ""
    tracking: str = ""    # upstream branch
    ahead: int = 0
    behind: int = 0
    commit_hash: str = ""


@dataclass
class TagInfo:
    name: str
    commit_hash: str
    message: str = ""     # for annotated tags
    is_annotated: bool = False


@dataclass
class StashInfo:
    index: int
    name: str             # e.g. "stash@{0}"
    message: str
    branch: str = ""
    date: Optional[datetime] = None


@dataclass
class RemoteInfo:
    name: str
    fetch_url: str
    push_url: str = ""


@dataclass
class LfsFileEntry:
    oid: str          # SHA256 hash
    size: int         # bytes
    path: str
    downloaded: bool  # True if full file, False if pointer only
