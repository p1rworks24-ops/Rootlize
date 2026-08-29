"""Internal AI cost estimates. Reuses the existing eval rate env vars.

Not a user-facing price list. Plan budgets live in Supabase, not here.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal

from app.ai_budget import (
    KIND_TEXT_LLM,
    KIND_VISION,
    OPERATION_ACT_PLAN,
    OPERATION_FACTS_GENERATE,
    OPERATION_MEANING_SEARCH,
    AiRequestIntent,
)

# Same knobs as tools/vision_relevance_benchmark.py so product and eval
# share one rate source. Override in the environment when provider prices change.
_VISION_INPUT_ENV = "CAPIXE_VISION_INPUT_USD_PER_MTOK"
_VISION_OUTPUT_ENV = "CAPIXE_VISION_OUTPUT_USD_PER_MTOK"
_TEXT_INPUT_ENV = "CAPIXE_TEXT_INPUT_USD_PER_MTOK"
_TEXT_OUTPUT_ENV = "CAPIXE_TEXT_OUTPUT_USD_PER_MTOK"

_DEFAULT_VISION_INPUT = Decimal("0.20")
_DEFAULT_VISION_OUTPUT = Decimal("1.25")
_DEFAULT_TEXT_INPUT = Decimal("0.15")
_DEFAULT_TEXT_OUTPUT = Decimal("0.60")

# Conservative reservation pads. Not plan amounts.
_ESTIMATE_ENV = {
    OPERATION_FACTS_GENERATE: "CAPIXE_AI_ESTIMATE_MICROS_FACTS_GENERATE",
    OPERATION_MEANING_SEARCH: "CAPIXE_AI_ESTIMATE_MICROS_MEANING_SEARCH",
    OPERATION_ACT_PLAN: "CAPIXE_AI_ESTIMATE_MICROS_ACT_PLAN",
    "other": "CAPIXE_AI_ESTIMATE_MICROS_OTHER",
}
_DEFAULT_ESTIMATE_MICROS = {
    OPERATION_FACTS_GENERATE: 50_000,
    OPERATION_MEANING_SEARCH: 10_000,
    OPERATION_ACT_PLAN: 10_000,
    "other": 20_000,
}


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def tokens_to_micros(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    kind: str = KIND_TEXT_LLM,
) -> int:
    if kind == KIND_VISION:
        input_rate = _decimal_env(_VISION_INPUT_ENV, _DEFAULT_VISION_INPUT)
        output_rate = _decimal_env(_VISION_OUTPUT_ENV, _DEFAULT_VISION_OUTPUT)
    else:
        input_rate = _decimal_env(_TEXT_INPUT_ENV, _DEFAULT_TEXT_INPUT)
        output_rate = _decimal_env(_TEXT_OUTPUT_ENV, _DEFAULT_TEXT_OUTPUT)
    total = Decimal(max(0, int(input_tokens))) * input_rate + Decimal(
        max(0, int(output_tokens))
    ) * output_rate
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))


def provider_usd_to_micros(cost_usd: object) -> int | None:
    if cost_usd is None or cost_usd == "":
        return None
    try:
        value = Decimal(str(cost_usd))
    except Exception:
        return None
    if value < 0:
        return None
    return int((value * Decimal(1_000_000)).to_integral_value(rounding=ROUND_HALF_UP))


def actual_cost_micros(
    *,
    model: str = "",
    kind: str = KIND_TEXT_LLM,
    input_tokens: int = 0,
    output_tokens: int = 0,
    usage: dict | None = None,
) -> int:
    del model
    payload = usage if isinstance(usage, dict) else {}
    for key in ("cost", "total_cost", "cost_usd"):
        converted = provider_usd_to_micros(payload.get(key))
        if converted is not None:
            return converted
    prompt = int(payload.get("prompt_tokens") or payload.get("input_tokens") or input_tokens or 0)
    completion = int(
        payload.get("completion_tokens") or payload.get("output_tokens") or output_tokens or 0
    )
    return tokens_to_micros(input_tokens=prompt, output_tokens=completion, kind=kind)


def estimate_cost_micros(intent: AiRequestIntent) -> int:
    operation = str(intent.operation or "other")
    env_name = _ESTIMATE_ENV.get(operation, _ESTIMATE_ENV["other"])
    per_request = _int_env(env_name, _DEFAULT_ESTIMATE_MICROS.get(operation, _DEFAULT_ESTIMATE_MICROS["other"]))
    count = max(1, int(intent.request_count or 1))
    return per_request * count
