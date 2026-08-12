"""Stamp dashboard asset links with a content hash so browsers cannot serve a
stale mix of old CSS and new markup.

GitHub Pages and python -m http.server both let a browser reuse a cached
stylesheet against freshly fetched HTML. When that happens an unstyled <path>
falls back to a solid black fill and the page looks broken rather than merely
out of date. Hashing each local asset into its query string makes the URL change
whenever the file does, so the browser is forced to refetch exactly the files
that moved.

Run after editing any dashboard CSS or JS.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / "index.html", *sorted((ROOT / "dashboard").glob("*.html"))]
ATTRIBUTE = re.compile(r'(?P<attr>href|src)="(?P<path>[^"?:]+\.(?:css|js))(?:\?v=[0-9a-f]+)?"')


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def main() -> None:
    changed = 0
    for page in PAGES:
        text = page.read_text(encoding="utf-8")

        def stamp(match: re.Match[str]) -> str:
            asset = (page.parent / match["path"]).resolve()
            token = digest(asset)
            if token is None:
                return match[0]
            return f'{match["attr"]}="{match["path"]}?v={token}"'

        updated = ATTRIBUTE.sub(stamp, text)
        if updated != text:
            page.write_text(updated, encoding="utf-8", newline="\n")
            changed += 1
        print(f"{page.relative_to(ROOT)}: {len(ATTRIBUTE.findall(updated))} assets stamped")
    print(f"{changed} page(s) rewritten")


if __name__ == "__main__":
    main()
