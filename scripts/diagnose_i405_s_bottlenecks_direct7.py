"""Evidence-based bottleneck screening for the seven direct D/μ links."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


TARGETS = ["L405S-012", "L405S-018", "L405S-028", "L405S-030", "L405S-058", "L405S-098", "L405S-115"]


def split_ids(value: object) -> list[str]:
    if pd.isna(value) or not str(value):
        return []
    return [x for x in str(value).split(";") if x]


def downstream_chain(link_id: str, topo: pd.DataFrame, links: pd.DataFrame, observed: set[str], limit: int = 8) -> list[str]:
    chain = []
    current = link_id
    seen = {current}
    for _ in range(limit):
        if current not in links.index:
            break
        node = links.loc[current, "to_node_id"]
        candidates = links[(links["from_node_id"] == node) & (links["is_ramp"] == 0)].index.astype(str).tolist()
        mainline = [x for x in candidates if x not in seen and x.startswith("L405S-")]
        if not mainline:
            break
        nxt = mainline[0]
        seen.add(nxt)
        chain.append(nxt)
        current = nxt
    return chain


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-file", type=Path, required=True)
    ap.add_argument("--corridor-root", type=Path, required=True)
    ap.add_argument("--episode-file", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(args.test_file)
    raw["time_key"] = raw["date"].astype(str) + "|" + raw["time_la"].astype(str)
    links = pd.read_csv(args.corridor_root / "network" / "links.csv").set_index("link_id")
    topo = pd.read_csv(args.corridor_root / "network" / "lwr_mainline_topology.csv").set_index("link_id")
    observed = set(raw["link_id"].astype(str))
    episode = pd.read_csv(args.episode_file)
    cleared = episode[episode["quality_status"] == "episode_cleared"].groupby("link_id").size()

    # Aggregate each observed link at the original LA 5-minute time key.
    obs = raw[raw["link_id"].isin(observed)].copy()
    obs["congested"] = obs["speed_kmh"] <= 0.70 * obs["link_id"].map(links["free_speed_kmh"])
    by_link = {k: g.set_index("time_key") for k, g in obs.groupby("link_id")}
    results = []
    for target in TARGETS:
        tg = by_link[target]
        chain = downstream_chain(target, topo, links, observed)
        target_cong = tg[tg["congested"]]
        target_mean = float(tg["speed_kmh"].mean())
        target_min = float(tg["speed_kmh"].min())
        target_cong_n = int(target_cong.shape[0])
        target_cong_flow_cv = float(target_cong["flow_vph"].std() / target_cong["flow_vph"].mean()) if target_cong_n > 1 and target_cong["flow_vph"].mean() else np.nan
        for rank, downstream in enumerate(chain, start=1):
            dg = by_link.get(downstream)
            if dg is None:
                continue
            common = tg.index.intersection(dg.index)
            pair = tg.loc[common, ["speed_kmh", "flow_vph", "congested"]].join(
                dg.loc[common, ["speed_kmh", "flow_vph", "congested"]], lsuffix="_target", rsuffix="_downstream"
            )
            pair = pair[pair["congested_target"]]
            if pair.empty:
                speed_gap = np.nan
                downstream_recovery = np.nan
                flow_gap = np.nan
            else:
                speed_gap = float((pair["speed_kmh_downstream"] - pair["speed_kmh_target"]).median())
                downstream_recovery = float((pair["speed_kmh_downstream"] > 0.85 * links.loc[downstream, "free_speed_kmh"]).mean())
                flow_gap = float((pair["flow_vph_downstream"] - pair["flow_vph_target"]).median())
            results.append({
                "target_link_id": target, "downstream_rank": rank, "downstream_link_id": downstream,
                "target_congested_samples": target_cong_n, "target_min_speed_kmh": target_min,
                "target_mean_speed_kmh": target_mean, "target_congested_flow_cv": target_cong_flow_cv,
                "downstream_speed_gap_median_kmh": speed_gap,
                "downstream_free_flow_fraction_during_target_congestion": downstream_recovery,
                "downstream_minus_target_flow_median_vph": flow_gap,
                "cleared_episode_count_target": int(cleared.get(target, 0)),
            })

    comparison = pd.DataFrame(results)
    comparison.to_csv(args.output_dir / "i405_s_direct7_bottleneck_downstream_comparison.csv", index=False)

    decisions = []
    for target in TARGETS:
        rows = comparison[comparison["target_link_id"] == target].sort_values("downstream_rank")
        best = rows.iloc[0] if not rows.empty else None
        target_episodes = int(cleared.get(target, 0))
        if best is None and target_episodes == 0:
            decision = "needs_review_no_clear_congestion"
        elif best is None:
            decision = "needs_review_no_observed_downstream"
        elif int(best["target_congested_samples"]) < 3:
            decision = "needs_review_no_clear_congestion"
        elif best["downstream_speed_gap_median_kmh"] >= 10 and target_episodes >= 3:
            decision = "target_candidate_bottleneck_use_target_flow_pending_review"
        elif best["downstream_speed_gap_median_kmh"] <= -5:
            decision = "downstream_or_further_bottleneck_use_downstream_flow_candidate"
        else:
            decision = "needs_review_mixed_evidence"
        decisions.append({
            "target_link_id": target,
            "first_observed_downstream_link": best["downstream_link_id"] if best is not None else "",
            "decision": decision,
            "recommended_mu_source": "target_link_flow" if decision.startswith("target_candidate") else "downstream_flow_or_review",
            "cleared_episode_count_target": target_episodes,
        })
    pd.DataFrame(decisions).to_csv(args.output_dir / "i405_s_direct7_bottleneck_decision.csv", index=False)
    print(pd.DataFrame(decisions).to_string(index=False))


if __name__ == "__main__":
    main()
