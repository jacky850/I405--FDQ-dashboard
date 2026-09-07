"""Sample sizes quoted in the documents match the committed outputs.

One TMC covers several network links, so the two counts are not interchangeable
and the link count overstates the independent evidence. The documents had
"252 links from 154 TMCs", which conflated the number of TMCs *with speed data*
on the four corridors with the number that actually map onto the analysed links.

These are the counts a reader would cite, so they get a test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "outputs/nvta_queue"


@pytest.fixture(scope="module")
def series() -> pd.DataFrame:
    path = QUEUE / "step8_speed_variants_15min.csv"
    if not path.exists():
        pytest.skip("NVTA queue outputs not present")
    return pd.read_csv(path, usecols=["link_id", "tmc_code", "corridor"])


@pytest.fixture(scope="module")
def audit() -> pd.DataFrame:
    path = QUEUE / "free_speed_audit_by_tmc.csv"
    if not path.exists():
        pytest.skip("free-speed audit not present")
    return pd.read_csv(path, usecols=["tmc_code", "corridor"])


def test_the_analysed_network_is_252_links_on_132_tmcs(series):
    assert series["link_id"].nunique() == 252
    assert series["tmc_code"].nunique() == 132


def test_the_audit_covers_more_tmcs_than_the_analysis_uses(audit, series):
    """154 TMCs carry speed; 132 of them map onto a network link.

    Quoting 154 as the independent-observation count for the 252 links is the
    error this test exists to catch.
    """
    assert audit["tmc_code"].nunique() == 154
    assert series["tmc_code"].nunique() < audit["tmc_code"].nunique()
    assert set(series["tmc_code"]) <= set(audit["tmc_code"])


def test_links_per_corridor(series):
    counts = series.groupby("corridor")["link_id"].nunique().to_dict()
    assert counts == {"I395_NB": 29, "I395_SB": 32, "I66_EB": 82, "I66_WB": 109}
    assert sum(counts.values()) == 252


def test_episode_links_sit_on_fewer_tmcs(series):
    """76 links with an episode, but only 44 independent observations behind them."""
    episodes = QUEUE / "step2_episodes.csv"
    if not episodes.exists():
        pytest.skip("episode table not present")
    links = pd.read_csv(episodes, usecols=["link_id"])["link_id"].unique()
    tmc_of = series.drop_duplicates("link_id").set_index("link_id")["tmc_code"]
    assert len(links) == 76
    assert tmc_of.reindex(links).nunique() == 44


@pytest.mark.parametrize("document", [
    "docs/QUEUE_STEPS_ZH.md",
    "nvta_queue_kernel/README.md",
])
def test_no_document_says_252_links_come_from_154_tmcs(document):
    """The specific conflation, in either language.

    Matches the *claim* -- "from 154 TMCs", "154 independent observations" -- not
    the mere co-occurrence of the two numbers. Both documents legitimately
    mention 154 while explaining that only 132 of those TMCs carry a link.
    """
    text = (ROOT / document).read_text(encoding="utf-8")
    for pattern in [r"来自\s*\*{0,2}154",
                    r"\bfrom\s+\*{0,2}154\s*(?:INRIX\s+)?TMC",
                    r"only\s+\*{0,2}154\s+independent",
                    r"154\s*个独立的速度观测"]:
        found = re.search(pattern, text)
        assert not found, (
            f"{document} still ties 252 links to 154 TMCs; it is 132. "
            f"Matched: {found.group(0)!r}")
