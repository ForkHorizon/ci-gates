# GitHub Actions workflows: every job runs on the self-hosted Mac, never on a GitHub-hosted runner.
YAML_RULES = [
    (
        "no-hosted-runner",
        r"^[^#]*\b(?:ubuntu|macos|windows)-(?:latest|\d[\w.]*)\b",
        "GitHub-hosted runner: use runs-on: [self-hosted, macOS, ARM64, ci-scope]",
    ),
    (
        "no-pull-request-target",
        r"^[^#]*\bpull_request_target\b",
        "pull_request_target runs pull-request code with secrets",
    ),
]
