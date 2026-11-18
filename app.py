import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd
import streamlit as st

from comps.config import load_policy, load_peers, PeerConfig
from comps.pipeline import run
from comps.workbook import write_workbook

st.set_page_config(page_title="Comps Scrubber", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; }
      h1, h2, h3 { color: #1F4E79; }
      [data-testid="stSidebar"] { background-color: #f8f9fa; }
      .stMetric { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 14px; }
    </style>
    """,
    unsafe_allow_html=True,
)

ALL_CATEGORIES = [
    "Restructuring",
    "Impairment",
    "Litigation",
    "M&A_Transaction",
    "Asset_Sale",
    "StockBasedCompensation",
    "Other_NonRecurring",
]


def _fmt(v, dp=1) -> str:
    return "" if v is None else f"{v:,.{dp}f}"


def _dollars(v) -> str:
    return "" if v is None else f"${v:,.0f}"


def comps_to_dataframe(rows) -> pd.DataFrame:
    recs = []
    for r in rows:
        recs.append(
            {
                "Ticker": r.ticker,
                "Company": r.name,
                "FY": r.fiscal_year,
                "FY End": r.fy_end,
                "Price": _fmt(r.price, 2),
                "Mkt Cap ($M)": _fmt(r.market_cap / 1e6 if r.market_cap else None),
                "Revenue ($M)": _fmt(r.revenue / 1e6 if r.revenue else None),
                "Reported EBITDA ($M)": _fmt(r.reported_ebitda / 1e6 if r.reported_ebitda else None),
                "Adjusted EBITDA ($M)": _fmt(r.adjusted_ebitda / 1e6 if r.adjusted_ebitda else None),
                "Net Income ($M)": _fmt(r.net_income / 1e6 if r.net_income else None),
                "Total Debt ($M)": _fmt(r.total_debt / 1e6 if r.total_debt else None),
                "Cash ($M)": _fmt(r.cash / 1e6 if r.cash else None),
                "EV ($M)": _fmt(r.enterprise_value / 1e6 if r.enterprise_value else None),
                "EV/Revenue": _fmt(r.ev_revenue),
                "EV/EBITDA (Rpt)": _fmt(r.ev_ebitda_reported),
                "EV/EBITDA (Adj)": _fmt(r.ev_ebitda_adjusted),
                "P/E": _fmt(r.pe),
            }
        )
    return pd.DataFrame(recs)


def flags_to_dataframe(flags) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Ticker": f.ticker, "FY End": f.fy_end, "Category": f.category, "Reason": f.reason, "Detail": f.detail} for f in flags]
    )


def render_bridge(ticker: str, entries: list[dict]) -> None:
    st.subheader(ticker)
    for e in entries:
        st.markdown(f"**FY{e['fiscal_year']}** — ended {e['fy_end']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Reported EBITDA", _dollars(e.get("reported_ebitda")))
        c2.metric("Adjusted EBITDA (tool)", _dollars(e.get("adjusted_ebitda")))
        c3.metric("Company-reported", _dollars(e.get("company_reported_adj_ebitda")))
        adj = e.get("adjustments", [])
        if adj:
            st.markdown("**Adjustments**")
            for a in adj:
                sign = "+" if a.sign == "add_back" else "−"
                url = e.get("tenk_url") if a.source_document == "10-K" else e.get("earnings_url")
                st.markdown(
                    f"- {sign} {_dollars(a.amount)} · **{a.category}** · {a.source_section} "
                    + (f" · [open source ↗]({url})" if url else "")
                )
                st.markdown(f"> {a.source_quote}")
        else:
            st.caption("No non-recurring adjustments found / enabled for this period.")
        st.divider()


with st.sidebar:
    st.title("Comps Scrubber")
    st.caption("SEC-filing comps with an audit trail.")
    tickers_text = st.text_area(
        "Tickers (one per line)",
        value="\n".join(load_peers().peers),
        height=180,
    )
    num_years = st.slider("Fiscal years", 1, 5, 3)
    with st.expander("Adjustment policy", expanded=True):
        sbc = st.checkbox("Add back stock-based compensation", value=False)
        toggles = {}
        for cat in ALL_CATEGORIES:
            default = cat != "StockBasedCompensation"
            toggles[cat] = st.checkbox(cat.replace("_", " "), value=default)
    run_btn = st.button("Run comps", type="primary", use_container_width=True)

if run_btn:
    tickers = [t.strip().upper() for t in tickers_text.splitlines() if t.strip()]
    if not tickers:
        st.error("Enter at least one ticker.")
    else:
        peers = PeerConfig(peers=tickers, num_years=num_years, output=Path("output/comps_output.xlsx"))
        policy = load_policy()
        for cat, enabled in toggles.items():
            if cat in policy.categories:
                policy.categories[cat].enabled = enabled
        policy.categories["StockBasedCompensation"].enabled = sbc

        with st.spinner("Pulling SEC financials + filing text, running LLM extraction..."):
            rows, bridges, flags = run(peers, policy)
        write_workbook(rows, bridges, flags, peers.output)

        st.session_state["rows"] = rows
        st.session_state["bridges"] = bridges
        st.session_state["flags"] = flags
        st.session_state["output"] = peers.output

if "rows" in st.session_state:
    rows = st.session_state["rows"]
    bridges = st.session_state["bridges"]
    flags = st.session_state["flags"]
    output_path = st.session_state["output"]

    tab_comps, tab_bridges, tab_flags = st.tabs(["Comps table", "Bridges", "Flags"])

    with tab_comps:
        st.dataframe(comps_to_dataframe(rows), hide_index=True, use_container_width=True)
        if output_path.exists():
            with open(output_path, "rb") as f:
                st.download_button(
                    "⬇ Download Excel workbook",
                    f.read(),
                    file_name=output_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    with tab_bridges:
        if bridges:
            ticker = st.selectbox("Company", list(bridges.keys()))
            render_bridge(ticker, bridges[ticker])
        else:
            st.info("No bridges produced.")

    with tab_flags:
        df_flags = flags_to_dataframe(flags)
        if df_flags.empty:
            st.success("No flags — everything verified cleanly.")
        else:
            st.dataframe(df_flags, hide_index=True, use_container_width=True)
else:
    st.info("Enter tickers in the sidebar and click **Run comps** to build the analysis.")
