# ci-gates

Reusable GitHub Actions quality gates for all ForkHorizon projects. The gate
logic lives here once; each project only carries a thin caller workflow, so
pushing to `main` in this repo updates every project instantly.

## Gates

| Workflow | What it checks |
|---|---|
| `readability.yml` | File length ≤ 300 lines, function length ≤ 50 lines (12+ languages). |
| `swift-compile.yml` | Project compiles; fails on critical warnings (Swift 6 concurrency, Sendable, data races). |
| `swift-quality.yml` | Build, `swift-format lint --strict`, dead code via Periphery. |

All jobs target self-hosted macOS ARM64 runners; the extra label is
configurable via the `runner-label` input.

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
  readability:
    uses: ForkHorizon/ci-gates/.github/workflows/readability.yml@main

  swift-compile:
    uses: ForkHorizon/ci-gates/.github/workflows/swift-compile.yml@main

  swift-quality:
    uses: ForkHorizon/ci-gates/.github/workflows/swift-quality.yml@main
    with:
      run-build: false   # compile gate already builds
```

Per-repo tuning stays in the project via config files:
`.linter-checker-300-lines.json`, `.swift-compile-gate.json`,
`.swift-quality-gate.json`. See each script's `DEFAULT_CONFIG` in
[scripts/](scripts/) for the available keys.

## Inputs

Common to all workflows:

- `runner-label` — extra runner label (`ci-scope` for readability, `ci-scope-broker` for Swift gates by default).
- `config` — path to the gate's JSON config in the calling repo.
- `gates-ref` — which ref of this repo to fetch scripts from (default `main`).

`readability.yml` and `swift-quality.yml` also take `mode`
(`auto`/`all`/`changed`; `auto` scans changed files on `pull_request` and
`merge_group`, everything otherwise). `swift-quality.yml` takes `run-build`
to skip its build stage when the compile gate already builds the project.

## Versioning

Projects reference `@main`, so a push here rolls out everywhere at once. If a
rollout misbehaves, revert the commit. For a breaking change in gate behavior,
cut a tag and migrate callers deliberately.
