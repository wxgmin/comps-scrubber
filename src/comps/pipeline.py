from __future__ import annotations

from datetime import date

from .config import PeerConfig, Policy
from .extractor import extract
from .filings import (
    get_10k_text,
    get_earnings_release_99_1,
    get_recent_10ks,
    resolve_company,
)
from .models import CompsRow, Financials, Flag
from .policy import apply_policy
from .sec_client import SECClient
from .valuation import compute_row, get_price
from .verifier import quote_matches, verify_adjustment


def build_financials(
    sec: SECClient, ticker: str, name: str, cik: str, fy_end: str, cf: dict, info
) -> Financials:
    return Financials(
        ticker=ticker,
        name=name,
        cik=cik,
        fy_end=fy_end,
        fiscal_year=date.fromisoformat(fy_end).year,
        revenue=sec.revenue(cf, fy_end),
        operating_income=sec.operating_income(cf, fy_end),
        d_and_a=sec.depreciation_amortization(cf, fy_end),
        net_income=sec.net_income(cf, fy_end),
        total_debt=sec.total_debt(cf, fy_end),
        cash=sec.cash(cf, fy_end),
        shares_outstanding=sec.shares_outstanding(cf, fy_end),
        tenk_accession=info.accession_no,
        tenk_primary_doc=info.primary_document,
    )


def run(peers: PeerConfig, policy: Policy) -> tuple[list[CompsRow], dict, list[Flag]]:
    sec = SECClient()
    rows: list[CompsRow] = []
    bridges: dict[str, list[dict]] = {}
    flags: list[Flag] = []

    for ticker in peers.peers:
        try:
            cik, name = resolve_company(ticker)
        except Exception as e:
            flags.append(Flag(ticker=ticker, fy_end="", category="", reason="resolve_failed", detail=str(e)))
            continue

        cf = sec.get_companyfacts(cik)
        infos = get_recent_10ks(ticker, peers.num_years)
        price = get_price(ticker)

        financials: list[tuple] = []
        for info in infos:
            fin = build_financials(sec, ticker, name, cik, info.period_of_report, cf, info)
            financials.append((info, fin))

        # Market cap uses the most-recent FY's cover-page share count.
        shares_for_mcap = financials[0][1].shares_outstanding if financials else None

        ticker_bridges: list[dict] = []
        for info, fin in financials:
            fy_end = fin.fy_end
            tenk_text = get_10k_text(info)
            earnings = get_earnings_release_99_1(ticker, fy_end)
            earnings_text = earnings[0] if earnings else ""
            earnings_url = earnings[1] if earnings else ""
            if not earnings_text:
                flags.append(
                    Flag(ticker=ticker, fy_end=fy_end, category="", reason="missing_99_1",
                         detail="No 8-K 99.1 non-GAAP release found within 120 days of FYE.")
                )

            extraction = extract(ticker, fy_end, tenk_text, earnings_text)

            # Verify the company's own reported adjusted EBITDA quote (reference line).
            rep = extraction.reported_adjusted_ebitda
            rep_source = earnings_text if rep.source_doc == "8-K_99.1" else tenk_text
            if rep.amount is not None and not quote_matches(rep.source_quote, rep_source):
                flags.append(
                    Flag(ticker=ticker, fy_end=fy_end, category="reported_adj_ebitda",
                         reason="quote_not_found", detail=rep.source_quote[:160])
                )
                rep.amount = None

            verified: list = []
            for adj in extraction.adjustments:
                adj.fiscal_year = fin.fiscal_year
                adj.fy_end = fy_end
                flag = verify_adjustment(adj, tenk_text, earnings_text, sec, cf)
                if flag:
                    flag.ticker = ticker
                    flags.append(flag)
                else:
                    verified.append(adj)

            included, pflags = apply_policy(verified, policy, ticker, fy_end)
            flags.extend(pflags)

            adjusted = None
            if fin.reported_ebitda is not None:
                adjusted = fin.reported_ebitda + sum(a.signed_amount for a in included)

            rows.append(compute_row(fin, adjusted, price, shares_for_mcap))
            ticker_bridges.append(
                {
                    "fy_end": fy_end,
                    "fiscal_year": fin.fiscal_year,
                    "reported_ebitda": fin.reported_ebitda,
                    "adjusted_ebitda": adjusted,
                    "company_reported_adj_ebitda": rep.amount,
                    "tenk_url": info.url,
                    "earnings_url": earnings_url,
                    "adjustments": included,
                }
            )

        bridges[ticker] = ticker_bridges

    return rows, bridges, flags
