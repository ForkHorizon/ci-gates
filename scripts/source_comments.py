def split_comments(lines: list[str], extension: str) -> tuple[list[str], list[str]]:
    code_lines, comments, block, quote, triple = [], [], False, "", False
    for line in lines:
        code, comment, i = [], [], 0
        while i < len(line):
            if block:
                end = line.find("*/", i)
                comment.append(line[i:] if end < 0 else line[i:end])
                i = len(line) if end < 0 else end + 2
                block = end < 0
            elif quote:
                delimiter = quote * (3 if triple else 1)
                if line[i] == "\\":
                    code.append(line[i : i + 2])
                    i += 2
                elif line.startswith(delimiter, i):
                    code.append(delimiter)
                    i += len(delimiter)
                    quote, triple = "", False
                else:
                    code.append(line[i])
                    i += 1
            elif line[i] in "'\"`":
                quote = line[i]
                triple = extension == ".py" and line.startswith(quote * 3, i)
                delimiter = quote * (3 if triple else 1)
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
