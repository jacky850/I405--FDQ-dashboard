"""One authoritative period clock, and nothing disagrees with it.

`docs/MULTIWEEK_AVERAGE_HOLDOUT_V1.md` said AM ran 06:00-10:00 while the code it
described had always used 06:00-09:00. Nothing downstream was wrong, but a reader
checking the window against the results would have found a mismatch and had no
way to tell which side was the defect.

See docs/VARIABLE_CONTRACT.md section 4.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The contract, in minutes from midnight.
CANONICAL = {
    "AM": (360, 540),    # 06:00-09:00
    "MD": (540, 900),    # 09:00-15:00
    "PM": (900, 1140),   # 15:00-19:00
}


def test_contract_declares_the_clock():
    text = (ROOT / "docs/VARIABLE_CONTRACT.md").read_text(encoding="utf-8")
    for period, hhmm in [("AM", ("06:00", "09:00")),
                         ("MD", ("09:00", "15:00")),
                         ("PM", ("15:00", "19:00"))]:
        row = re.search(rf"^\|\s*{period}\s*\|(.+)$", text, re.M)
        assert row, f"{period} is missing from the contract's period table"
        assert hhmm[0] in row.group(1) and hhmm[1] in row.group(1), (
            f"{period} in the contract is not {hhmm[0]}-{hhmm[1]}")


def test_multiweek_holdout_uses_the_canonical_hours():
    text = (ROOT / "scripts/run_i405_multiweek_average_holdout.py").read_text(encoding="utf-8")
    match = re.search(r"PERIODS\s*=\s*\{([^}]*)\}", text)
    assert match, "PERIODS is no longer declared where this test looks for it"
    body = match.group(1)
    assert '"AM": (6.0, 9.0)' in body, f"AM window changed: {body}"
    assert '"PM": (15.0, 19.0)' in body, f"PM window changed: {body}"


def test_dashboard_period_windows_match():
    text = (ROOT / "dashboard/qvdf_multiweek.js").read_text(encoding="utf-8")
    match = re.search(r"PERIOD_WINDOW\s*=\s*\{([^}]*)\}", text)
    assert match, "PERIOD_WINDOW is no longer declared in the dashboard script"
    body = match.group(1).replace(" ", "")
    assert f"AM:[{CANONICAL['AM'][0]},{CANONICAL['AM'][1]}]" in body, body
    assert f"PM:[{CANONICAL['PM'][0]},{CANONICAL['PM'][1]}]" in body, body


# A document may name the old window only while marking it as the defect. These
# are the phrasings that count as marking it; anything else is a live claim.
CORRECTION_MARKERS = ("documentation defect", "was documented as", "said 06:00")


@pytest.mark.parametrize("document", sorted((ROOT / "docs").glob("*.md")))
def test_no_document_claims_am_ends_at_ten(document):
    text = document.read_text(encoding="utf-8")
    # Match 06:00 followed by any dash form and 10:00.
    for offending in re.finditer(r"06:00\s*[-–—]{1,2}\s*10:00", text):
        context = text[max(0, offending.start() - 300):offending.end() + 300]
        assert any(marker in context for marker in CORRECTION_MARKERS), (
            f"{document.name} states AM as 06:00-10:00 without marking it as the "
            f"corrected defect:\n...{context}...")
