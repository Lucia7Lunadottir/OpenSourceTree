import numpy as np
from .models import CommitRecord, LaneData

MAX_LANES = 32


def compute_graph_layout(commits: list[CommitRecord]) -> list[CommitRecord]:
    """
    Assign lanes to commits and compute LaneData for drawing the graph.
    Input: commits in topological order (newest first).
    Returns the same list with .lane and .lane_data populated.
    """
    if not commits:
        return commits

    # Map hash -> index in commits list
    hash_to_idx: dict[str, int] = {c.hash: i for i, c in enumerate(commits)}

    # lane_occupied[i] = True if lane i is currently in use
    lane_occupied = np.zeros(MAX_LANES, dtype=bool)

    # lane_commit[lane] = hash of the commit expected to arrive on that lane
    # (i.e., the child commit currently "occupying" that lane)
    lane_commit: dict[int, str] = {}

    # For each commit: what lane does it appear on
    commit_lane: dict[str, int] = {}

    # Active lanes at each row (lanes with ongoing lines)
    # active_lanes[i] = list of lanes that have lines passing through row i
    all_active: list[list[int]] = []

    # connections: for each commit row, store (from_lane, to_lane) pairs
    all_conn_in: list[list[tuple[int, int]]] = []
    all_conn_out: list[list[tuple[int, int]]] = []

    def find_free_lane() -> int:
        free = np.argmin(lane_occupied)
        if lane_occupied[free]:
            # All lanes occupied (unlikely with MAX_LANES=32), use last+1
            return int(np.sum(lane_occupied))
        return int(free)

    def release_lane(lane: int):
        if lane < MAX_LANES:
            lane_occupied[lane] = False
        if lane in lane_commit:
            del lane_commit[lane]

    # Current set of "open" lanes: lanes waiting for a parent
    # open_lanes[hash] = lane that expects this hash as a parent
    open_lanes: dict[str, int] = {}

    for i, commit in enumerate(commits):
        h = commit.hash

        # Determine this commit's lane
        if h in open_lanes:
            my_lane = open_lanes[h]
        else:
            my_lane = find_free_lane()
            if my_lane < MAX_LANES:
                lane_occupied[my_lane] = True

        commit_lane[h] = my_lane
        commit.lane = my_lane

        # Remove this commit from open_lanes
        if h in open_lanes:
            del open_lanes[h]

        # Compute connections_in: lines coming from above into this node
        conn_in: list[tuple[int, int]] = []
        for lane, expected_hash in list(lane_commit.items()):
            if expected_hash == h:
                if lane != my_lane:
                    conn_in.append((lane, my_lane))
                # release this lane if it was just for this commit
                # but only if it's not the main lane
                if lane != my_lane:
                    release_lane(lane)

        all_conn_in.append(conn_in)

        # Assign lanes to parents
        conn_out: list[tuple[int, int]] = []
        first_parent = True
        for parent_hash in commit.parents:
            if parent_hash not in hash_to_idx:
                # Parent not in our commit list (truncated log)
                continue
            if first_parent:
                # First parent continues on same lane
                parent_lane = my_lane
                first_parent = False
            else:
                # Additional parents get new lanes
                if parent_hash in open_lanes:
                    parent_lane = open_lanes[parent_hash]
                else:
                    parent_lane = find_free_lane()
                    if parent_lane < MAX_LANES:
                        lane_occupied[parent_lane] = True

            if parent_hash not in open_lanes:
                open_lanes[parent_hash] = parent_lane
                if parent_lane < MAX_LANES:
                    lane_commit[parent_lane] = parent_hash

            if parent_lane != my_lane:
                conn_out.append((my_lane, parent_lane))

        all_conn_out.append(conn_out)

        # Record lane_commit for this lane (first parent)
        if commit.parents and commit.parents[0] in hash_to_idx:
            if my_lane < MAX_LANES:
                lane_commit[my_lane] = commit.parents[0]
        else:
            # No parent or parent not in view: release this lane
            release_lane(my_lane)

        # Snapshot active lanes at this row
        active = sorted(open_lanes.values())
        if my_lane not in active:
            active.append(my_lane)
        active = sorted(set(active))
        all_active.append(active)

    # Attach LaneData to each commit
    for i, commit in enumerate(commits):
        commit.lane_data = LaneData(
            node_lane=commit.lane,
            active_lanes=all_active[i],
            connections_in=all_conn_in[i],
            connections_out=all_conn_out[i],
        )

    return commits
