"""AI Budget / Usage v1: percents, periods, reservation protocol, security, UI."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QProgressBar

from app.ai_budget import (
    AiBudgetExceeded,
    AiBudgetUnavailable,
    AiRequestIntent,
    AllowAllAiBudgetGate,
    check_ai_budget,
    finalize_ai_usage,
    release_ai_reservation,
    reset_ai_budget_gate_for_tests,
    set_ai_budget_gate,
)
from app.auth import AuthService, AuthStatus, MemoryCredentialStore, local_features_available
from app.auth.config import AuthClientConfig
from app.auth.device import DeviceService
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.http import HttpResponse
from app.auth.models import AccountSession, AuthUser, Entitlement
from app.budget.calc import can_reserve, usage_status, utc_month_bounds
from app.budget.display import format_reset_date
from app.budget.gate import CloudAiBudgetGate
from app.budget.ledger import InMemoryBudgetLedger
from app.budget.models import AIUsageStatus
from app.budget.pricing import actual_cost_micros, estimate_cost_micros, tokens_to_micros
from app.budget.prototype import (
    HARD_CAP_MICROS,
    ONBOARDING_BUDGET_MICROS,
    REGULAR_MONTHLY_BUDGET_MICROS,
)
from app.budget.service import BudgetService
from app.i18n import t
from app.ui.pages.account_page import AccountPage
from test_auth import FakeHttp, _user_payload


USER = "11111111-1111-1111-1111-111111111111"
SQL_PATH = Path(__file__).resolve().parent / "supabase" / "migrations" / "002_ai_budget_v1.sql"
PROTOTYPE_SQL_PATH = (
    Path(__file__).resolve().parent / "supabase" / "migrations" / "004_prototype_ai_budget_v1.sql"
)


def _monthly_only(
    ledger: InMemoryBudgetLedger,
    monthly_micros: int,
    **kwargs,
) -> None:
    """Keep legacy monthly tests from being opened by the onboarding bucket."""
    ledger.set_entitlement(
        USER,
        ai_monthly_budget_micros=monthly_micros,
        ai_onboarding_budget_micros=0,
        ai_lifetime_hard_cap_micros=monthly_micros,
        **kwargs,
    )


def _prototype_entitlement(ledger: InMemoryBudgetLedger, **kwargs) -> None:
    ledger.set_entitlement(
        USER,
        ai_monthly_budget_micros=REGULAR_MONTHLY_BUDGET_MICROS,
        ai_onboarding_budget_micros=ONBOARDING_BUDGET_MICROS,
        ai_lifetime_hard_cap_micros=HARD_CAP_MICROS,
        **kwargs,
    )


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_utc_month_bounds_first_of_month():
    start, end = utc_month_bounds(datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 9, 1)


def test_usage_percent_thresholds():
    cases = [
        (10_000_000, 0, 0, 100.0, False),
        (10_000_000, 5_000_000, 50.0, 50.0, False),
        (10_000_000, 8_000_000, 80.0, 20.0, False),
        (10_000_000, 9_500_000, 95.0, 5.0, False),
        (10_000_000, 10_000_000, 100.0, 0.0, True),
        (0, 0, 100.0, 0.0, True),
        (1_000_000, 1_500_000, 100.0, 0.0, True),
    ]
    for budget, used, expected_used, expected_remaining, reached in cases:
        status = usage_status(budget_micros=budget, used_micros=used)
        assert status.used_percent == expected_used
        assert status.remaining_percent == expected_remaining
        assert status.limit_reached is reached


def test_display_percent_truncates_fraction():
    status = usage_status(budget_micros=10_000_000, used_micros=6_320_000)
    assert status.used_percent == pytest.approx(63.2)
    assert status.display_used_percent == 63
    assert status.display_remaining_percent == 37


def test_warning_levels():
    assert usage_status(budget_micros=100, used_micros=79).warning_level == "normal"
    assert usage_status(budget_micros=100, used_micros=80).warning_level == "warning"
    assert usage_status(budget_micros=100, used_micros=95).warning_level == "critical"
    assert usage_status(budget_micros=100, used_micros=100).warning_level == "exhausted"


def test_period_switch_keeps_previous_period():
    clock = {"now": datetime(2026, 8, 15, tzinfo=timezone.utc)}
    ledger = InMemoryBudgetLedger(clock=lambda: clock["now"])
    _monthly_only(ledger, 1_000_000)
    reservation = ledger.reserve(USER, 200_000, "meaning_search")
    ledger.finalize(USER, reservation.reservation_id, 200_000)
    august = ledger.status(USER)
    assert august.used_micros == 200_000
    clock["now"] = datetime(2026, 9, 2, tzinfo=timezone.utc)
    september = ledger.status(USER)
    assert september.used_micros == 200_000
    assert september.reset_at is None
    assert (USER, date(2026, 8, 1)) in ledger.periods
    assert ledger.periods[(USER, date(2026, 8, 1))].used_micros == 200_000
    later = ledger.reserve(USER, 1, "meaning_search")
    ledger.finalize(USER, later.reservation_id, 1)
    assert ledger.periods[(USER, date(2026, 9, 1))].used_micros == 1
    assert ledger.status(USER).used_micros == 200_001


def test_plan_budget_change_keeps_used():
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 250_000, plan="free")
    reservation = ledger.reserve(USER, 200_000, "facts_generate")
    ledger.finalize(USER, reservation.reservation_id, 200_000)
    _monthly_only(ledger, 10_000_000, plan="pro")
    status = ledger.status(USER)
    assert status.used_micros == 200_000
    assert status.budget_micros == 10_000_000
    assert status.limit_reached is False
    assert can_reserve(status, 9_800_000) is True


def test_reserve_success_and_insufficient_budget():
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 1000)
    ok = ledger.reserve(USER, 400, "meaning_search")
    assert ok.reserved_micros == 400
    assert ledger.status(USER).reserved_micros == 400
    with pytest.raises(AiBudgetExceeded) as exc:
        ledger.reserve(USER, 700, "meaning_search")
    assert exc.value.reason == "limit_reached"


def test_finalize_actual_less_and_more_than_reserved():
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 10_000)
    first = ledger.reserve(USER, 1000, "act_plan")
    ledger.finalize(USER, first.reservation_id, 400)
    status = ledger.status(USER)
    assert status.used_micros == 400
    assert status.reserved_micros == 0
    second = ledger.reserve(USER, 500, "act_plan")
    ledger.finalize(USER, second.reservation_id, 800)
    status = ledger.status(USER)
    assert status.used_micros == 1200
    assert status.reserved_micros == 0


def test_release_and_duplicate_finalize_release():
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 5000)
    reservation = ledger.reserve(USER, 1000, "other")
    again = ledger.release(USER, reservation.reservation_id)
    assert again["already"] is False
    assert ledger.status(USER).reserved_micros == 0
    dup_release = ledger.release(USER, reservation.reservation_id)
    assert dup_release["already"] is True
    finalize_after_release = ledger.finalize(USER, reservation.reservation_id, 1000)
    assert finalize_after_release["status"] == "released"
    assert ledger.status(USER).used_micros == 0

    other = ledger.reserve(USER, 300, "other")
    ledger.finalize(USER, other.reservation_id, 300)
    dup_finalize = ledger.finalize(USER, other.reservation_id, 999)
    assert dup_finalize["already"] is True
    assert ledger.status(USER).used_micros == 300
    dup_release_finalized = ledger.release(USER, other.reservation_id)
    assert dup_release_finalized["status"] == "finalized"
    assert ledger.status(USER).used_micros == 300


def test_concurrent_reservations_do_not_overrun():
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 1000)
    results: list[object] = []

    def worker() -> None:
        try:
            results.append(ledger.reserve(USER, 600, "meaning_search"))
        except AiBudgetExceeded:
            results.append("denied")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    successes = [item for item in results if item != "denied"]
    assert len(successes) == 1
    status = ledger.status(USER)
    assert status.reserved_micros + status.used_micros <= 1000


def test_budget_service_rpc_does_not_send_user_id_or_write_tables():
    calls: list[tuple[str, str, dict | None]] = []

    class RpcHttp:
        def request(self, url, *, method="GET", headers=None, json_body=None):
            calls.append((method.upper(), url, json_body))
            if url.endswith("/rpc/reserve_ai_budget"):
                return HttpResponse(200, "", {"reservation_id": "res-1", "reserved_micros": 10})
            if url.endswith("/rpc/finalize_ai_usage"):
                return HttpResponse(200, "", {"status": "finalized"})
            if url.endswith("/rpc/release_ai_reservation"):
                return HttpResponse(200, "", {"status": "released"})
            if url.endswith("/rpc/get_ai_usage_status"):
                return HttpResponse(
                    200,
                    "",
                    {
                        "used_percent": 63.2,
                        "remaining_percent": 36.8,
                        "reset_at": "2026-09-01",
                        "limit_reached": False,
                        "budget_micros": 10_000_000,
                        "used_micros": 6_320_000,
                        "reserved_micros": 0,
                    },
                )
            raise AssertionError(url)

    service = BudgetService(
        rest_url="https://example.supabase.co/rest/v1",
        publishable_key="anon-public",
        http=RpcHttp(),
    )
    status = service.get_status("access-token")
    assert status.display_used_percent == 63
    reservation = service.reserve(
        "access-token",
        estimated_cost_micros=10,
        operation="meaning_search",
        provider="openai",
        model="x",
    )
    service.finalize("access-token", reservation.reservation_id, 8)
    service.release("access-token", reservation.reservation_id)
    for method, url, body in calls:
        assert method == "POST"
        assert "/rpc/" in url
        assert "/entitlements" not in url
        dumped = str(body)
        assert "user_id" not in dumped
        assert "screenshot" not in dumped.lower()
        assert "ocr" not in dumped.lower()
        assert "embedding" not in dumped.lower()


def test_budget_service_unauthenticated_and_offline():
    class Boom:
        def request(self, *_args, **_kwargs):
            raise AuthError(AuthErrorCode.NETWORK)

    service = BudgetService(rest_url="https://example.supabase.co/rest/v1", publishable_key="anon")
    unavailable = service.get_status("")
    assert unavailable.unavailable is True
    assert unavailable.limit_reached is True
    with pytest.raises(AiBudgetUnavailable):
        service.reserve("", estimated_cost_micros=1, operation="meaning_search")

    online = BudgetService(
        rest_url="https://example.supabase.co/rest/v1",
        publishable_key="anon",
        http=Boom(),
    )
    with pytest.raises(AiBudgetUnavailable):
        online.reserve("token", estimated_cost_micros=1, operation="meaning_search")


def test_cloud_gate_requires_session_and_uses_budget_service(monkeypatch):
    monkeypatch.setenv("CAPIXE_AI_DIRECT_PROVIDER", "1")
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 50_000)
    budget = BudgetService(ledger=ledger, ledger_user_id=USER)

    class FakeAuth:
        def __init__(self):
            self._session = AccountSession(
                status=AuthStatus.SIGNED_IN,
                user=AuthUser(USER, "ada@example.com"),
                access_token="access-token",
            )

        @property
        def session(self):
            return self._session.without_secrets()

        def bearer_token(self):
            return "access-token"

    gate = CloudAiBudgetGate(FakeAuth(), budget)
    set_ai_budget_gate(gate)
    check_ai_budget(AiRequestIntent(operation="meaning_search", kind="text_llm", model="x"))
    assert ledger.status(USER).reserved_micros > 0
    finalize_ai_usage(actual_cost_micros=12)
    assert ledger.status(USER).used_micros == 12
    check_ai_budget(AiRequestIntent(operation="act_plan", kind="text_llm"))
    release_ai_reservation()
    assert ledger.status(USER).reserved_micros == 0
    reset_ai_budget_gate_for_tests()


def test_cloud_gate_proxy_preflight_does_not_reserve(monkeypatch):
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)
    ledger = InMemoryBudgetLedger()
    _monthly_only(ledger, 50_000)
    budget = BudgetService(ledger=ledger, ledger_user_id=USER)
    budget.get_status("token", user_id=USER)

    class FakeAuth:
        def __init__(self):
            self._session = AccountSession(
                status=AuthStatus.SIGNED_IN,
                user=AuthUser(USER, "ada@example.com"),
                access_token="access-token",
            )

        @property
        def session(self):
            return self._session.without_secrets()

        def bearer_token(self):
            return "access-token"

    gate = CloudAiBudgetGate(FakeAuth(), budget)
    set_ai_budget_gate(gate)
    check_ai_budget(AiRequestIntent(operation="meaning_search", kind="text_llm"))
    assert ledger.status(USER).reserved_micros == 0
    reset_ai_budget_gate_for_tests()


def test_cloud_gate_offline_and_signed_out_deny_ai_not_local():
    budget = BudgetService()

    class SignedOut:
        session = AccountSession()

        def bearer_token(self):
            return ""

    set_ai_budget_gate(CloudAiBudgetGate(SignedOut(), budget))
    with pytest.raises(AiBudgetExceeded) as exc:
        check_ai_budget(AiRequestIntent(operation="meaning_search", kind="text_llm"))
    assert exc.value.reason == "not_authenticated"
    assert local_features_available(AccountSession()) is True

    class Offline:
        session = AccountSession(
            status=AuthStatus.OFFLINE_SESSION,
            user=AuthUser(USER, "ada@example.com"),
        )

        def bearer_token(self):
            return "stale"

    set_ai_budget_gate(CloudAiBudgetGate(Offline(), budget))
    with pytest.raises(AiBudgetUnavailable):
        check_ai_budget(AiRequestIntent(operation="facts_generate", kind="vision"))
    assert local_features_available(Offline.session) is True
    reset_ai_budget_gate_for_tests()
    set_ai_budget_gate(AllowAllAiBudgetGate())
    check_ai_budget(AiRequestIntent(operation="other", kind="vision"))


def test_sql_security_contract():
    sql = SQL_PATH.read_text(encoding="utf-8")
    assert "auth.uid()" in sql
    assert "p_user_id" not in sql.split("reserve_ai_budget")[1].split("returns")[0]
    assert "grant execute on function public.reserve_ai_budget" in sql.lower()
    assert "revoke all on function public.reserve_ai_budget" in sql.lower()
    assert "for insert" not in sql.lower() or "ai_usage_periods" in sql
    assert "ai_usage_events_select_own" in sql
    assert "for update to authenticated" not in sql
    assert "for insert to authenticated" not in sql
    assert "query" not in sql or "Do not store query" in sql
    assert "ai_monthly_budget_micros" in sql
    assert "security definer" in sql.lower()


def test_prototype_sql_hard_cap_contract():
    sql = PROTOTYPE_SQL_PATH.read_text(encoding="utf-8")
    assert "1250000" in sql
    assert "ai_lifetime_hard_cap_micros" in sql
    assert "ai_onboarding_budget_micros" in sql
    assert "ai_usage_lifetime" in sql
    assert "auth.uid()" in sql
    assert "p_user_id" not in sql.split("reserve_ai_budget")[1].split("returns")[0]
    assert "query" not in sql or "Do not store query" in sql
    assert "filename" not in sql.lower() or "Do not store" in sql
    assert "security definer" in sql.lower()
    assert "grant execute on function public.reserve_ai_budget" in sql.lower()
    assert "plan_display" in sql
    assert "Prototype" in sql


def test_client_cannot_patch_budget_through_budget_service():
    class Forbidden:
        def request(self, url, *, method="GET", headers=None, json_body=None):
            if method.upper() in {"PATCH", "PUT", "DELETE"}:
                raise AssertionError("client must not write usage tables")
            if "/entitlements" in url and method.upper() != "GET":
                raise AssertionError("client must not write entitlements")
            return HttpResponse(200, "", {"reservation_id": "x", "reserved_micros": 1})

    service = BudgetService(
        rest_url="https://example.supabase.co/rest/v1",
        publishable_key="anon",
        http=Forbidden(),
    )
    service.reserve("token", estimated_cost_micros=1, operation="meaning_search")


def test_actual_cost_prefers_provider_usd_then_tokens():
    assert actual_cost_micros(usage={"cost": 0.002}) == 2000
    assert tokens_to_micros(input_tokens=1_000_000, output_tokens=0, kind="text_llm") > 0
    intent = AiRequestIntent(operation="facts_generate", kind="vision")
    assert estimate_cost_micros(intent) > 0


def test_account_page_usage_states():
    _ensure_app()
    page = AccountPage()
    session = AccountSession(
        status=AuthStatus.SIGNED_IN,
        user=AuthUser(USER, "ada@example.com"),
        entitlement=Entitlement(plan="free"),
    )
    page.apply_session(session)
    assert t("account.plan.prototype") in page._plan.text()
    page.apply_usage(
        usage_status(
            budget_micros=HARD_CAP_MICROS,
            used_micros=975_000,
        )
    )
    assert t("account.ai_usage") in page._usage_title.text()
    assert "78%" in page._usage_used.text()
    assert "22%" in page._usage_remaining.text()
    assert "$" not in page._usage_used.text()
    assert "$" not in page._usage_remaining.text()
    assert not page._usage_reset.isVisibleTo(page)
    assert page.findChild(QProgressBar, "accountUsageBar").value() == 78
    assert not page._usage_hint.isVisibleTo(page)

    page.apply_usage(usage_status(budget_micros=100, used_micros=80))
    assert page._usage_hint.isVisibleTo(page)
    assert t("account.ai_warning") in page._usage_hint.text()

    page.apply_usage(usage_status(budget_micros=100, used_micros=96))
    assert t("account.ai_critical") in page._usage_hint.text()

    page.apply_usage(usage_status(budget_micros=HARD_CAP_MICROS, used_micros=HARD_CAP_MICROS))
    assert t("account.ai.limit_reached") in page._usage_hint.text()
    assert t("account.ai.limit_reached_body") in page._usage_hint.text()
    assert "0%" in page._usage_remaining.text()
    assert "reset" not in page._usage_hint.text().lower()
    assert "$" not in page._usage_hint.text()

    page.apply_usage(AIUsageStatus.unavailable_status())
    assert t("account.ai.verification_unavailable") in page._usage_used.text()
    page.close()


def test_limit_reached_user_message_hides_amounts():
    from app.ai_budget import format_budget_user_message

    text = format_budget_user_message(
        AiBudgetExceeded(reason="limit_reached", reset_at=date(2026, 9, 1))
    )
    assert "AI usage limit reached." in text
    assert "You've reached the AI usage limit for this prototype." in text
    assert "Sep 1" not in text
    assert "reset" not in text.lower()
    assert "$" not in text
    assert "micros" not in text


def test_reset_date_ja():
    assert format_reset_date(date(2026, 9, 1), locale="ja") == "9月1日"


def test_auth_regression_email_and_local_features(tmp_path):
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            {},
        ]
    )
    service = AuthService(
        AuthClientConfig("https://example.supabase.co", "anon-public"),
        store=MemoryCredentialStore(),
        devices=DeviceService(tmp_path / "device.json"),
        http=http,
        open_url=lambda _url: None,
    )
    signed = service.sign_in_email("ada@example.com", "secret")
    assert signed.status == AuthStatus.SIGNED_IN
    assert signed.email == "ada@example.com"
    assert local_features_available(signed) is True
    assert service.bearer_token()
    out = service.sign_out()
    assert out.status == AuthStatus.SIGNED_OUT
    assert local_features_available(out) is True


def test_prototype_hard_cap_limits_regular_after_onboarding_spend():
    ledger = InMemoryBudgetLedger()
    _prototype_entitlement(ledger)
    first = ledger.reserve(USER, 1_000_000, "facts_generate")
    ledger.finalize(USER, first.reservation_id, 1_000_000)
    status = ledger.status(USER)
    assert status.used_micros == 1_000_000
    assert status.budget_micros == HARD_CAP_MICROS
    assert status.display_used_percent == 80
    assert status.display_remaining_percent == 20
    assert status.limit_reached is False
    ok = ledger.reserve(USER, 250_000, "meaning_search")
    ledger.finalize(USER, ok.reservation_id, 250_000)
    assert ledger.status(USER).used_micros == 1_250_000
    assert ledger.status(USER).limit_reached is True
    with pytest.raises(AiBudgetExceeded) as exc:
        ledger.reserve(USER, 1, "act_plan")
    assert exc.value.reason == "limit_reached"


def test_prototype_hard_cap_clips_regular_when_onboarding_used_1_20():
    ledger = InMemoryBudgetLedger()
    _prototype_entitlement(ledger)
    first = ledger.reserve(USER, 1_200_000, "facts_generate")
    ledger.finalize(USER, first.reservation_id, 1_200_000)
    ok = ledger.reserve(USER, 50_000, "meaning_search")
    assert ok.reserved_micros == 50_000
    with pytest.raises(AiBudgetExceeded):
        ledger.reserve(USER, 1, "meaning_search")


def test_prototype_month_reset_cannot_exceed_hard_cap():
    clock = {"now": datetime(2026, 8, 15, tzinfo=timezone.utc)}
    ledger = InMemoryBudgetLedger(clock=lambda: clock["now"])
    _prototype_entitlement(ledger)
    first = ledger.reserve(USER, 1_200_000, "facts_generate")
    ledger.finalize(USER, first.reservation_id, 1_200_000)
    clock["now"] = datetime(2026, 9, 2, tzinfo=timezone.utc)
    september = ledger.status(USER)
    assert september.used_micros == 1_200_000
    assert september.limit_reached is False
    assert september.reset_at is None
    ok = ledger.reserve(USER, 50_000, "act_plan")
    ledger.finalize(USER, ok.reservation_id, 50_000)
    assert ledger.status(USER).used_micros == 1_250_000
    with pytest.raises(AiBudgetExceeded):
        ledger.reserve(USER, 1, "act_plan")


def test_entitlement_plan_label_is_prototype_not_free():
    assert Entitlement(plan="free").plan_label == t("account.plan.prototype")
    assert Entitlement(plan="free").plan == "free"
    assert Entitlement(plan="free").plan_label != "Free"
