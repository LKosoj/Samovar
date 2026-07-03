def extract_function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise ValueError(f"function not found: {signature}")
    brace = source.find("{", start)
    if brace < 0:
        raise ValueError(f"function body not found: {signature}")
    depth = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    for index in range(brace, len(source)):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if in_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            continue
        if char == '"':
            in_string = True
            continue
        if char == "'":
            in_char = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise ValueError(f"function body is not closed: {signature}")


def strip_cpp_comments(source: str) -> str:
    result: list[str] = []
    index = 0
    in_string = False
    in_char = False
    escaped = False
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if in_char:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            index += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "'":
            in_char = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            while index < len(source) and source[index] != "\n":
                index += 1
            if index < len(source):
                result.append("\n")
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index < len(source) - 1 and not (source[index] == "*" and source[index + 1] == "/"):
                result.append("\n" if source[index] == "\n" else " ")
                index += 1
            index += 2 if index < len(source) else 0
            continue

        result.append(char)
        index += 1

    return "".join(result)


def extract_braced_block_after(source: str, token: str, offset: int = 0) -> tuple[str, int]:
    start = source.find(token, offset)
    if start < 0:
        raise ValueError(f"block token not found: {token}")
    brace = source.find("{", start)
    if brace < 0:
        raise ValueError(f"block opening brace not found: {token}")
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index], index + 1
    raise ValueError(f"block is not closed: {token}")


def require_ordered_tokens(name: str, body: str, tokens: list[str], errors: list[str]) -> None:
    offset = 0
    for token in tokens:
        index = body.find(token, offset)
        if index < 0:
            errors.append(f"{name} missing ordered token: {token}")
            return
        offset = index + len(token)
