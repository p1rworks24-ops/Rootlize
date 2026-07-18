def image_matches_search(file_name: str, tags: list[str], search_query: str) -> bool:
    """Return True if the image matches the search query (filename or tag)."""
    query = search_query.strip().lower()
    if not query:
        return True

    if query in file_name.lower():
        return True

    # Allow searching with or without a leading #
    query_plain = query.lstrip("#").strip()
    for tag in tags:
        tag_l = tag.lower()
        if query in tag_l or (query_plain and query_plain in tag_l):
            return True
        if query_plain and f"#{tag_l}".find(query) >= 0:
            return True
    return False
