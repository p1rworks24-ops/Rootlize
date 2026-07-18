def make_unique_name(name: str, existing: list[str] | set[str]) -> str:
    """
    Return a unique name like Windows folders:
    test -> test (1) -> test (2) when duplicates exist.
    """
    existing_set = set(existing)
    if name not in existing_set:
        return name

    n = 1
    while True:
        candidate = f"{name} ({n})"
        if candidate not in existing_set:
            return candidate
        n += 1
