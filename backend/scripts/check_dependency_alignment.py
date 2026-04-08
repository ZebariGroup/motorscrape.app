#!/usr/bin/env python3
"""Validate backend dependency parity between requirements.txt and pyproject.toml."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+(?:\[[^\]]+\])?\s*(?:[<>=!~]=?.+)?)\s*$")
_PKG_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def _normalize_pkg_key(spec: str) -> str:
    match = _PKG_RE.match(spec)
    if not match:
        return spec.strip().lower()
    return match.group(1).strip().lower().replace("_", "-")


def _normalize_spec(spec: str) -> str:
    return re.sub(r"\s+", "", spec.strip())


def _load_requirements(path: Path) -> dict[str, str]:
    deps: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQ_LINE_RE.match(line)
        if not match:
            continue
        spec = _normalize_spec(match.group(1))
        deps[_normalize_pkg_key(spec)] = spec
    return deps


def _load_pyproject_dependencies(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    deps_raw = project.get("dependencies") or []
    deps: dict[str, str] = {}
    for entry in deps_raw:
        if not isinstance(entry, str):
            continue
        spec = _normalize_spec(entry)
        deps[_normalize_pkg_key(spec)] = spec
    return deps


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    requirements_path = root / "requirements.txt"
    pyproject_path = root / "pyproject.toml"

    req_deps = _load_requirements(requirements_path)
    pyproject_deps = _load_pyproject_dependencies(pyproject_path)

    missing_in_pyproject = sorted(set(req_deps) - set(pyproject_deps))
    missing_in_requirements = sorted(set(pyproject_deps) - set(req_deps))
    version_mismatches = sorted(
        key for key in (set(req_deps) & set(pyproject_deps)) if req_deps[key] != pyproject_deps[key]
    )

    if not missing_in_pyproject and not missing_in_requirements and not version_mismatches:
        print("Dependency alignment OK: requirements.txt and pyproject.toml are in sync.")
        return 0

    print("Dependency alignment check failed.")
    if missing_in_pyproject:
        print("Missing in pyproject.toml:")
        for key in missing_in_pyproject:
            print(f"  - {req_deps[key]}")
    if missing_in_requirements:
        print("Missing in requirements.txt:")
        for key in missing_in_requirements:
            print(f"  - {pyproject_deps[key]}")
    if version_mismatches:
        print("Version/spec mismatches:")
        for key in version_mismatches:
            print(f"  - {key}: requirements.txt={req_deps[key]} | pyproject.toml={pyproject_deps[key]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
