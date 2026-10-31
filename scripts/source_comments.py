def split_comments(lines: list[str], extension: str) -> tuple[list[str], list[str]]:
    code_lines, comments, block_depth, quote, triple, raw_hashes, regex_hashes = [], [], 0, "", False, 0, 0
    for line in lines:
        code, comment, i = [], [], 0
        while i < len(line):
            if regex_hashes or block_depth:
                piece, i, block_depth, regex_hashes, is_comment = _comment_part(
                    line, i, extension, block_depth, regex_hashes
                )
                (comment if is_comment else code).append(piece)
            elif quote:
                piece, i, quote, triple, raw_hashes = _quoted_part(line, i, quote, triple, raw_hashes)
                code.append(piece)
            elif line[i] in "'\"`":
                quote, triple, raw_hashes, delimiter = _string_start(line, i, extension)
                code.append(delimiter)
                i += len(delimiter)
            elif extension == ".swift" and line[i] == "#":
                regex_hashes, token, i = _raw_regex_start(line, i)
                code.append(token)
            elif line.startswith("/*", i):
                block_depth, i = 1, i + 2
            elif line.startswith("//", i) or (extension == ".py" and line[i] == "#"):
                comment.append(line[i:])
                break
            else:
                code.append(line[i])
                i += 1
        code_lines.append("".join(code))
        comments.append("".join(comment))
    return code_lines, comments


def _string_start(line: str, index: int, extension: str) -> tuple[str, bool, int, str]:
    quote = line[index]
    triple = extension in (".py", ".swift") and line.startswith(quote * 3, index)
    raw_hashes = 0
    if extension == ".swift":
        j = index - 1
        while j >= 0 and line[j] == "#":
            raw_hashes += 1
            j -= 1
    return quote, triple, raw_hashes, quote * (3 if triple else 1)


def _quoted_part(line: str, index: int, quote: str, triple: bool, raw_hashes: int) -> tuple[str, int, str, bool, int]:
    delimiter = quote * (3 if triple else 1)
    close = delimiter + "#" * raw_hashes
    if line[index] == "\\" and not raw_hashes:
        return line[index : index + 2], index + 2, quote, triple, raw_hashes
    escape = "\\" + close
    if raw_hashes and line.startswith(escape, index):
        return escape, index + len(escape), quote, triple, raw_hashes
    if line.startswith(close, index):
        return close, index + len(close), "", False, 0
    return line[index], index + 1, quote, triple, raw_hashes


def _raw_regex_start(line: str, index: int) -> tuple[int, str, int]:
    end = index
    while end < len(line) and line[end] == "#":
        end += 1
    if end > index and end < len(line) and line[end] == "/":
        return end - index, line[index : end + 1], end + 1
    return 0, line[index], index + 1


def _regex_part(line: str, index: int, raw_hashes: int) -> tuple[str, int, int]:
    close = "/" + "#" * raw_hashes
    escaped = "\\" + close
    if line.startswith(escaped, index):
        return escaped, index + len(escaped), raw_hashes
    if line.startswith(close, index):
        return close, index + len(close), 0
    return line[index], index + 1, raw_hashes


def _comment_part(
    line: str, index: int, extension: str, block_depth: int, regex_hashes: int
) -> tuple[str, int, int, int, bool]:
    if regex_hashes:
        piece, index, regex_hashes = _regex_part(line, index, regex_hashes)
        return piece, index, block_depth, regex_hashes, False
    if extension == ".swift" and line.startswith("/*", index):
        return "/*", index + 2, block_depth + 1, 0, True
    if line.startswith("*/", index):
        return "*/", index + 2, block_depth - 1, 0, True
    return line[index], index + 1, block_depth, 0, True
