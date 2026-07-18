from pathlib import Path


def make_unique_copy_filename(original_name: str, existing_names: set[str] | list[str]) -> str:
    """
    Build a Windows Explorer-like copy name.
    Example: a.png -> a - Copy.png -> a - Copy (2).png
    """
    existing = set(existing_names)
    path = Path(original_name)
    stem = path.stem
    suffix = path.suffix

    candidate = f"{stem} - Copy{suffix}"
    if candidate not in existing:
        return candidate

    n = 2
    while True:
        candidate = f"{stem} - Copy ({n}){suffix}"
        if candidate not in existing:
            return candidate
        n += 1
