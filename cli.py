from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from comps.config import load_peers, load_policy  # noqa: E402
from comps.pipeline import run  # noqa: E402
from comps.workbook import write_workbook  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Comps Scrubber — adjusted comparable company analysis")
    ap.add_argument("--peers", help="Path to peers YAML (default config/peers.yaml)")
    ap.add_argument("--policy", help="Path to policy YAML (default config/policy.yaml)")
    ap.add_argument("--output", help="Override output workbook path")
    args = ap.parse_args()

    peers = load_peers(args.peers)
    policy = load_policy(args.policy)
    if args.output:
        peers.output = Path(args.output)

    print(f"Running comps for {len(peers.peers)} peers x {peers.num_years} years...")
    rows, bridges, flags = run(peers, policy)
    write_workbook(rows, bridges, flags, peers.output)
    print(f"Wrote {peers.output}")
    print(f"  comps rows: {len(rows)}")
    print(f"  flags:      {len(flags)}")


if __name__ == "__main__":
    main()
