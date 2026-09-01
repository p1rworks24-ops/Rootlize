"""Public Prototype AI budget amounts. Enforcement stays on the server.

Anonymous Prototype users use plan_defaults.plan = 'prototype'.
Authenticated Free / Next / Pro rows are not overwritten for this.
Change Prototype amounts in that plan_defaults row (and matching entitlements),
not in scattered client magic numbers.
"""

from __future__ import annotations

# 1 USD = 1_000_000 micros. User-facing UI never shows these amounts.
ONBOARDING_BUDGET_MICROS = 1_250_000
REGULAR_MONTHLY_BUDGET_MICROS = 250_000
HARD_CAP_MICROS = 1_250_000
