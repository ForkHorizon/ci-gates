from pathlib import Path


CACHE_DIR = Path.home() / "Library/Caches/ci-gates"

DEFAULT_CONFIG = {
    "include_extensions": [
        ".py",
        ".swift",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".cs",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
    ],
    "exclude_paths": [
        "node_modules/",
        "dist/",
        "build/",
        ".build/",
        "vendor/",
        "Pods/",
        "Assets/Plugins/",
        "Assets/Libs/",
        "Assets/TextMesh Pro/",
    ],
    "categories": [
        "swallowed-error",
        "speculative-abstraction",
        "misleading-name",
        "noise-comment",
        "fake-test",
        "dead-end-code",
        "insecure-pattern",
    ],
    "max_findings": 8,
    "max_candidates": 15,
    "max_file_diff_lines": 400,
    "refute_votes": 3,
}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "problem": {"type": "string"},
                },
                "required": ["line", "category", "severity", "problem"],
            },
        }
    },
    "required": ["findings"],
}

REFUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_real": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["is_real", "reason"],
}

FIND_PROMPT = """You are a strict senior reviewer looking ONLY for AI-generated "slop"
in the added lines of this diff. Report at most {max} of the MOST serious issues.

Flag only these categories: {categories}
Definitions:
- swallowed-error: an exception/error caught and ignored, logged-and-continued, or a
  success value returned when the operation actually failed.
- speculative-abstraction: an interface/factory/config/wrapper with a single use that
  adds no behavior; indirection for its own sake (YAGNI).
- misleading-name: a name that claims behavior the code does not perform.
- noise-comment: a comment that only restates what the next line already says.
- fake-test: a test that asserts a mock/constant, or exercises nothing real.
- dead-end-code: unreachable branches, unused "just in case" parameters, no-op paths.
- insecure-pattern: secret literals, or SQL/shell/HTML built by string concatenation.

Rules:
- Consider ONLY lines marked with '+'. Report the exact shown line number.
- Do NOT report style, formatting, or anything a linter already catches.
- If nothing qualifies, return an empty list. Be conservative; precision over recall.

File: {path}
```
{diff}
```"""

REFUTE_PROMPT = """A first reviewer flagged the issue below. You are a second, skeptical
reviewer. Decide whether it is a REAL problem worth showing the author.

Set is_real=true if a competent engineer would agree the flagged code is a genuine
instance of the category. Set is_real=false ONLY if the claim is factually wrong,
purely stylistic/nitpicky, or a clear false positive.

Judge the code exactly as shown. For security, assume external inputs may be untrusted
(string-built SQL/shell IS injectable regardless of the caller). But REJECT findings that
depend on hypothetical misuse not present in the diff ("if this were ever logged",
"if called wrongly"), normal control flow described as a bug (an early-return guard is not
a swallowed error), errors that are propagated via `throws`/`throw`/`return err`, and
intentional defaults (`?? ""`) unless the masking is clearly harmful.

Category: {category}
Claim (line {line}): {problem}

File: {path}
```
{diff}
```"""

__all__ = [
    "CACHE_DIR",
    "DEFAULT_CONFIG",
    "FIND_PROMPT",
    "FIND_SCHEMA",
    "REFUTE_PROMPT",
    "REFUTE_SCHEMA",
    "SEVERITY_RANK",
]
