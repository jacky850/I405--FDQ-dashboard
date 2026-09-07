"""Repo-relative path rendering, so no committed output carries a personal path.

Every published JSON and CSV is read by someone on a different machine. An
absolute path from the machine that produced it is at best noise and at worst a
username published on GitHub Pages, and it makes a diff between two runs of the
same pipeline look like a change when nothing changed.

Use :func:`as_repo_relative` for anything that lands in a written artefact.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/data_sources.json"
LOCAL_CONFIG = ROOT / "configs/data_sources.local.json"


def as_repo_relative(path: os.PathLike[str] | str) -> str:
    """Render `path` relative to the repository root, with forward slashes.

    Falls back to the basename when the path lies outside the repository, which
    is the case for the external shared data package. The name is kept because it
    identifies which input was used; the directories above it are the part that
    is personal and are dropped.
    """
    resolved = Path(path).expanduser()
    try:
        resolved = resolved.resolve()
    except OSError:
        pass
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


class SourceNotConfigured(SystemExit):
    """Raised with an actionable message when an external input has no location."""


def _load_config() -> dict:
    merged: dict = {}
    for path in (CONFIG, LOCAL_CONFIG):
        if path.exists():
            block = json.loads(path.read_text(encoding="utf-8")).get("sources", {})
            for name, entry in block.items():
                merged.setdefault(name, {}).update(entry)
    return merged


def resolve_source(name: str, override: os.PathLike[str] | str | None = None) -> Path:
    """Locate an external input that is too large or too restricted to commit.

    Resolution order, first hit wins:

      1. `override`, normally the script's own command-line argument
      2. the `FDQ_<NAME>` environment variable
      3. `configs/data_sources.local.json`, then `configs/data_sources.json`

    No script carries a personal absolute path as a default, so a fresh clone on
    another machine fails with an instruction rather than with a path that
    happens not to exist.
    """
    if override is not None:
        candidate = Path(override).expanduser()
        if not candidate.exists():
            raise SourceNotConfigured(f"{name}: the path given does not exist: {candidate}")
        return candidate

    environment = os.environ.get(f"FDQ_{name.upper()}")
    if environment:
        candidate = Path(environment).expanduser()
        if not candidate.exists():
            raise SourceNotConfigured(
                f"{name}: FDQ_{name.upper()} points at a path that does not exist: {candidate}")
        return candidate

    entry = _load_config().get(name)
    if entry is None:
        raise SourceNotConfigured(
            f"{name}: not declared in {as_repo_relative(CONFIG)}. Add it there, or pass the "
            f"path on the command line.")

    configured = entry.get("path")
    if not configured:
        raise SourceNotConfigured(
            f"{name} is not configured.\n"
            f"  What it is: {entry.get('description', '(no description)')}\n"
            f"  Set it one of three ways:\n"
            f"    - pass the path as a command-line argument\n"
            f"    - export FDQ_{name.upper()}=/path/to/it\n"
            f"    - set sources.{name}.path in configs/data_sources.local.json\n"
            f"  Expected to contain: {', '.join(entry.get('expected_children') or ['-'])}"
        )

    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if not candidate.exists():
        raise SourceNotConfigured(
            f"{name}: configured path does not exist on this machine: {candidate}\n"
            f"  Override it in configs/data_sources.local.json or with "
            f"FDQ_{name.upper()}.")
    return candidate
