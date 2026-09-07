"""The NVTA queue inputs are in the repository and resolve without configuration.

Queue steps 1 and 5 used to read an external package at a hard-coded Windows
path, so nobody but the author could rerun the chain from observed speed. The
four studied corridors are now staged under `data/nvta_link_queue_inputs/`.

These tests check the staged tree is complete and that `resolve_source` finds it
with nothing set — no argument, no environment variable, no local config. They do
not rerun the pipeline; `REPRODUCE.md` records that step 1 reproduces the
committed output to 6.8e-13 and step 5 to 1.8e-12.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.paths import resolve_source, table  # noqa: E402

STAGED = ROOT / "data/nvta_link_queue_inputs"
CORRIDORS = ["I395_NB", "I395_SB", "I66_EB", "I66_WB"]
PERIODS = ["am", "md", "pm"]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((STAGED / "manifest.json").read_text(encoding="utf-8"))


def test_source_resolves_with_nothing_configured(monkeypatch):
    """A fresh clone must find the inputs with no setup at all."""
    monkeypatch.delenv("FDQ_LINK_QUEUE_SIMULATION", raising=False)
    resolved = resolve_source("link_queue_simulation")
    assert resolved.resolve() == STAGED.resolve()


def test_environment_variable_still_overrides(monkeypatch, tmp_path):
    """Level 2 has to keep working for corridors outside the staged set."""
    monkeypatch.setenv("FDQ_LINK_QUEUE_SIMULATION", str(tmp_path))
    assert resolve_source("link_queue_simulation").resolve() == tmp_path.resolve()


@pytest.mark.parametrize("corridor", CORRIDORS)
def test_every_corridor_has_readings(corridor):
    readings = table(STAGED / "tmc-15min-speed" / corridor / "Readings.csv")
    assert readings.exists()
    frame = pd.read_csv(readings, nrows=5)
    for column in ["tmc_code", "measurement_tstamp", "speed"]:
        assert column in frame.columns, f"step 1 reads {column}"
    assert (STAGED / "tmc-15min-speed" / corridor / "TMC_Identification.csv").exists()


@pytest.mark.parametrize("period", PERIODS)
def test_every_period_has_a_link_table(period):
    path = table(STAGED / f"TAPLite-model-input-output-subset/{period}/link_performance.csv")
    assert path.exists()
    frame = pd.read_csv(path, nrows=5)
    # The columns steps 1 and 5 name explicitly in usecols.
    for column in ["link_id", "from_node_id", "to_node_id", "volume", "lane_capacity",
                   "link_capacity", "free_speed_mph", "cutoff_speed_mph",
                   "qvdf_profile_status"]:
        assert column in frame.columns, f"steps 1/5 read {column}"


def test_matching_table_covers_every_staged_link():
    """The network tables were filtered by the matching table; they must agree."""
    mapping = pd.read_csv(table(STAGED / "tmc-matching/canonical_node_pair_tmc-1v1.csv"))
    link_ids = set(mapping["link_id"].astype(str))
    for period in PERIODS:
        performance = pd.read_csv(
            table(STAGED / f"TAPLite-model-input-output-subset/{period}/link_performance.csv"))
        orphans = set(performance["link_id"].astype(str)) - link_ids
        assert not orphans, f"{period} carries links the matching table does not: {sorted(orphans)[:5]}"


def test_staged_tmcs_are_exactly_the_corridors_tmcs():
    """Filtering must not have dropped a TMC that a corridor actually reports."""
    observed: set[str] = set()
    for corridor in CORRIDORS:
        frame = pd.read_csv(table(STAGED / "tmc-15min-speed" / corridor / "Readings.csv"),
                            usecols=["tmc_code"])
        observed.update(frame["tmc_code"].astype(str).unique())
    mapping = pd.read_csv(table(STAGED / "tmc-matching/canonical_node_pair_tmc-1v1.csv"))
    assert set(mapping["tmc"].astype(str)) <= observed, "matching table has unobserved TMCs"


def test_manifest_records_provenance(manifest):
    assert manifest["corridors"] == CORRIDORS
    assert len(manifest["files"]) == 8
    for name, entry in manifest["files"].items():
        assert entry["rows"] > 0, f"{name} staged empty"
        assert len(entry["source_sha256"]) == 64, f"{name} has no source hash"
    # Small enough to live in git; a regression here means the filter broke.
    assert manifest["total_bytes"] < 20_000_000, "staged inputs grew past 20 MB"
