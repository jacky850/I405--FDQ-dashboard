from __future__ import annotations

import numpy as np

from fdqbench.slc_qvdf import (
    SLCLinkParameters,
    qvdf_episode_profile,
    qvdf_forward,
    qvdf_inverse_identified,
)


def gold_link() -> SLCLinkParameters:
    return SLCLinkParameters(
        link_id="GOLD-001",
        length_mi=1.2,
        period_hours=4.0,
        volume_veh=12000.0,
        free_speed_mph=65.0,
        cutoff_speed_mph=49.0,
        capacity_vph=5000.0,
        k_d=1.25,
        k_mu=0.85,
        stress_basis="D_over_C",
        f_d_h=5.0,
        n=1.10,
        f_p=0.24,
        s=1.40,
        T2_h=8.0,
    )


def test_gold_link_matches_report_values() -> None:
    link = gold_link()
    state = qvdf_forward(link)
    assert np.isclose(state["D"], 3750.0)
    assert np.isclose(state["mu"], 4250.0)
    assert np.isclose(state["P"], 3.6436562169865256)
    assert np.isclose(state["vT2"], 19.863989896401158)
    assert np.isclose(state["queue_delay_vht"], 296.6701228683981)
    recovered = qvdf_inverse_identified(link, state["P"], state["vT2"])
    assert np.isclose(recovered["V_hat"], link.volume_veh, rtol=1e-12)
    assert np.isclose(recovered["f_p_hat"], link.f_p, rtol=1e-12)


def test_episode_center_and_boundaries() -> None:
    link = gold_link()
    state = qvdf_forward(link)
    time = np.array([state["t0"], state["T2"], state["t3"]])
    speed, queue = qvdf_episode_profile(link, state, time)
    assert np.allclose(speed[[0, 2]], link.cutoff_speed_mph)
    assert np.isclose(speed[1], state["vT2"])
    assert np.allclose(queue[[0, 2]], 0.0)
    assert queue[1] > 0.0
