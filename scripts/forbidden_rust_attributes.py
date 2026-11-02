"""Joins Rust attributes written over several lines so the one-line suppression rules still see them."""

MAX_ATTRIBUTE_LINES = 20


def join_attributes(
    lines: list[str], code_lines: list[str], comments: list[str], selected: set[int]
) -> tuple[list[str], list[str], set[int]]:
    """Return lines/comments where each multi-line `#[...]` sits on its first line, and the selection moved there."""
    joined, joined_comments, moved = list(lines), list(comments), set(selected)
    index = 0
    while index < len(code_lines):
        start = _attribute_start(code_lines[index])
        depth = _depth(code_lines[index][start:]) if start >= 0 else 0
        if depth <= 0:
            index += 1
            continue
        end = index
        while depth > 0 and end + 1 < len(code_lines) and end - index < MAX_ATTRIBUTE_LINES:
            end += 1
            depth += _depth(code_lines[end])
        joined[index] = " ".join(code_lines[row].strip() for row in range(index, end + 1))
        joined_comments[index] = " ".join(comments[row] for row in range(index, end + 1))
        if any(row + 1 in selected for row in range(index, end + 1)):
            moved.add(index + 1)
        index = end + 1
    return joined, joined_comments, moved


def _attribute_start(code: str) -> int:
    for token in ("#![", "#["):
        position = code.find(token)
        if position >= 0:
            return position
    return -1


def _depth(code: str) -> int:
    return code.count("[") - code.count("]")
