"""Replace personal absolute paths in committed artefacts with portable ones.

A published output that records a home-directory path as its provenance leaks a
username onto GitHub Pages, makes two runs of the same pipeline diff, and tells a
reader on another machine nothing they can act on.

This rewrites the *provenance strings* inside generated JSON and JS. It does not
touch any computed value, so the results are unchanged; only the recorded name of
an input changes. Paths inside the repository become repository-relative; paths
outside become `<external>/<basename>`, which still identifies the input.

    python scripts/scrub_personal_paths.py --check     # report, change nothing
    python scripts/scrub_personal_paths.py             # rewrite in place

Source files are reported but never rewritten: a hard-coded path in code is a
defect to fix at the call site, with `fdqbench.paths.resolve_source`, not
something to paper over here.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Windows with either single or JSON-doubled separators, or a POSIX home.
#
# The tail runs to the enclosing quote rather than to the next space: these paths
# live inside JSON and JS string values and routinely contain spaces
# ("ASU Dropbox", "IEEE Big Data"). Stopping at a space rewrites the first
# segment and leaves the rest of the personal path in the file.
PERSONAL = re.compile(
    r"""(?P<prefix>[A-Za-z]:(?:\\{1,2})Users(?:\\{1,2})|/Users/|/home/)"""
    r"""(?P<rest>[^"']*)"""
)

# Repairs an earlier pass that stopped at the first space.
HALF_SCRUBBED = re.compile(r"""<external>/(?P<rest>[^"']*)""")

ARTEFACTS = ["outputs", "dashboard"]
ARTEFACT_SUFFIXES = {".json", ".js", ".csv"}
SOURCE_DIRS = ["scripts", "src"]


def portable(match: re.Match[str]) -> str:
    """Turn one matched absolute path into a repo-relative or <external> form."""
    raw = match.group(0)
    doubled = "\\\\" in raw
    normalised = raw.replace("\\\\", "/").replace("\\", "/")

    marker = "/I405--FDQ-dashboard-github/"
    if marker in normalised:
        return normalised.split(marker, 1)[1]
    for alternative in ("/I405--FDQ-dashboard/", "/fdq_single_link_benchmark_v0_2/"):
        if alternative in normalised:
            tail = normalised.split(alternative)[-1]
            return tail
    name = normalised.rstrip("/").rsplit("/", 1)[-1]
    return f"<external>/{name}" if not doubled else f"<external>/{name}"


def repair(match: re.Match[str]) -> str:
    """Re-resolve a `<external>/...` string that still carries directory segments."""
    rest = match.group("rest")
    normalised = rest.replace("\\\\", "/").replace("\\", "/")
    if "/" not in normalised:
        return match.group(0)          # already a bare basename; leave it alone
    marker = "/I405--FDQ-dashboard-github/"
    if marker in "/" + normalised:
        return ("/" + normalised).split(marker, 1)[1]
    return f"<external>/{normalised.rstrip('/').rsplit('/', 1)[-1]}"


def scrub_text(text: str) -> tuple[str, int]:
    hits = len(PERSONAL.findall(text))
    text = PERSONAL.sub(portable, text)
    repaired = HALF_SCRUBBED.sub(repair, text)
    if repaired != text:
        hits = max(hits, 1)
    return repaired, hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report offending files and exit non-zero; change nothing")
    args = parser.parse_args()

    offending_artefacts: list[tuple[Path, int]] = []
    for directory in ARTEFACTS:
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or path.suffix not in ARTEFACT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            cleaned, hits = scrub_text(text)
            if not hits:
                continue
            offending_artefacts.append((path, hits))
            if not args.check:
                path.write_text(cleaned, encoding="utf-8")

    offending_sources: list[Path] = []
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue          # this file matches on its own pattern literal
            try:
                if PERSONAL.search(path.read_text(encoding="utf-8")):
                    offending_sources.append(path)
            except (UnicodeDecodeError, OSError):
                continue

    verb = "would rewrite" if args.check else "rewrote"
    for path, hits in offending_artefacts:
        print(f"  {verb} {path.relative_to(ROOT)} ({hits} path(s))")
    print(f"{verb} {len(offending_artefacts)} artefact(s)")

    if offending_sources:
        print(f"\n{len(offending_sources)} source file(s) still hard-code a personal path.")
        print("Fix these at the call site with fdqbench.paths.resolve_source:")
        for path in offending_sources:
            print(f"  {path.relative_to(ROOT)}")

    if args.check and (offending_artefacts or offending_sources):
        return 1
    return 1 if offending_sources else 0


if __name__ == "__main__":
    raise SystemExit(main())
