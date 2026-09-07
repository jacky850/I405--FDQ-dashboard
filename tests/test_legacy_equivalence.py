"""LEGACY_NOMINAL_DC reproduces the frozen v0.2 oracle, value for value.

`tests/gold/slc_qvdf_legacy_v02.json` was generated from `slc_qvdf.py` before
ISSUE 05 touched it. Its only purpose is to fail when the legacy path drifts, so
regenerating it to make a test pass destroys it. If a value here has to change,
that is a deliberate change to published behaviour and belongs in its own commit
with a before/after table.

The file also pins what `k_mu` touches. `mu = k_mu * C` feeds `queue_delay_vht`
and the queue profile even on a `D_over_C` run, which is a 15% effect on the
reference link. That was reviewed and kept as legacy behaviour rather than moved
into Mode B; see the module docstring. These tests make the decision visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from fdqbench.slc_qvdf import (LEGACY_NOMINAL_DC, SLCLinkParameters,
                               qvdf_episode_profile, qvdf_forward,
                               qvdf_inverse_identified)

GOLD = Path(__file__).resolve().parent / "gold/slc_qvdf_legacy_v02.json"


@pytest.fixture(scope="module")
def gold() -> dict:
    return json.loads(GOLD.read_text(encoding="utf-8"))


def case_names() -> list[str]:
    return sorted(json.loads(GOLD.read_text(encoding="utf-8"))["cases"])


def link_of(case: dict) -> SLCLinkParameters:
    return SLCLinkParameters(**case["inputs"])


def test_the_golden_file_declares_its_tolerance(gold):
    assert gold["tolerance"] == {"rtol": 1e-12, "atol": 0.0}
    assert gold["cases"], "the golden file is empty"


@pytest.mark.parametrize("name", case_names())
def test_forward_matches_the_frozen_oracle(gold, name):
    case = gold["cases"][name]
    state = qvdf_forward(link_of(case), mode=LEGACY_NOMINAL_DC)
    for key, expected in case["forward"].items():
        assert state[key] == pytest.approx(expected, rel=1e-12, abs=0.0), (
            f"{name}.{key} drifted from the frozen v0.2 value")


@pytest.mark.parametrize("name", case_names())
def test_inverse_matches_the_frozen_oracle(gold, name):
    case = gold["cases"][name]
    link = link_of(case)
    recovered = qvdf_inverse_identified(
        link, case["forward"]["P"], case["forward"]["vT2"], mode=LEGACY_NOMINAL_DC)
    for key, expected in case["inverse"].items():
        assert recovered[key] == pytest.approx(expected, rel=1e-12, abs=0.0), (
            f"{name}.{key} drifted from the frozen v0.2 value")


@pytest.mark.parametrize("name", case_names())
def test_episode_profile_matches_the_frozen_oracle(gold, name):
    case = gold["cases"][name]
    link = link_of(case)
    state = qvdf_forward(link, mode=LEGACY_NOMINAL_DC)
    clock = np.asarray(case["profile"]["clock_h"], dtype=float)
    speed, queue = qvdf_episode_profile(link, state, clock)
    # An absolute floor is needed at the episode boundary. There the shape factor
    # (1 - tau^2)^2 vanishes, so a last-bit difference in P -- the same P that
    # matches to 1e-12 above -- is squared into a large *relative* difference
    # between two numbers that are both around 1e-28. A queue of 1e-28 vehicles
    # is zero. Away from the boundary the values are order 1 to 1000 and the
    # relative tolerance is what binds.
    for produced, expected, label in [(speed, case["profile"]["speed_mph"], "speed"),
                                      (queue, case["profile"]["queue_veh"], "queue")]:
        for i, want in enumerate(expected):
            if want is None:
                assert np.isnan(produced[i]), f"{name}.{label}[{i}] should be outside the episode"
            else:
                assert produced[i] == pytest.approx(want, rel=1e-12, abs=1e-9), (
                    f"{name}.{label}[{i}] drifted")


@pytest.mark.parametrize("name", case_names())
def test_default_mode_is_the_legacy_mode(gold, name):
    """A v0.2 caller that never heard of `mode` must get identical numbers."""
    link = link_of(gold["cases"][name])
    assert qvdf_forward(link) == qvdf_forward(link, mode=LEGACY_NOMINAL_DC)


def test_kmu_still_reaches_queue_delay_on_a_dc_run(gold):
    """The compatibility decision, asserted rather than described.

    Both cases use `D_over_C`, so the duration is identical. Only `k_mu` differs,
    and `queue_delay_vht` moves with it. If someone later confines `k_mu` to
    Mode B, this fails and the change becomes visible instead of silent.
    """
    dropped = gold["cases"]["report_reference_D_over_C"]["forward"]
    unity = gold["cases"]["kmu_unity_D_over_C"]["forward"]

    assert dropped["P"] == pytest.approx(unity["P"], rel=1e-12)
    assert dropped["x"] == pytest.approx(unity["x"], rel=1e-12)
    capacity = gold["cases"]["report_reference_D_over_C"]["inputs"]["capacity_vph"]
    assert dropped["mu"] == pytest.approx(0.85 * capacity, rel=1e-12)
    assert unity["mu"] == pytest.approx(capacity, rel=1e-12)

    ratio = dropped["queue_delay_vht"] / unity["queue_delay_vht"]
    assert ratio == pytest.approx(0.85, rel=1e-12), (
        "queue_delay_vht scales with k_mu on a D_over_C run; that is frozen "
        "legacy behaviour, documented in the slc_qvdf module docstring")


def test_the_gold_file_covers_both_bases_and_both_kmu_regimes(gold):
    """Guards the coverage the decision above depends on."""
    names = set(gold["cases"])
    assert {"report_reference_D_over_C", "report_reference_D_over_mu",
            "kmu_unity_D_over_C", "kmu_unity_D_over_mu"} <= names
    assert len(names) >= 6, "the golden file should pin more than one link"
