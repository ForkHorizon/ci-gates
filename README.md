# ci-gates

Reusable GitHub Actions quality gates for all ForkHorizon projects. The gate
logic lives here once; each project only carries a thin caller workflow, so
pushing to `main` in this repo updates every project instantly.

## Gates

| Workflow | What it checks |
|---|---|
| `code-linter.yml` | Dependency-free structure checks for 21 mapped language/config families plus `.gitignore`: file ≤ 300 lines, function ≤ 50 lines, control-flow nesting ≤ 4, parameters ≤ 5, prose comment block ≤ 5 lines, doc-comment block ≤ 50 lines, top-level types per file ≤ 2, plus syntax and lexical block-balance checks. YAML and `.gitignore` receive syntax-only policy checks; YAML mappings also reject duplicate keys. Blank lines inside a comment run do not reset its limit; recognized SPDX/license headers have a bounded allowance of 30 lines under the default policy. |
| `swift-compile.yml` | Project compiles; fails on critical warnings (Swift 6 concurrency, Sendable, data races). |
| `swift-quality.yml` | Build, `swift-format lint --strict`, dead code via Periphery. |
| `web-quality.yml` | TS/JS: `tsc --noEmit`, ESLint (if the repo has a config), dead code + unused deps via knip, copy-paste via jscpd. |
| `python-quality.yml` | Ruff lint (strict fallback config in `configs/ruff-strict.toml`) and `ruff format --check`. |
| `go-quality.yml` | `go vet`, `gofmt -l` (fails on unformatted files), `golangci-lint run`. Does not run `go test` — test execution stays with the project's own CI. |
| `unity-quality.yml` | Unity C#: `dotnet build` with Microsoft.Unity.Analyzers (fails on first-party warnings), jscpd for C#. Uses a persistent per-repo workspace cache under `~/Library/Caches/ci-gates` — no project checkout, incremental fetch + Library reuse. |
| `slop-review.yml` | **Advisory, non-blocking.** Sends each changed file's diff to a local Ollama model to flag semantic AI-slop that linters miss (swallowed errors, fake tests, misleading names, insecure string-built queries, dead-end code), with a 3-vote adversarial refutation pass. Posts `::warning` annotations + a job-summary table and a calibration journal; never affects the merge decision. |

All jobs target self-hosted macOS ARM64 runners by default; the full label
set is configurable via the `runs-on` input (a JSON array).

## Usage

Add a caller workflow to the project:

```yaml
# .github/workflows/quality.yml
name: Quality

on:
  pull_request:
  merge_group:
    types: [checks_requested]

permissions:
  contents: read

jobs:
  code-linter:
    uses: ForkHorizon/ci-gates/.github/workflows/code-linter.yml@main

  swift-compile:
    uses: ForkHorizon/ci-gates/.github/workflows/swift-compile.yml@main

  swift-quality:
    uses: ForkHorizon/ci-gates/.github/workflows/swift-quality.yml@main
    with:
      run-build: false   # compile gate already builds
```

Per-repo tuning stays in the project via config files:
`.code-linter.json`, `.swift-compile-gate.json`,
`.swift-quality-gate.json`. See each script's `DEFAULT_CONFIG` in
[scripts/](scripts/) for the available keys.

The Code Linter uses `.code-linter.json` by default and fails if that file is
missing. Its config is strictly validated. Unsupported
extensions, unknown keys, empty extension lists, non-positive limits, and
malformed language overrides fail the job. Limits are bounded and blanket
source ignores such as `*.py` are rejected. Changing the config or a caller
workflow forces an all-files structure scan. The gate does not replace a
compiler, type checker, security scanner, or tests; use the language-specific
quality workflows alongside it.

Coverage gaps are accounted for separately. The default `coverage_mode` is
`report`: tracked files in ignored source directories, excluded supported
extensions, and recognized unsupported code/config surfaces are listed as
GitHub warnings instead of disappearing silently. Set `"coverage_mode":
"strict"` to fail on any unapproved gap. Intentional exclusions for surfaces
that still need a dedicated analyzer must be documented with a pattern and
reason, for example:

```json
{
  "coverage_mode": "strict",
  "coverage_exceptions": [
    {
      "pattern": "vendor/",
      "reason": "third-party dependency mirrored from upstream"
    },
    {
      "pattern": ".github/workflows/",
      "reason": "validated by actionlint in the workflow gate"
    }
  ]
}
```

The coverage inventory recognizes common C/C++, Objective-C, Dart, Scala,
shell, SQL, build, web, serialization, and workflow/configuration surfaces.
C/C++, Objective-C, Dart, Scala, and Groovy/Gradle now use the existing
brace-based structural checks; JSON and TOML use standard-library syntax
parsers, Bash-compatible shell files use native `bash -n` plus structural
checks, and YAML workflows/configuration use dependency-free lexical checks.
`.gitignore` receives policy-pattern checks. Other recognized surfaces remain
explicit gaps, and unknown UTF-8 text files are reported too; binary files and
clearly documentary files such as Markdown are excluded from that inventory.
Strict mode never approves an ignored or excluded extension that already has
structural support; this prevents a self-declared generated/vendor exception
from hiding handwritten code. Such files must be scanned or removed from the
policy gap before release.

Function detection is dependency-free and best-effort lexical analysis, not a
full parser for every supported language. Keep language-specific quality gates
enabled when complete grammar coverage is required.

This repository also checks itself on every pull request, merge-queue run, and
push to `main`. The self-check executes the scripts from the exact revision
being reviewed, runs the full unit-test suite, applies the default Code Linter
policy, checks Ruff lint/format, and validates all workflow files. The public
`scripts/code-linter.py` entry point remains stable; its implementation is split
across the small modules in `scripts/code_linter/`.

## Inputs

Common to all workflows:

- `runs-on` — JSON array of runner labels, e.g. `'["self-hosted", "macOS", "ARM64", "ci-scope-heavy"]'` (defaults end in `ci-scope` for the Code Linter, `ci-scope-broker` for Swift gates).
- `config` — path to the gate's JSON config in the calling repo; the Code
  Linter defaults to `.code-linter.json`.
- `coverage-mode` — optional `report` or `strict` override; when omitted, the
  repository config's `coverage_mode` is used.
- `gates-ref` — which ref of this repo to fetch scripts from where supported.
  The Code Linter deliberately always fetches `main`.

- `explain-model` — Ollama model used by the failure explainer (default `qwen3-coder:30b-a3b-q4_K_M`); set to `''` to disable.

When a gate fails, `scripts/explain-failure.py` sends the log tail and diff
summary to the local Ollama on the runner and writes a "Why this failed"
analysis to the job summary. Advisory only — it never changes the gate
verdict, and it silently skips if Ollama is unreachable.

`code-linter.yml` and `swift-quality.yml` also take `mode`
(`auto`/`all`/`changed`; `auto` scans changed files on `pull_request` and
`merge_group`, everything otherwise). `swift-quality.yml` takes `run-build`
to skip its build stage when the compile gate already builds the project.
`web-quality.yml`, `python-quality.yml`, and `go-quality.yml` take
`working-directory`; `web-quality.yml` also takes `duplication-threshold`
(max % of duplicated code, default 2). `go-quality.yml` also takes
`bootstrap-command`, an optional shell command run before vet/lint —
e.g. to satisfy a `go:embed` target that needs at least one file present
on a fresh checkout.

## Versioning

Projects reference `@main`, so a push here rolls out everywhere at once. If a
rollout misbehaves, revert the commit. For a breaking change in gate behavior,
cut a tag and migrate callers deliberately.
