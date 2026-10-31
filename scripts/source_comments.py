def split_comments(lines: list[str], extension: str) -> tuple[list[str], list[str]]:
    code_lines, comments, block, quote, triple, raw_hashes = [], [], False, "", False, 0
    for line in lines:
        code, comment, i = [], [], 0
        while i < len(line):
            if block:
                end = line.find("*/", i)
                comment.append(line[i:] if end < 0 else line[i:end])
                i = len(line) if end < 0 else end + 2
                block = end < 0
            elif quote:
                piece, i, quote, triple, raw_hashes = _quoted_part(line, i, quote, triple, raw_hashes)
                code.append(piece)
            elif line[i] in "'\"`":
                quote, triple, raw_hashes, delimiter = _string_start(line, i, extension)
                code.append(delimiter)
                i += len(delimiter)
            elif line.startswith("/*", i):
                block, i = True, i + 2
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
    if line.startswith(close, index):
        return close, index + len(close), "", False, 0
    return line[index], index + 1, quote, triple, raw_hashes
