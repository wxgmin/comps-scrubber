from __future__ import annotations

from .config import Policy
from .models import Adjustment, Flag


def apply_policy(
    adjustments: list[Adjustment],
    policy: Policy,
    ticker: str,
    fy_end: str,
) -> tuple[list[Adjustment], list[Flag]]:
    """Normalize a company's raw adjustments through the shared policy.

    Returns (included_adjustments, flags). Disabled categories are dropped; recurring
    items and `requires_review` categories are surfaced as flags for human judgement.
    """
    included: list[Adjustment] = []
    flags: list[Flag] = []
    for adj in adjustments:
        if not policy.enabled(adj.category):
            continue
        treatment = policy.treatment(adj.category)
        if treatment == "add_back":
            adj.sign = "add_back"
        elif treatment == "subtract":
            adj.sign = "subtract"
        # "auto" (asset sales) keeps the LLM's gain/loss direction.
        included.append(adj)

        if adj.is_recurring:
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="recurring_item",
                    detail=f"'{adj.category}' appears recurring; confirm it should be treated as one-off.",
                )
            )
        if policy.requires_review(adj.category):
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="requires_review",
                    detail=adj.rationale[:160],
                )
            )
        if adj.verification_status == "xbrl_mismatch":
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="xbrl_mismatch",
                    detail=f"quote={adj.amount:,.0f} xbrl={adj.xbrl_match:,.0f}",
                )
            )
    return included, flags
