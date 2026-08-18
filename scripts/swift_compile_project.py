from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from swift_compile_common import fail, require_path, stripped, trimmed_error
from swift_compile_model import SwiftProject


def ensure_developer_dir() -> None:
    if "DEVELOPER_DIR" in os.environ:
        return
    try:
        proc = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=False)
        selected = proc.stdout.strip()
        if selected and not selected.endswith("CommandLineTools"):
            return
    except Exception:
        pass
    for candidate in sorted(Path("/Applications").glob("Xcode*.app")):
        dev_dir = candidate / "Contents" / "Developer"
        if dev_dir.exists():
            os.environ["DEVELOPER_DIR"] = str(dev_dir)
            return


def xcode_project(
    root: Path,
    kind: str,
    project_path: str,
    scheme: str,
    settings: tuple[str, str],
) -> SwiftProject:
    flag = "-workspace" if kind == "xcode-workspace" else "-project"
    destination, configuration = settings
    return SwiftProject(
        kind,
        project_path,
        scheme or detect_scheme(root, flag, project_path),
        destination,
        configuration,
    )


def detect_project(root: Path, config: dict) -> SwiftProject:
    ensure_developer_dir()
    configuration = str(config.get("xcode_configuration") or "Debug")
    destination = str(config.get("xcode_destination") or "")
    scheme = stripped(config.get("xcode_scheme"))
    workspace = stripped(config.get("xcode_workspace"))
    project = stripped(config.get("xcode_project"))
    settings = destination, configuration

    if workspace:
        require_path(root / workspace, "xcode_workspace")
        return xcode_project(root, "xcode-workspace", workspace, scheme, settings)

    if project:
        require_path(root / project, "xcode_project")
        return xcode_project(root, "xcode-project", project, scheme, settings)

    workspaces = sorted(path for path in root.glob("*.xcworkspace") if path.is_dir())
    projects = sorted(path for path in root.glob("*.xcodeproj") if path.is_dir())

    if len(workspaces) == 1:
        relative = workspaces[0].relative_to(root).as_posix()
        return xcode_project(root, "xcode-workspace", relative, scheme, settings)
    if len(projects) == 1:
        relative = projects[0].relative_to(root).as_posix()
        return xcode_project(root, "xcode-project", relative, scheme, settings)
    if not workspaces and not projects and (root / "Package.swift").exists():
        return SwiftProject("spm")

    if len(workspaces) + len(projects) > 1:
        fail(
            "Multiple Xcode projects/workspaces found. Set xcode_workspace or xcode_project in .swift-compile-gate.json."
        )
    fail("No SwiftPM package or root Xcode project/workspace found.")


def detect_scheme(root: Path, flag: str, project_path: str) -> str:
    result = subprocess.run(
        ["xcodebuild", "-list", "-json", flag, project_path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(trimmed_error(result.stdout + result.stderr, f"Unable to inspect schemes for {project_path}."))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail(f"Unable to parse xcodebuild scheme list for {project_path}.")

    container_key = "workspace" if flag == "-workspace" else "project"
    schemes = payload.get(container_key, {}).get("schemes", [])
    if len(schemes) == 1:
        return str(schemes[0])
    if not schemes:
        fail(f"No shared schemes found for {project_path}. Set xcode_scheme in .swift-compile-gate.json.")
    fail(
        f"Multiple schemes found for {project_path}: {', '.join(map(str, schemes))}. Set xcode_scheme in .swift-compile-gate.json."
    )


def xcodebuild_base_command(project: SwiftProject, config: dict) -> list[str]:
    command = ["xcodebuild"]
    if project.kind == "xcode-workspace":
        command.extend(["-workspace", project.project_path or ""])
    else:
        command.extend(["-project", project.project_path or ""])
    command.extend(["-scheme", project.scheme or ""])
    if project.configuration:
        command.extend(["-configuration", project.configuration])
    if project.destination:
        command.extend(["-destination", project.destination])
    if not bool(config.get("xcode_code_signing_allowed", False)):
        command.append("CODE_SIGNING_ALLOWED=NO")
    return command
