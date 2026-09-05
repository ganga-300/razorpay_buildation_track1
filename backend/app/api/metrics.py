"""LLM cost/usage reporting.

`GET /metrics/llm` exists to make the cost-reduction rules in
`app/agents/llm.py` / `app/agents/purchasing_agent.py` measurable rather than
argued about: how much each real call cost, how much prompt caching and model
tiering have saved, and how many intent calls never needed the network at all.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.metrics import LLMMetricsResponse
from app.services import llm_usage

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics/llm",
    response_model=LLMMetricsResponse,
    summary="Claude token usage, cost, and what the cost-reduction rules saved",
)
async def get_llm_metrics() -> LLMMetricsResponse:
    return LLMMetricsResponse.model_validate(llm_usage.snapshot())
