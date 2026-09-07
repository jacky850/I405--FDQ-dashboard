"""The dashboard shows what the pipeline generated, and nothing else.

Every headline number on `dashboard/qvdf_multiweek.html` used to be typed into
the HTML by hand. Two of them had drifted from the results: the "Supported MAPE"
tile showed 16.51%, which is the whole-period *speed* MAPE, not the supported
*volume* MAPE of 16.88%; and the median APE tile showed 14.71% against a
generated 14.51%.

These tests fail if a number is reintroduced into the markup, if the payload
stops matching the source JSON, or if `k_d` is labelled as `D/C` again.

See docs/VARIABLE_CONTRACT.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/i405_multiweek_average_holdout"
DASHBOARD = ROOT / "dashboard"
PAYLOAD = DASHBOARD / "qvdf_multiweek_data.js"
PAGE = DASHBOARD / "qvdf_multiweek.html"
SCRIPT = DASHBOARD / "qvdf_multiweek.js"

TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def payload() -> dict:
    text = PAYLOAD.read_text(encoding="utf-8")
    body = text[text.index("=") + 1:].rstrip().rstrip(";")
    return json.loads(body)


@pytest.fixture(scope="module")
def comparison() -> dict:
    return json.loads((SOURCE / "observed_vs_inferred_D_V_summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def projection() -> dict:
    return json.loads((SOURCE / "forward_projection_speed_summary.json").read_text(encoding="utf-8"))


def test_payload_comparison_matches_source(payload, comparison):
    """The browser payload carries the generated summary unmodified."""
    assert payload["comparison"] == comparison


def test_payload_projection_matches_source(payload, projection):
    assert payload["projection"] == projection


@pytest.mark.parametrize(
    "path",
    [
        ("coverage", "total_cases"),
        ("coverage", "episode_identified"),
        ("coverage", "supported_both_gates"),
        ("coverage", "supported_pct"),
        ("supported_cases", "demand_D", "mape_pct"),
        ("supported_cases", "volume_V", "mape_pct"),
        ("supported_cases", "volume_V", "median_ape_pct"),
    ],
)
def test_headline_inputs_are_present_and_equal(payload, comparison, path):
    """Each value the headline renders exists in both places and agrees.

    The renderer reads these exact keys; a rename upstream would silently blank a
    tile rather than showing a wrong number, so the keys are pinned here too.
    """
    generated = comparison
    carried = payload["comparison"]
    for key in path:
        generated = generated[key]
        carried = carried[key]
    assert carried == pytest.approx(generated, abs=TOLERANCE)


def test_speed_mape_is_available_and_distinct_from_volume(payload, comparison, projection):
    """The two MAPEs are different numbers and must not be shown as one metric."""
    speed = projection["supported_cases"]["period"]["forward"]["mape_pct"]
    volume = comparison["supported_cases"]["volume_V"]["mape_pct"]
    assert payload["projection"]["supported_cases"]["period"]["forward"]["mape_pct"] == pytest.approx(
        speed, abs=TOLERANCE)
    assert abs(speed - volume) > TOLERANCE, (
        "speed and volume MAPE happen to be equal; the labelling test below is then "
        "vacuous and this fixture needs revisiting"
    )


def test_no_hard_coded_percentages_in_headline_markup():
    """The headline section is rendered, not typed."""
    html = PAGE.read_text(encoding="utf-8")
    section = re.search(
        r'<section class="metrics" id="headlineMetrics".*?</section>', html, re.S)
    assert section, "headlineMetrics section is missing from the page"
    assert not re.search(r"\d+\.\d+%", section.group(0)), (
        "a percentage is hard-coded in the headline markup; render it from "
        "window.QVDF_MULTI instead"
    )


def test_stale_headline_values_are_gone():
    """The two numbers that were wrong must not reappear anywhere in the markup."""
    html = PAGE.read_text(encoding="utf-8")
    for stale in ("16.51%", "14.71%"):
        assert stale not in html, f"{stale} is hard-coded in the page again"


def test_kd_is_not_labelled_as_dc(comparison):
    """k_d is a peak-load factor and is reported on its own."""
    supported = comparison["supported_cases"]
    assert "d_over_c" not in supported, "the mislabelled d_over_c block is back"
    assert "dc_rate" in supported
    assert "peak_load_factor_kd_observed" in comparison

    kd = comparison["peak_load_factor_kd_observed"]
    assert kd["min"] >= 1.0, (
        "k_d is D/(V/H) and cannot be below 1; a value under 1 means the field is "
        "carrying something else"
    )


def test_renderer_reads_the_canonical_keys():
    """The script must not still be reaching for the old key names."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "s1.d_over_c" not in script, "the renderer still reads the removed d_over_c block"
    assert "dc_rate" in script
    assert "headlineMetrics" in script, "the headline renderer is missing"
