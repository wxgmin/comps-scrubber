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

    Returns (included_adjustments, flags). Disabled categories and unknown categories are
    dropped; recurring items, `requires_review` categories, and sign conflicts become flags.
    """
    included: list[Adjustment] = []
    flags: list[Flag] = []

    for adj in adjustments:
        if adj.category not in policy.categories:
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="unknown_category",
                    detail=f"'{adj.category}' is not defined in policy.yaml; excluded.",
                )
            )
            continue

        if not policy.enabled(adj.category):
            continue

        treatment = policy.treatment(adj.category)
        if treatment == "add_back":
            adj.sign = "add_back"
        elif treatment == "subtract":
            adj.sign = "subtract"
        elif treatment == "auto":
            # Use the XBRL gain/loss direction when it conflicts with the LLM's guess.
            if adj.sign_conflict and adj.xbrl_match is not None:
                adj.sign = "subtract" if adj.xbrl_match > 0 else "add_back"
        else:
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="unknown_treatment",
                    detail=f"treatment '{treatment}' is not add_back/subtract/auto.",
                )
            )
            continue

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
        if adj.sign_conflict:
            flags.append(
                Flag(
                    ticker=ticker,
                    fy_end=fy_end,
                    category=adj.category,
                    reason="sign_conflict",
                    detail=(
                        f"XBRL direction conflicts with sign; xbrl={adj.xbrl_match:,.0f} "
                        f"(gain>0, loss<0)."
                    ),
                )
            )
    return included, flags
