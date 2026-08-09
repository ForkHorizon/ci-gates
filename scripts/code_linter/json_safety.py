from __future__ import annotations


# Keep this below the recursion budget of Python 3.11 while remaining generous
# for ordinary JSON documents and consistent with runtimes that parse JSON
# iteratively, such as Python 3.14.
MAX_JSON_DEPTH = 900


def exceeds_json_depth(text: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return True
        elif char in "]}" and depth:
            depth -= 1
    return False
