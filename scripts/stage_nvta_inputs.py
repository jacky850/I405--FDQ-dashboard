"""Copy the NVTA queue inputs into the repository so steps 1 and 5 reproduce.

Steps 2-4 and 6-8 already run from committed outputs. Steps 1 and 5 were the two
that needed an external package, which meant nobody but the author could rerun
the chain from observed speed. This stages the parts they read.

Only the four studied corridors are kept, and the two network tables are filtered
to the links those corridors map to. The speed readings are copied whole, because
they are already corridor-scoped and every column is used or documented. Files
are gzipped; pandas reads them transparently.

    python scripts/stage_nvta_inputs.py --shared /path/to/link-queue-simulation

Writes to data/nvta_link_queue_inputs/, mirroring the external layout so the same
code path reads either, and records a manifest with row counts and SHA-256 of
each source file.

Provenance: INRIX 15-minute TMC speeds and the TAPLite assignment tables, as
supplied in the shared `link-queue-simulation` package. Redistribution of the
INRIX readings inside this repository was authorised by the project owner.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.paths import as_repo_relative, resolve_source  # noqa: E402

CORRIDORS = ["I395_NB", "I395_SB", "I66_EB", "I66_WB"]
PERIODS = ["am", "md", "pm"]
DESTINATION = ROOT / "data/nvta_link_queue_inputs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_gzipped(frame: pd.DataFrame, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, compression="gzip")
    return target.stat().st_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared", type=Path, default=None,
                        help="the link-queue-simulation package; if omitted, resolved "
                             "from configs/data_sources.json")
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shared = resolve_source("link_queue_simulation", args.shared)
    args.destination.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "staged_on": date.today().isoformat(),
        "source_package": "link-queue-simulation (external, not committed)",
        "corridors": CORRIDORS,
        "files": {},
    }

    # 1. Speed readings, one directory per corridor, copied whole.
    tmc_codes: set[str] = set()
    for corridor in CORRIDORS:
        source = shared / "tmc-15min-speed" / corridor
        readings = pd.read_csv(source / "Readings.csv")
        tmc_codes.update(readings["tmc_code"].astype(str).unique())
        target = args.destination / "tmc-15min-speed" / corridor / "Readings.csv.gz"
        size = write_gzipped(readings, target)
        shutil.copy2(source / "TMC_Identification.csv",
                     target.parent / "TMC_Identification.csv")
        manifest["files"][f"tmc-15min-speed/{corridor}/Readings.csv.gz"] = {
            "rows": int(len(readings)), "bytes": size,
            "source_sha256": sha256(source / "Readings.csv"),
        }
        print(f"  {corridor:<9} {len(readings):>7} readings, "
              f"{readings['tmc_code'].nunique():>4} TMCs -> {size / 1e6:.1f} MB")

    # 2. TMC-to-link matching, filtered to the TMCs those corridors actually carry.
    source = shared / "tmc-matching/canonical_node_pair_tmc-1v1.csv"
    mapping = pd.read_csv(source)
    kept = mapping[mapping["tmc"].astype(str).isin(tmc_codes)]
    target = args.destination / "tmc-matching/canonical_node_pair_tmc-1v1.csv.gz"
    size = write_gzipped(kept, target)
    manifest["files"]["tmc-matching/canonical_node_pair_tmc-1v1.csv.gz"] = {
        "rows": int(len(kept)), "rows_in_source": int(len(mapping)), "bytes": size,
        "source_sha256": sha256(source),
        "filter": "tmc in the four corridors' readings",
    }
    print(f"  matching  {len(kept):>7} of {len(mapping)} rows -> {size / 1e6:.1f} MB")

    # 3. Assignment link tables, filtered to the links that matching keeps. The
    #    node ids travel with link_id because step 1 joins on all three.
    link_ids = set(kept["link_id"].astype(str))
    for period in PERIODS:
        source = shared / f"TAPLite-model-input-output-subset/{period}/link_performance.csv"
        performance = pd.read_csv(source)
        subset = performance[performance["link_id"].astype(str).isin(link_ids)]
        target = args.destination / f"TAPLite-model-input-output-subset/{period}/link_performance.csv.gz"
        size = write_gzipped(subset, target)
        manifest["files"][f"TAPLite-model-input-output-subset/{period}/link_performance.csv.gz"] = {
            "rows": int(len(subset)), "rows_in_source": int(len(performance)), "bytes": size,
            "source_sha256": sha256(source),
            "filter": "link_id present in the filtered matching table",
        }
        print(f"  {period:<9} {len(subset):>7} of {len(performance)} links -> {size / 1e6:.1f} MB")

    manifest["total_bytes"] = sum(entry["bytes"] for entry in manifest["files"].values())
    (args.destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{as_repo_relative(args.destination)}: "
          f"{manifest['total_bytes'] / 1e6:.1f} MB across {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
