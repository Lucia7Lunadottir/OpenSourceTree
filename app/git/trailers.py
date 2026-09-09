import re

_CO_AUTHOR_RE = re.compile(r"^Co-authored-by:\s*(.+?)\s*<([^<>]+)>\s*$", re.IGNORECASE)


def parse_co_authors(message: str) -> list[tuple[str, str]]:
    """Return [(name, email), ...] for each Co-authored-by trailer in message."""
    result = []
    for line in message.splitlines():
        m = _CO_AUTHOR_RE.match(line.strip())
        if m:
            result.append((m.group(1).strip(), m.group(2).strip()))
    return result


def add_co_author(message: str, name: str, email: str) -> str:
    """Append a Co-authored-by trailer, skipping if that email is already present."""
    if any(e.lower() == email.lower() for _, e in parse_co_authors(message)):
        return message
    trailer = f"Co-authored-by: {name} <{email}>"
    stripped = message.rstrip("\n")
    if not stripped:
        return trailer
    last_line = stripped.splitlines()[-1].strip()
    sep = "\n" if _CO_AUTHOR_RE.match(last_line) else "\n\n"
    return f"{stripped}{sep}{trailer}"


def remove_co_author(message: str, email: str) -> str:
    """Remove the Co-authored-by trailer matching email (case-insensitive)."""
    kept = []
    for line in message.splitlines():
        m = _CO_AUTHOR_RE.match(line.strip())
        if m and m.group(2).strip().lower() == email.lower():
            continue
        kept.append(line)
    while kept and kept[-1].strip() == "":
        kept.pop()
    return "\n".join(kept)
