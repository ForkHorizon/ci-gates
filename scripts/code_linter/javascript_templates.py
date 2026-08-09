from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TemplateContext:
    in_interpolation: bool = False
    brace_depth: int = 0


def consume_template_text(
    line: str,
    index: int,
    templates: list[TemplateContext],
) -> int:
    context = templates[-1]
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
        elif line.startswith("${", index):
            context.in_interpolation = True
            context.brace_depth = 1
            return index + 2
        elif char == "`":
            templates.pop()
            return index + 1
        else:
            index += 1
    return index


def consume_template_brace(char: str, context: TemplateContext) -> bool:
    if char == "{":
        context.brace_depth += 1
        return True
    if context.brace_depth == 1:
        context.in_interpolation = False
        context.brace_depth = 0
        return False
    context.brace_depth -= 1
    return True
