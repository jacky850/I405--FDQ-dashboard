"""The queue kernel reproduces the published NVTA output, and refuses bad input.

`nvta_queue_kernel/` is the handoff package for embedding this model in a DNL.
Its whole claim is that the four lines of arithmetic in `kernel.py` are the same
four lines that produced `outputs/nvta_queue/`. These tests are that claim.

The conventions checked here are the ones PORTING_NOTES.md warns about: the
start-of-interval index, the Q/dt discharge term, and queue carryover across a
period boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "nvta_queue_kernel"
sys.path.insert(0, str(PACKAGE))

from kernel import queue_to_speed, run_link, run_queue  # noqa: E402

DT_H = 0.25
TOLERANCE = 1e-9
CASES = ["link_26469_i395nb.csv", "link_31804_i66eb.csv"]
COMPARED = ["outflow_vph", "queue_model_veh", "delay_h", "travel_time_h", "speed_model_mph"]


@pytest.fixture(scope="module")
def expected() -> pd.DataFrame:
    return pd.read_csv(PACKAGE / "data/expected_output.csv")


@pytest.mark.parametrize("filename", CASES)
@pytest.mark.parametrize("column", COMPARED)
def test_reproduces_published_output(filename, column, expected):
    frame = pd.read_csv(PACKAGE / "data" / filename).sort_values("t_min").reset_index(drop=True)
    result = run_link(
        arrival_vph=frame["lambda_anchored_vph"].to_numpy(float),
        service_vph=frame["mu_vph"].to_numpy(float),
        dt_h=DT_H,
        length_mi=float(frame["length_mi"].iloc[0]),
        free_speed_mph=float(frame["free_speed_mph"].iloc[0]),
        initial_queue_veh=0.0,
    )
    link_id = int(frame["link_id"].iloc[0])
    want = (expected[expected["link_id"] == link_id]
            .sort_values("t_min")[column].to_numpy(float))
    assert np.max(np.abs(result[column] - want)) < TOLERANCE


@pytest.mark.parametrize("filename", CASES)
def test_published_cases_cover_both_peaks(filename, expected):
    """The pair is meant to show an AM case and a PM case; guard that."""
    frame = pd.read_csv(PACKAGE / "data" / filename)
    link_id = int(frame["link_id"].iloc[0])
    want = expected[expected["link_id"] == link_id].sort_values("t_min").reset_index(drop=True)
    peak_minute = int(frame.sort_values("t_min").reset_index(drop=True)
                      .loc[int(want["queue_model_veh"].idxmax()), "t_min"])
    period = frame.sort_values("t_min").reset_index(drop=True).loc[
        int(want["queue_model_veh"].idxmax()), "anchor_period"]
    assert period in {"AM", "PM"}
    assert 360 <= peak_minute < 1140


def test_queue_is_start_of_interval():
    """`queue[0]` is the initial queue, not the queue after the first interval."""
    queue, outflow, final = run_queue([100.0, 100.0], [0.0, 0.0], dt_h=1.0,
                                      initial_queue_veh=7.0)
    assert queue[0] == pytest.approx(7.0)
    assert queue[1] == pytest.approx(107.0)
    assert final == pytest.approx(207.0)
    assert outflow == pytest.approx([0.0, 0.0])


def test_standing_queue_discharges_through_the_dt_term():
    """Without Q/dt in `available`, a queue could never drain faster than arrivals."""
    # No new arrivals, service 40 veh/h, dt = 0.25 h -> 10 veh served per interval.
    queue, outflow, final = run_queue([0.0, 0.0, 0.0], [40.0, 40.0, 40.0],
                                      dt_h=0.25, initial_queue_veh=25.0)
    assert outflow[0] == pytest.approx(40.0)
    assert queue == pytest.approx([25.0, 15.0, 5.0])
    assert final == pytest.approx(0.0)


def test_queue_never_negative_and_clears_when_undersaturated():
    queue, _, final = run_queue([10.0] * 5, [1000.0] * 5, dt_h=0.25)
    assert (queue >= 0).all()
    assert final == pytest.approx(0.0)


def test_period_boundary_carries_the_queue():
    """Chaining two calls with the carried queue equals one continuous run.

    This is the property that makes AM/MD/PM labels rather than resets.
    """
    arrival = np.array([2000.0, 2000.0, 500.0, 500.0])
    service = np.array([1000.0, 1000.0, 1000.0, 1000.0])
    whole, whole_out, _ = run_queue(arrival, service, DT_H)

    first, _, carried = run_queue(arrival[:2], service[:2], DT_H)
    second, _, _ = run_queue(arrival[2:], service[2:], DT_H, initial_queue_veh=carried)

    assert np.concatenate([first, second]) == pytest.approx(whole)
    assert carried > 0, "the fixture must actually leave a queue standing"


def test_zero_queue_gives_exactly_free_speed():
    speed, travel_time, delay = queue_to_speed([0.0, 0.0], [1000.0, 1000.0],
                                               length_mi=2.0, free_speed_mph=60.0)
    assert speed == pytest.approx([60.0, 60.0])
    assert travel_time == pytest.approx([2.0 / 60.0] * 2)
    assert delay == pytest.approx([0.0, 0.0])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(arrival_vph=[1.0, 2.0], service_vph=[1.0], dt_h=0.25), "must match"),
        (dict(arrival_vph=[1.0], service_vph=[1.0], dt_h=0.0), "must be positive"),
        (dict(arrival_vph=[-1.0], service_vph=[1.0], dt_h=0.25), "non-negative"),
        (dict(arrival_vph=[np.nan], service_vph=[1.0], dt_h=0.25), "NaN"),
        (dict(arrival_vph=[1.0], service_vph=[1.0], dt_h=0.25,
              initial_queue_veh=-5.0), "non-negative"),
    ],
)
def test_bad_input_is_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        run_queue(**kwargs)
