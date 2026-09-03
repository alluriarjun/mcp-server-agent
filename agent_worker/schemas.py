"""Structured output schemas for agent_worker graphs (CLAUDE.md: no unstructured
critical output — every agent output validates against a Pydantic schema before use).
"""

from typing import Literal

from pydantic import BaseModel, Field


class WatchlistOperation(BaseModel):
    """One proposed watchlist change, resolved from raw user input."""

    action: Literal["add", "remove", "create_watchlist"]
    watchlist_name: str
    symbol: str | None = Field(default=None, description="Required for add/remove")
    exchange: str = "NASDAQ"
    confidence: float = Field(ge=0, le=1, description="Resolver's confidence in this operation")
    note: str | None = Field(
        default=None, description="Why this was proposed, grounded in the raw input"
    )


class WatchlistUpdateProposal(BaseModel):
    """The resolve node's structured output: read-only, nothing applied yet."""

    operations: list[WatchlistOperation]
    unresolved: list[str] = Field(
        default_factory=list,
        description="Raw input lines/rows that could not be confidently resolved",
    )


class AppliedOperation(BaseModel):
    """One operation plus the result apply_watchlist_update actually returned."""

    operation: WatchlistOperation
    result: dict


class WatchlistImportSummary(BaseModel):
    """Final structured result returned to whatever triggered the import."""

    user_id: int
    proposal: WatchlistUpdateProposal
    applied: list[AppliedOperation]
    summary_text: str
