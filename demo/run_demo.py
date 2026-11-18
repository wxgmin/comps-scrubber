from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comps.config import load_peers, load_policy  # noqa: E402
from comps.pipeline import run  # noqa: E402
from comps.workbook import write_workbook  # noqa: E402

_M = 1_000_000.0


def _m(v):
    return "" if v is None else f"{v / _M:,.1f}"


def main() -> None:
    peers = load_peers()
    policy = load_policy()
    print(f"Running demo: {len(peers.peers)} software peers x {peers.num_years} years...")
    rows, bridges, flags = run(peers, policy)
    write_workbook(rows, bridges, flags, peers.output)
    print(f"Workbook: {peers.output}")
    print(f"Flags: {len(flags)}")

    writeup_path = Path(__file__).resolve().parent / "writeup.md"
    lines: list[str] = [
        "# Comps Scrubber — demo write-up",
        "",
        f"Peer set: {', '.join(peers.peers)}",
        "",
        "Below, the tool's **adjusted EBITDA** is compared to each company's **own reported "
        "adjusted EBITDA** (from its 8-K 99.1 non-GAAP reconciliation). All tool adjustment "
        "amounts are quoted verbatim from the filings and verified by code; the workbook's "
        "bridge sheets carry each quote with a one-click link to the source.",
        "",
        "## Why the two differ",
        "",
        "The dominant, systematic difference is **stock-based compensation**: by default the tool "
        "does *not* add back SBC (it is a recurring, real economic cost), whereas software "
        "companies almost always add it back in their own non-GAAP EBITDA. Toggle "
        "`StockBasedCompensation.enabled: true` in `config/policy.yaml` to match company "
        "non-GAAP. The remaining delta is category normalization — the tool applies one shared "
        "policy to every peer, so a charge one company calls 'restructuring' and another calls "
        "'business realignment' lands in the same adjustment bucket.",
        "",
        "## Comparison ($M, per fiscal year)",
        "",
        "| Ticker | FY | Reported EBITDA | Tool Adj. EBITDA | Company Adj. EBITDA | Delta (Tool − Co.) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for ticker, entries in bridges.items():
        for e in entries:
            lines.append(
                f"| {ticker} | FY{e['fiscal_year']} | {_m(e['reported_ebitda'])} "
                f"| {_m(e['adjusted_ebitda'])} | {_m(e['company_reported_adj_ebitda'])} "
                f"| {_m(_delta(e))} |"
            )
    lines += [
        "",
        "## Residual items needing judgement",
        "",
        f"{len(flags)} flag(s) were raised (see the workbook **Flags** sheet) covering recurring "
        "restructuring charges, XBRL mismatches, and any unverifiable quotes.",
        "",
    ]
    writeup_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Write-up: {writeup_path}")


def _delta(e) -> float | None:
    if e["adjusted_ebitda"] is None or e["company_reported_adj_ebitda"] is None:
        return None
    return e["adjusted_ebitda"] - e["company_reported_adj_ebitda"]


if __name__ == "__main__":
    main()
