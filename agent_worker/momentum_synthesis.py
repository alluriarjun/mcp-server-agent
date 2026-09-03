"""Momentum commentary synthesis (design-doc.md Section 8.2 — Report Synthesis Agent slice).

Adds narrative color to an already-ranked momentum list (mcp_server.server.get_top_momentum)
via a single structured Claude API call. Deliberately NOT an agent that re-ranks or filters —
the numeric screening step stays plain Python/SQL (see docs/roadmap-status.md for that
discussion); this only interprets a small, already-decided set of results.
"""

from typing import Any

import anthropic
from pydantic import BaseModel, Field

from shared.config import settings


class MomentumCommentary(BaseModel):
    symbol: str
    rank: int
    headline: str = Field(description="One short punchy line, e.g. 'Breakout on volume'")
    rationale: str = Field(
        description="1-2 sentences explaining the move, grounded only in the numbers given"
    )


class MomentumCommentaryBatch(BaseModel):
    commentary: list[MomentumCommentary]


def add_commentary(ranked_stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach an LLM-generated headline/rationale to each already-ranked stock.

    `ranked_stocks` must already be sorted (e.g. get_top_momentum's output) — this
    function only interprets it, it never re-ranks or filters.
    """
    if not ranked_stocks:
        return []

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    numbered = [{"rank": i + 1, **stock} for i, stock in enumerate(ranked_stocks)]
    prompt = (
        "For each of these already-ranked momentum stocks, write a short headline and a "
        "1-2 sentence rationale grounded ONLY in the numbers given below. Do not invent "
        "news, catalysts, or any fact not present in the data.\n\n"
        f"{numbered}"
    )

    response = client.messages.parse(
        model=settings.llm_model_dev,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        output_format=MomentumCommentaryBatch,
    )

    commentary_by_rank = {c.rank: c for c in response.parsed_output.commentary}

    enriched = []
    for i, stock in enumerate(ranked_stocks):
        rank = i + 1
        commentary = commentary_by_rank.get(rank)
        enriched.append(
            {
                **stock,
                "rank": rank,
                "headline": commentary.headline if commentary else None,
                "rationale": commentary.rationale if commentary else None,
            }
        )
    return enriched
