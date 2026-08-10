from __future__ import annotations


def order_javascript_results(
    results: list[tuple[str, int, int, int]],
    positions: list[tuple[int, int]],
) -> None:
    groups: dict[int, list[int]] = {}
    for index, (line, _) in enumerate(positions):
        groups.setdefault(line, []).append(index)
    for indices in groups.values():
        ordered = sorted(indices, key=lambda index: positions[index][1])
        values = [results[index] for index in ordered]
        ordered_positions = [positions[index] for index in ordered]
        if len({len(indices), len(values), len(ordered_positions)}) != 1:
            raise ValueError("JavaScript result ordering metadata is inconsistent")
        for offset in range(len(indices)):
            index = indices[offset]
            results[index] = values[offset]
            positions[index] = ordered_positions[offset]
