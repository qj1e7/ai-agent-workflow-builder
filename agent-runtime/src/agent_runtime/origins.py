import httpx

type Origin = tuple[str, str, int | None]


def origin_of(url: str) -> Origin | None:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return None
    if not parsed.scheme or not parsed.host or parsed.userinfo:
        return None
    return (parsed.scheme, parsed.host, parsed.port)


def parse_origin_list(raw: str) -> frozenset[Origin]:
    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]
    if not entries:
        raise ValueError("no origin given")
    origins: set[Origin] = set()
    for entry in entries:
        origin = origin_of(entry)
        if origin is None or origin[0] not in {"http", "https"}:
            raise ValueError(f"{entry!r} is not an http or https origin")
        if httpx.URL(entry).raw_path != b"/" or "?" in entry or "#" in entry:
            raise ValueError(f"{entry!r} must be an origin only, with no path, query or fragment")
        origins.add(origin)
    return frozenset(origins)
