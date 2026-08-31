"""Guided Prototype Experience: state, progression, overlay, and safety."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QWidget,
)

from app.prototype_tour.anchors import AnchorRegistry
from app.prototype_tour.controller import TourController
from app.prototype_tour.entitlement import PrototypeEntitlement
from app.prototype_tour.events import TourEventBus, emit_tour_event, install_tour_bus, uninstall_tour_bus
from app.prototype_tour.models import (
    ACTION_START_PREPARING,
    ANCHOR_AUTOMATION_ADD_BLOCK,
    ANCHOR_AUTOMATION_BUILDER,
    ANCHOR_AUTOMATION_FOLDER,
    ANCHOR_AUTOMATION_FIT,
    ANCHOR_AUTOMATION_LIST_RUN,
    ANCHOR_AUTOMATION_NAV,
    ANCHOR_AUTOMATION_NEW,
    ANCHOR_AUTOMATION_PARAM,
    ANCHOR_AUTOMATION_RUN,
    ANCHOR_AUTOMATION_SAVE,
    ANCHOR_IMAGES_ASK_AI,
    ANCHOR_IMAGES_ASK_AI_BUTTON,
    ANCHOR_IMAGES_FAVORITE,
    ANCHOR_IMAGES_NAV,
    ANCHOR_IMAGES_ORGANIZE,
    ANCHOR_IMAGES_SEARCH,
    ANCHOR_IMAGES_TAGS,
    ANCHOR_SEARCH_RESULTS_GRID,
    EVENT_AI_PREPARATION_STARTED,
    EVENT_AI_TUTORIAL_COMPLETED,
    EVENT_AI_TUTORIAL_SKIPPED,
    EVENT_AI_TUTORIAL_STARTED,
    EVENT_AUTOMATION_TUTORIAL_COMPLETED,
    EVENT_AUTOMATION_TUTORIAL_SKIPPED,
    EVENT_AUTOMATION_TUTORIAL_STARTED,
    EVENT_BASIC_SEARCH_COMPLETED,
    EVENT_FEEDBACK_DISMISSED,
    EVENT_FEEDBACK_SHOWN,
    EVENT_FEEDBACK_SUBMITTED,
    EVENT_FOLDER_SELECTED,
    EVENT_MEANING_SEARCH_COMPLETED,
    EVENT_ONBOARDING_COMPLETED,
    EVENT_ONBOARDING_SKIPPED,
    EVENT_ONBOARDING_STARTED,
    EVENT_PROTOTYPE_STARTED,
    EVENT_TAG_ADDED,
    EVENT_TUTORIAL_COMPLETED,
    EVENT_WORKFLOW_RUN,
    EVENT_WORKFLOW_SAVED,
    STEP_AI_ACTION,
    STEP_AI_CONSENT,
    STEP_AI_DONE,
    STEP_AI_IMAGES_RETURN,
    STEP_AI_INTRO,
    STEP_ASK_AI_OPEN,
    STEP_AI_PREP,
    STEP_AI_PREVIEW,
    STEP_AI_RESULT,
    STEP_AI_TAG,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_SKIPPED,
    STEP_ACT,
    STEP_AUTOMATE,
    STEP_AUTOMATE_IMAGES_RETURN,
    STEP_AUTOMATE_INTRO,
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_FAVORITE,
    STEP_FIND,
    STEP_FOLDER,
    STEP_IDLE,
    STEP_IMAGES_GUIDE,
    STEP_LOCAL_PREP,
    STEP_WELCOME,
    STEP_MEANING_CONFIRM,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    STEP_TAGS_SORT,
    UI_ACT_COMPLETED,
    UI_ACT_PREVIEW_SHOWN,
    UI_ASK_AI_OPENED,
    UI_AUTOMATION_BLOCK_CHANGED,
    UI_AUTOMATION_FITTED,
    UI_AUTOMATION_OPENED,
    UI_AUTOMATION_PAGE_SHOWN,
    UI_AUTOMATION_RUN,
    UI_AUTOMATION_RUN_FINISHED,
    UI_AUTOMATION_SAVED,
    UI_FAVORITE_CHANGED,
    UI_FIND_FAILED,
    UI_FIND_FINISHED,
    UI_FOLDER_SELECTED,
    UI_IMAGES_PAGE_SHOWN,
    UI_SELECTION_CHANGED,
    UI_TAG_ADDED,
)
from app.prototype_tour.state.analytics import TourAnalytics
from app.prototype_tour.state.feedback import FeedbackStore, build_feedback
from app.prototype_tour.state.store import TourStore, migrate_legacy_record, retire_ask_ai_tutorial
from app.prototype_tour.steps import (
    AI_SEQUENCE,
    AUTOMATION_SEQUENCE,
    CORE_SEQUENCE,
    TOUR_SEQUENCE,
    TOUR_STEPS,
    step_spec,
)
from app.ui.tour_overlay import (
    RING,
    TourOverlay,
    click_block_region,
    paint_tour_overlay,
    spotlight_cutout_path,
)
from app.ui.tour_popover import TourPopover, popover_position, wrapped_text_height
from app.ui.tour_welcome import TourFeedbackCard, TourWelcomeCard
from app.ui.pages.settings_page import SettingsPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _controller(tmp_path: Path, host=None, *, authenticated: bool | None = None) -> TourController:
    auth_provider = None
    if authenticated is True:
        auth_provider = lambda: {"user_id": "user-1"}
    elif authenticated is False:
        auth_provider = lambda: {}
    return TourController(
        store=TourStore(tmp_path / "tour.json"),
        analytics=TourAnalytics(tmp_path / "events.jsonl"),
        feedback=FeedbackStore(tmp_path / "feedback.jsonl"),
        entitlement=PrototypeEntitlement(),
        host=host,
        auth_provider=auth_provider,
    )


def _names(tour: TourController) -> list[str]:
    return [event.event_name for event in tour.analytics.events]


def _finish_local_prep(tour: TourController) -> None:
    if tour.view().guide.step_id == STEP_FOLDER:
        tour.handle_event(UI_FOLDER_SELECTED, {})
    if tour.view().guide.step_id == STEP_LOCAL_PREP:
        tour.next_fallback()


def _finish_core(tour: TourController) -> None:
    if (
        tour.view().active is False
        or tour.view().guide.step_id in {STEP_IDLE, STEP_WELCOME}
    ):
        tour.start()
    _finish_local_prep(tour)
    if tour.view().guide.step_id == STEP_IMAGES_GUIDE:
        tour.next_fallback()


def _open_ask_ai(tour: TourController) -> None:
    if tour.view().active and tour.view().guide.step_id == STEP_IMAGES_GUIDE:
        tour.next_fallback()
    tour.handle_event(UI_ASK_AI_OPENED, {})


def _finish_ai(tour: TourController) -> None:
    tour.store.complete_ai()
    tour.stop()


def _open_automation(tour: TourController) -> None:
    tour.handle_event(UI_AUTOMATION_PAGE_SHOWN, {})
    if tour.view().guide.step_id == STEP_AUTOMATE_PAGE:
        tour.next_fallback()
    tour.handle_event(UI_AUTOMATION_OPENED, {})


def _build_automation(tour: TourController) -> None:
    if tour.view().guide.step_id == STEP_AUTOMATE_INTRO:
        tour.next_fallback()
    _open_automation(tour)
    tour.handle_event(UI_AUTOMATION_BLOCK_CHANGED, {"has_folder": True})
    tour.next_fallback()
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_text_search": True},
    )
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_text_search": True, "has_search_query": True},
    )
    tour.next_fallback()
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {
            "has_folder": True,
            "has_text_search": True,
            "has_search_query": True,
            "has_add_tag": True,
            "has_tag_value": True,
        },
    )
    tour.handle_event(UI_AUTOMATION_FITTED, {})
    tour.next_fallback()
    tour.next_fallback()


def test_store_starts_not_started_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "tour.json"
    store = TourStore(path)
    assert store.status == STATUS_NOT_STARTED
    assert store.should_auto_start()
    store.start(STEP_FIND)
    assert store.status == STATUS_IN_PROGRESS
    loaded = TourStore(path)
    assert loaded.status == STATUS_IN_PROGRESS
    assert loaded.record.current_step == STEP_FIND
    loaded.complete()
    assert TourStore(path).status == STATUS_COMPLETED
    skipped = TourStore(tmp_path / "other.json")
    skipped.skip()
    assert skipped.status == STATUS_SKIPPED


def test_analytics_rejects_query_and_unknown_events(tmp_path: Path) -> None:
    analytics = TourAnalytics(tmp_path / "events.jsonl")
    assert analytics.record("query", session_id="s") is None
    assert analytics.record("image_path", session_id="s") is None
    event = analytics.record(EVENT_ONBOARDING_STARTED, session_id="s")
    assert event is not None
    raw = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "onboarding_started" in raw
    assert "query" not in raw
    assert "C:\\\\" not in raw


def test_analytics_migrates_legacy_event_names(tmp_path: Path) -> None:
    analytics = TourAnalytics(tmp_path / "events.jsonl")
    event = analytics.record("tour_started", session_id="s")
    assert event is not None
    assert event.event_name == EVENT_ONBOARDING_STARTED
    mapped = analytics.record("chapter_ai_started", session_id="s")
    assert mapped is not None
    assert mapped.event_name == EVENT_AI_TUTORIAL_STARTED
    raw = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "onboarding_started" in raw
    assert "tour_started" not in raw
    assert "ai_tutorial_started" in raw
    assert '"chapter_ai_started"' not in raw


def test_tag_added_is_not_mapped_to_favorite(tmp_path: Path) -> None:
    analytics = TourAnalytics(tmp_path / "events.jsonl")
    event = analytics.record("tag_added", session_id="s")
    assert event is not None
    assert event.event_name == EVENT_TAG_ADDED
    raw = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "tag_added" in raw
    assert "favorite_added" not in raw


def test_product_feature_events_record_outside_tour(tmp_path: Path) -> None:
    tour = _controller(tmp_path, authenticated=True)
    tour.handle_event(UI_FIND_FINISHED, {"ok": True, "result_count": 1, "kind": "basic"})
    tour.handle_event(UI_FIND_FINISHED, {"ok": True, "result_count": 2, "kind": "meaning"})
    tour.handle_event(UI_TAG_ADDED, {})
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": False})
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    names = _names(tour)
    assert names.count(EVENT_BASIC_SEARCH_COMPLETED) == 1
    assert names.count(EVENT_MEANING_SEARCH_COMPLETED) == 1
    assert names.count(EVENT_TAG_ADDED) == 1
    assert names.count(EVENT_WORKFLOW_SAVED) == 1
    assert names.count(EVENT_WORKFLOW_RUN) == 1


def test_empty_or_failed_search_is_not_recorded(tmp_path: Path) -> None:
    tour = _controller(tmp_path, authenticated=True)
    tour.handle_event(UI_FIND_FINISHED, {"ok": False, "result_count": 0, "kind": "basic"})
    assert _names(tour) == []


def test_feedback_strips_disallowed_choice_and_keeps_safe_fields() -> None:
    payload = build_feedback(
        session_id="sess",
        most_useful="search",
        would_use="definitely",
        easier_than_current="harder",
        willingness_to_pay="maybe",
        confusing_text="  the confirm step  ",
        user_id="user-1",
    )
    fields = payload.public_fields()
    assert set(fields) == {
        "prototype_session_id",
        "completed_at",
        "most_useful",
        "would_use",
        "easier_than_current",
        "confusing_text",
        "willingness_to_pay",
        "app_version",
        "user_id",
        "feedback_version",
    }
    assert "path" not in fields
    assert "query" not in fields
    assert "feature_feedback" not in fields
    assert payload.most_useful == "search"
    legacy = build_feedback(session_id="s", most_useful_step="find")
    assert legacy.most_useful == "search"
    dirty = build_feedback(session_id="s", most_useful="C:/secret.png")
    assert dirty.most_useful == ""


def test_authentication_start_path_and_introduction(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=False)
    assert tour.should_auto_start()
    tour.offer_welcome()
    assert tour.view().active is False
    assert tour.store.status == STATUS_NOT_STARTED
    tour.on_signed_in()
    assert tour.view().active is False
    auth_provider = lambda: {"user_id": "user-1"}
    tour.auth_provider = auth_provider
    tour.on_signed_in()
    assert tour.view().guide.step_id == STEP_WELCOME
    assert tour.view().guide.mode == "welcome"
    assert EVENT_ONBOARDING_STARTED not in _names(tour)
    tour.start()
    assert tour.view().guide.step_id == STEP_FOLDER
    assert EVENT_ONBOARDING_STARTED in _names(tour)


def test_unauthenticated_start_stays_on_auth(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=False)
    tour.start()
    assert tour.view().active is False
    assert tour.store.status == STATUS_NOT_STARTED
    assert EVENT_ONBOARDING_STARTED not in _names(tour)
    tour.skip()
    assert tour.view().active is False
    assert tour.store.status == STATUS_NOT_STARTED


def test_sign_in_gate_has_no_navigation_or_skip() -> None:
    from app.ui.pages.sign_in_gate import SignInGatePage

    _app()
    page = SignInGatePage()
    assert page.objectName() == "signInGatePage"
    labels = [child.text().lower() for child in page.findChildren(QPushButton)]
    assert not any("skip" in text for text in labels)
    assert not any("images" in text or "automation" in text or "settings" in text for text in labels)
    page.close()


def test_needs_sign_in_gate_until_authenticated(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    monkeypatch.setattr("app.ui.main_window.is_frozen", lambda: True)
    window = SimpleNamespace(
        _auth_gate_released=False,
        _account_controller=SimpleNamespace(
            session=SimpleNamespace(is_authenticated=False),
            service=SimpleNamespace(has_stored_session=lambda: False, configured=True),
        ),
    )
    assert MainWindow._needs_sign_in_gate(window) is True
    window._account_controller.session.is_authenticated = True
    assert MainWindow._needs_sign_in_gate(window) is False
    window._account_controller.session.is_authenticated = False
    window._auth_gate_released = True
    assert MainWindow._needs_sign_in_gate(window) is False
    window._auth_gate_released = False
    window._account_controller.service.has_stored_session = lambda: True
    assert MainWindow._needs_sign_in_gate(window) is False
    monkeypatch.setattr("app.ui.main_window.is_frozen", lambda: False)
    window._account_controller.service.has_stored_session = lambda: False
    assert MainWindow._needs_sign_in_gate(window) is False


def test_first_launch_start_and_interaction_progression(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    assert tour.should_auto_start()
    tour.offer_welcome()
    assert host.images >= 1
    assert tour.store.status == STATUS_NOT_STARTED
    assert tour.view().guide.step_id == STEP_WELCOME
    assert tour.view().guide.mode == "welcome"
    tour.start()
    assert tour.store.status == STATUS_IN_PROGRESS
    assert tour.view().guide.step_id == STEP_FOLDER
    assert EVENT_ONBOARDING_STARTED in _names(tour)
    assert tour.view().guide.phase == "core"
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_FOLDER

    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert EVENT_FOLDER_SELECTED in _names(tour)
    assert host.prep_starts == 0
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    guide = tour.view().guide
    assert "filename" in guide.body.lower()
    assert "tag" in guide.body.lower()
    assert ANCHOR_IMAGES_FAVORITE not in guide.anchors
    assert ANCHOR_IMAGES_ORGANIZE not in guide.anchors
    tour.handle_event(UI_FIND_FINISHED, {"ok": True, "result_count": 2, "kind": "basic"})
    tour.handle_event(UI_SELECTION_CHANGED, {"selected_count": 1})
    tour.handle_event(UI_FAVORITE_CHANGED, {"ok": True, "favorited": True})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.next_fallback()
    assert tour.store.status == STATUS_COMPLETED
    assert tour.view().active is False
    assert EVENT_ONBOARDING_COMPLETED in _names(tour)
    assert EVENT_TUTORIAL_COMPLETED not in _names(tour)
    assert tour.store.record.ai_status == STATUS_NOT_STARTED
    assert tour.store.record.automation_status == STATUS_NOT_STARTED

    tour.handle_event(UI_ASK_AI_OPENED, {})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert EVENT_AI_TUTORIAL_STARTED in _names(tour)
    assert host.prep_starts == 0
    assert host.consent == 1
    assert tour.store.record.ai_status == STATUS_IN_PROGRESS
    assert tour.store.record.automation_status == STATUS_NOT_STARTED
    tour.next_fallback()
    assert tour.store.record.ai_status == STATUS_COMPLETED
    assert tour.view().active is False

    tour.handle_event(UI_AUTOMATION_PAGE_SHOWN, {})
    assert tour.view().guide.step_id == STEP_AUTOMATE_PAGE
    assert EVENT_AUTOMATION_TUTORIAL_STARTED in _names(tour)
    tour.next_fallback()
    tour.handle_event(UI_AUTOMATION_OPENED, {})
    assert tour.view().guide.step_id == STEP_AUTOMATE
    tour.handle_event(UI_AUTOMATION_BLOCK_CHANGED, {"has_folder": True})
    assert "folder" in tour.view().guide.title.lower() or "folder" in tour.view().guide.body.lower()
    tour.next_fallback()
    tour.handle_event(UI_AUTOMATION_BLOCK_CHANGED, {"has_folder": True, "has_text_search": True})
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_text_search": True, "has_search_query": True},
    )
    tour.next_fallback()
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {
            "has_folder": True,
            "has_text_search": True,
            "has_search_query": True,
            "has_add_tag": True,
            "has_tag_value": True,
        },
    )
    tour.handle_event(UI_AUTOMATION_FITTED, {})
    tour.next_fallback()
    assert "workflow" in (tour.view().guide.title + tour.view().guide.body).lower()
    tour.next_fallback()
    assert tour.view().guide.anchors == (ANCHOR_AUTOMATION_SAVE,)
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    assert tour.store.status == STATUS_COMPLETED
    assert tour.view().guide.step_id == STEP_AUTOMATE_SAVE_CONFIRM
    assert EVENT_WORKFLOW_SAVED in _names(tour)
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_AUTOMATE_RUN
    assert tour.view().guide.anchors == (ANCHOR_AUTOMATION_LIST_RUN, ANCHOR_AUTOMATION_RUN)

    tour.handle_event(UI_AUTOMATION_RUN, {})
    assert "Confirm" in tour.view().guide.title
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": False})
    assert tour.view().guide.step_id == STEP_AUTOMATE_RUN
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert tour.view().guide.step_id == STEP_AUTOMATE_RUN
    assert "finished" in tour.view().guide.title.lower() or "完了" in tour.view().guide.title
    assert EVENT_WORKFLOW_RUN in _names(tour)

    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_AUTOMATE_IMAGES_RETURN
    tour.next_fallback()
    assert tour.store.record.automation_status == STATUS_COMPLETED
    assert EVENT_AUTOMATION_TUTORIAL_COMPLETED in _names(tour)
    assert EVENT_TUTORIAL_COMPLETED in _names(tour)
    assert tour.view().active is False

    tour.open_feedback()
    assert tour.view().guide.mode == "feedback"
    tour.submit_feedback(
        {
            "most_useful": "search",
            "would_use": "probably",
            "easier_than_current": "much_easier",
            "willingness_to_pay": "maybe",
            "confusing_text": "nothing",
        }
    )
    assert tour.view().guide.mode == "thanks"
    assert EVENT_FEEDBACK_SUBMITTED in _names(tour)
    tour.stop()
    assert tour.view().active is False
    assert tour.view().guide.mode == "guide" or tour.view().guide.step_id == STEP_IDLE


def test_skip_and_replay(tmp_path: Path) -> None:
    tour = _controller(tmp_path, authenticated=True)
    tour.offer_welcome()
    tour.skip()
    assert tour.store.status == STATUS_SKIPPED
    assert tour.store.record.ai_status == STATUS_NOT_STARTED
    assert tour.view().active is False
    assert EVENT_ONBOARDING_SKIPPED in _names(tour)
    tour.replay()
    assert tour.view().guide.step_id == STEP_WELCOME
    tour.start()
    assert tour.view().guide.step_id == STEP_FOLDER


def test_close_offers_feedback(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    assert tour.intercept_close() is True
    assert tour.view().guide.mode == "feedback"
    assert EVENT_FEEDBACK_SHOWN in _names(tour)
    assert tour.intercept_close() is True
    tour.decline_feedback()
    assert tour.view().active is False
    assert tour.store.record.feedback_offered is True
    assert EVENT_FEEDBACK_DISMISSED in _names(tour)
    assert host.app_closes == 1
    assert tour.intercept_close() is False


def test_next_does_not_skip_required_gates(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.back()
    assert tour.view().guide.step_id == STEP_FOLDER


def test_entitlement_is_separate_hint_only() -> None:
    entitlement = PrototypeEntitlement()
    assert entitlement.should_request_more_ai()
    entitlement.note_call()
    entitlement.note_call()
    assert entitlement.should_request_more_ai() is False
    assert entitlement.used == 2


def test_event_bus_is_noop_without_install() -> None:
    emit_tour_event(UI_FIND_FINISHED, ok=True, result_count=3)


def test_event_bus_forwards_to_controller(tmp_path: Path) -> None:
    _app()
    app = QApplication.instance()
    bus = install_tour_bus(app, TourEventBus())
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.attach_bus(bus)
    tour.next_fallback()
    emit_tour_event(UI_FOLDER_SELECTED)
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    uninstall_tour_bus(app)


def test_welcome_card_and_feedback_form() -> None:
    _app()
    welcome = TourWelcomeCard()
    buttons = [child.text() for child in welcome.findChildren(QPushButton)]
    assert "Start" in buttons
    assert "Skip tour" in buttons
    item_text = " ".join(child.text() for child in welcome.findChildren(QLabel))
    assert "Find images" in item_text
    assert "meaning" in item_text.lower()
    assert "tags" in item_text.lower()
    assert "Automation" in item_text
    assert "Your Local Workspace." in item_text
    body = welcome.findChild(QLabel, "tourWelcomeBody")
    assert body is not None
    assert "images on your PC" in body.text()
    assert "without moving them to the cloud" in body.text()
    assert welcome.width() >= 460
    form = TourFeedbackCard()
    labels = [child.text() for child in form.findChildren(QLabel)]
    joined = " ".join(labels)
    assert "most useful" in joined
    assert "own images" in joined
    assert "confusing" in joined
    assert "easier" in joined
    assert "wish Capixe" not in joined
    assert "wish Rootlize" not in joined
    assert labels.index("Compared with how you manage images today, does this feel easier?") < labels.index(
        "What was the most confusing part?"
    )
    radios = form.findChildren(QRadioButton)
    assert len(radios) == 16
    assert any(radio.text() == "Search" for radio in radios)
    assert any(radio.text() == "Favorites / Organization" for radio in radios)
    first = next(radio for radio in radios if radio.text() == "Search")
    second = next(radio for radio in radios if radio.text() == "Ask AI")
    first.setChecked(True)
    second.setChecked(True)
    assert first.isChecked() is False
    assert second.isChecked() is True
    assert first.property("selected") is False
    assert second.property("selected") is True
    indicator = first._indicator_rect()
    assert indicator.width() >= 12
    assert indicator.height() >= 12
    actions = [child.text() for child in form.findChildren(QPushButton)]
    assert "Exit without feedback" in actions
    assert "Send feedback & exit" in actions


def test_settings_has_replay_prototype_tour(tmp_path: Path) -> None:
    _app()
    page = SettingsPage(
        {
            "screenshot_dir": str(tmp_path),
            "window_width": 1600,
            "window_height": 900,
            "filename_template": "{date}_{time}",
            "current_folder": "Default",
            "save_folder": "Default",
        },
        tmp_path,
    )
    texts = [child.text() for child in page.findChildren(QPushButton)]
    assert "Replay getting started" in texts
    assert "Ask AI explanation" in texts
    assert "Replay Ask AI guide" in texts
    assert "Replay Automation guide" in texts
    seen = []
    page.replay_tour_requested.connect(lambda: seen.append("core"))
    page.replay_ai_tour_requested.connect(lambda: seen.append("ai_tour"))
    page.replay_automation_tour_requested.connect(lambda: seen.append("automation"))
    page.ask_ai_explanation_requested.connect(lambda: seen.append("ask_ai"))
    replay = next(
        child
        for child in page.findChildren(QPushButton)
        if child.text() == "Replay getting started"
    )
    replay.click()
    explain = next(
        child
        for child in page.findChildren(QPushButton)
        if child.text() == "Ask AI explanation"
    )
    explain.click()
    replay_ai = next(
        child
        for child in page.findChildren(QPushButton)
        if child.text() == "Replay Ask AI guide"
    )
    replay_ai.click()
    assert seen == ["core", "ask_ai", "ai_tour"]


def test_spotlight_follows_widget_and_clamps(tmp_path: Path) -> None:
    _app()
    window = QMainWindow()
    window.resize(800, 600)
    window.show()
    target = QLabel("Ask AI", window)
    target.setGeometry(40, 80, 180, 40)
    target.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_ASK_AI, target)
    overlay = TourOverlay(window, registry)
    overlay.show()
    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    hole = overlay.hole_rect()
    assert not hole.isEmpty()
    assert window.rect().contains(hole)
    window.resize(500, 400)
    overlay.refresh_geometry()
    assert window.rect().contains(overlay.hole_rect())
    target.hide()
    overlay.refresh_geometry()
    assert overlay.hole_rect().isEmpty()
    window.close()


def test_popover_stays_inside_bounds() -> None:
    hole = QRect(700, 500, 80, 40)
    bounds = QRect(16, 16, 768, 568)
    pos = popover_position(hole, QSize(320, 180), bounds)
    card = QRect(pos, QSize(320, 180))
    assert bounds.contains(card)


def test_run_guide_sits_below_header_button() -> None:
    hole = QRect(1100, 18, 72, 32)
    bounds = QRect(16, 16, 1248, 860)
    pos = popover_position(hole, QSize(320, 200), bounds, placement="below")
    card = QRect(pos, QSize(320, 200))
    assert bounds.contains(card)
    assert not card.intersects(hole)
    assert card.top() >= hole.bottom()


def test_ai_popover_sits_left_of_tall_chat_panel() -> None:
    hole = QRect(900, 40, 360, 820)
    bounds = QRect(16, 16, 1248, 860)
    pos = popover_position(hole, QSize(320, 280), bounds, placement="left")
    card = QRect(pos, QSize(320, 280))
    chat = QRect(hole.left(), hole.bottom() - 220, hole.width(), 220)
    assert bounds.contains(card)
    assert card.right() <= hole.left()
    assert not card.intersects(hole)
    assert not card.intersects(chat)
    fallback = popover_position(hole, QSize(320, 280), bounds)
    fallback_card = QRect(fallback, QSize(320, 280))
    assert bounds.contains(fallback_card)
    assert not fallback_card.intersects(chat)
    header = QRect(900, 40, 360, 36)
    header_pos = popover_position(header, QSize(380, 220), bounds, placement="left")
    header_card = QRect(header_pos, QSize(380, 220))
    assert bounds.contains(header_card)
    assert not header_card.intersects(chat)
    assert header_card.right() <= header.left()


def test_missing_anchor_does_not_crash(tmp_path: Path) -> None:
    _app()
    window = QWidget()
    window.resize(400, 300)
    window.show()
    overlay = TourOverlay(window, AnchorRegistry())
    overlay.apply(_guide_view_for(ANCHOR_SEARCH_RESULTS_GRID))
    overlay.refresh_geometry()
    assert overlay.hole_rect().isEmpty()
    assert overlay.isVisible()
    assert overlay.popover.isVisible()
    path = spotlight_cutout_path(overlay.rect(), overlay.hole_rect())
    assert path.contains(QPoint(200, 150))
    window.close()


def test_hidden_overlay_does_not_arm_click_shield_on_resize() -> None:
    _app()
    window = QMainWindow()
    window.resize(800, 600)
    overlay = TourOverlay(window, AnchorRegistry())
    window.show()
    QApplication.processEvents()
    assert overlay.isVisible() is False
    assert overlay.shield.isVisible() is False
    window.resize(640, 480)
    QApplication.processEvents()
    overlay.refresh_geometry()
    overlay.raise_()
    QApplication.processEvents()
    assert overlay.isVisible() is False
    assert overlay.shield.isVisible() is False
    window.close()


def test_non_blocking_guide_hides_click_shield() -> None:
    _app()
    window = QWidget()
    window.resize(640, 480)
    window.show()
    target = QPushButton("Tags", window)
    target.setGeometry(40, 80, 120, 36)
    target.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_TAGS, target)
    overlay = TourOverlay(window, registry)
    view = _guide_view_for(ANCHOR_IMAGES_TAGS)
    view.guide.blocking = False
    overlay.apply(view)
    QApplication.processEvents()
    overlay.refresh_geometry()
    assert overlay.isVisible() is True
    assert overlay.shield.isVisible() is False
    window.close()


def test_intro_highlights_sort_and_tags_separately() -> None:
    _app()
    window = QWidget()
    window.resize(800, 480)
    window.show()
    tags = QPushButton("Tags", window)
    tags.setGeometry(420, 40, 88, 32)
    tags.show()
    sort = QLabel("Sort", window)
    sort.setGeometry(280, 40, 110, 32)
    sort.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_TAGS, tags)
    registry.register(ANCHOR_IMAGES_ORGANIZE, sort)
    overlay = TourOverlay(window, registry)
    view = _guide_view_for(
        ANCHOR_IMAGES_TAGS,
        extra_anchors=(ANCHOR_IMAGES_ORGANIZE,),
    )
    view.guide.blocking = False
    view.guide.highlight_all = True
    overlay.apply(view)
    QApplication.processEvents()
    overlay.refresh_geometry()
    holes = overlay._spot_holes
    assert len(holes) == 2
    assert overlay.hole_rect().contains(tags.geometry().center())
    assert overlay.hole_rect().contains(sort.geometry().center())
    assert overlay.shield.isVisible() is False
    window.close()


def test_spotlight_cutout_excludes_hole_from_backdrop() -> None:
    bounds = QRect(0, 0, 400, 300)
    hole = QRect(80, 70, 120, 48)
    path = spotlight_cutout_path(bounds, hole)
    assert path.contains(QPoint(20, 20))
    assert not path.contains(hole.center())
    assert not path.contains(QPoint(hole.center().x(), hole.center().y()))
    empty = spotlight_cutout_path(bounds, QRect())
    assert empty.contains(QPoint(140, 94))
    second = QRect(200, 160, 90, 40)
    other = spotlight_cutout_path(bounds, second)
    assert other.contains(hole.center())
    assert not other.contains(second.center())


def _colors_close(actual: QColor, expected: QColor, slop: int = 4) -> bool:
    return (
        abs(actual.red() - expected.red()) <= slop
        and abs(actual.green() - expected.green()) <= slop
        and abs(actual.blue() - expected.blue()) <= slop
        and abs(actual.alpha() - expected.alpha()) <= slop
    )


def test_spotlight_paint_leaves_ui_clear_and_draws_ring() -> None:
    _app()
    bounds = QRect(0, 0, 360, 240)
    hole = QRect(90, 80, 140, 56)
    image = QImage(bounds.size(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    paint_tour_overlay(painter, bounds, hole)
    painter.end()

    outside = image.pixelColor(16, 16)
    assert outside.alpha() == 0

    inside = image.pixelColor(hole.center())
    assert inside.alpha() == 0
    assert inside.red() == 0
    assert inside.green() == 0
    assert inside.blue() == 0

    edge = image.pixelColor(hole.left(), hole.center().y())
    assert edge.alpha() > 0
    assert edge.blue() > edge.red()
    assert _colors_close(QColor(edge.red(), edge.green(), edge.blue()), RING, slop=40)


def test_guide_only_missing_anchor_paints_no_veil() -> None:
    _app()
    bounds = QRect(0, 0, 320, 200)
    image = QImage(bounds.size(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    paint_tour_overlay(painter, bounds, QRect())
    painter.end()
    assert image.pixelColor(40, 40).alpha() == 0
    assert image.pixelColor(160, 100).alpha() == 0


def test_multiple_steps_reuse_same_cutout_paint() -> None:
    _app()
    window = QMainWindow()
    window.resize(700, 500)
    window.show()
    folder = QLabel("Folder", window)
    folder.setGeometry(36, 70, 160, 36)
    folder.show()
    search = QLabel("Search", window)
    search.setGeometry(36, 130, 220, 36)
    search.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_ASK_AI, folder)
    registry.register(ANCHOR_SEARCH_RESULTS_GRID, search)
    overlay = TourOverlay(window, registry)
    overlay.show()

    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    first = QRect(overlay.hole_rect())
    assert not first.isEmpty()
    first_path = spotlight_cutout_path(overlay.rect(), first)
    assert not first_path.contains(first.center())

    overlay.apply(_guide_view_for(ANCHOR_SEARCH_RESULTS_GRID))
    QApplication.processEvents()
    overlay.refresh_geometry()
    second = QRect(overlay.hole_rect())
    assert not second.isEmpty()
    assert second != first
    second_path = spotlight_cutout_path(overlay.rect(), second)
    assert not second_path.contains(second.center())
    assert second_path.contains(first.center())
    assert overlay.popover.isVisible()
    window.close()


def test_spotlight_hit_test_keeps_hole_interactive() -> None:
    _app()
    window = QWidget()
    window.resize(640, 480)
    window.show()
    target = QPushButton("Folder", window)
    target.setGeometry(40, 80, 160, 48)
    target.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_ASK_AI, target)
    overlay = TourOverlay(window, registry)
    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    local = target.geometry().center()
    assert overlay.hole_rect().contains(local)
    assert overlay._in_hole(local)
    assert not overlay._in_popover(local)
    assert not overlay._in_hole(QPoint(8, 8))
    blocked = click_block_region(overlay.rect(), overlay.hole_rect(), overlay.popover.geometry())
    assert not blocked.contains(local)
    assert blocked.contains(QPoint(8, 8))
    assert not blocked.contains(overlay.popover.geometry().center())
    window.close()


def test_click_block_region_keeps_hole_and_guide_open() -> None:
    bounds = QRect(0, 0, 640, 480)
    hole = QRect(40, 80, 200, 48)
    popover = QRect(260, 80, 320, 180)
    region = click_block_region(bounds, hole, popover)
    assert region.contains(QPoint(8, 8))
    assert not region.contains(hole.center())
    assert not region.contains(popover.center())
    empty = click_block_region(bounds, QRect(), popover)
    assert empty.contains(hole.center())
    assert not empty.contains(popover.center())


def _center_in(host: QWidget, widget: QWidget) -> QPoint:
    return host.mapFromGlobal(widget.mapToGlobal(widget.rect().center()))


def _click_window(window: QWidget, widget: QWidget) -> None:
    handle = window.windowHandle()
    pos = widget.mapTo(window, widget.rect().center())
    if handle is not None:
        QTest.mouseClick(handle, Qt.LeftButton, Qt.NoModifier, pos)
    else:
        QTest.mouseClick(widget, Qt.LeftButton)


def _assert_hole_is_native(overlay: TourOverlay, widget: QWidget) -> None:
    local = _center_in(overlay, widget)
    assert overlay.hole_rect().contains(local)
    assert not overlay.shield.mask().contains(local)
    assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents) is True
    assert not overlay.popover.geometry().contains(local)


def test_spotlight_hole_forwards_focus_keyboard_and_button(tmp_path: Path) -> None:
    _app()
    window = QWidget()
    window.resize(720, 520)
    window.show()
    window.activateWindow()
    shell = QWidget(window)
    shell.setGeometry(36, 72, 340, 44)
    row = QHBoxLayout(shell)
    row.setContentsMargins(4, 4, 4, 4)
    field = QLineEdit(shell)
    field.setObjectName("tourTestSearchInput")
    search = QPushButton("Search", shell)
    search.setObjectName("tourTestSearchButton")
    clicks: list[str] = []
    search.clicked.connect(lambda: clicks.append("search"))
    row.addWidget(field, stretch=1)
    row.addWidget(search)
    shell.show()
    blocked = QPushButton("Blocked", window)
    blocked.setGeometry(40, 420, 120, 36)
    blocked.show()
    blocked_clicks: list[str] = []
    blocked.clicked.connect(lambda: blocked_clicks.append("blocked"))

    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_ASK_AI, shell)
    overlay = TourOverlay(window, registry)
    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    assert overlay.shield.isVisible()
    _assert_hole_is_native(overlay, field)
    _assert_hole_is_native(overlay, search)
    assert overlay.shield.mask().contains(QPoint(8, 8))
    assert overlay.shield.mask().contains(_center_in(overlay.shield, blocked))
    assert not overlay.shield.mask().contains(_center_in(overlay.shield, overlay.popover))

    _click_window(window, field)
    QApplication.processEvents()
    field.setFocus()
    QTest.keyClicks(field, "invoice")
    QApplication.processEvents()
    assert field.text() == "invoice"
    assert QApplication.focusWidget() is field

    QTest.mouseClick(search, Qt.LeftButton)
    QApplication.processEvents()
    assert clicks == ["search"]

    QTest.mouseClick(overlay.shield, Qt.LeftButton, Qt.NoModifier, _center_in(overlay.shield, blocked))
    QApplication.processEvents()
    assert blocked_clicks == []

    skip = overlay.popover._skip
    close = overlay.popover._close
    skipped: list[str] = []
    closed: list[str] = []
    overlay.popover.skip_clicked.connect(lambda: skipped.append("skip"))
    overlay.popover.close_clicked.connect(lambda: closed.append("close"))
    QTest.mouseClick(skip, Qt.LeftButton)
    QTest.mouseClick(close, Qt.LeftButton)
    QApplication.processEvents()
    assert skipped == ["skip"]
    assert closed == ["close"]

    window.resize(900, 640)
    QApplication.processEvents()
    overlay.refresh_geometry()
    _assert_hole_is_native(overlay, field)
    field.clear()
    _click_window(window, field)
    field.setFocus()
    QTest.keyClicks(field, "2026")
    QApplication.processEvents()
    assert field.text() == "2026"
    window.close()


def test_interactive_steps_reuse_hole_input_design() -> None:
    _app()
    window = QWidget()
    window.resize(780, 560)
    window.show()
    folder = QPushButton("Folder", window)
    folder.setGeometry(36, 70, 160, 36)
    folder.show()
    folder_clicks: list[str] = []
    folder.clicked.connect(lambda: folder_clicks.append("folder"))
    ask = QLineEdit(window)
    ask.setGeometry(36, 130, 260, 36)
    ask.show()
    grid = QPushButton("Grid image", window)
    grid.setGeometry(36, 190, 180, 80)
    grid.show()
    grid_clicks: list[str] = []
    grid.clicked.connect(lambda: grid_clicks.append("grid"))
    save = QPushButton("Save", window)
    save.setGeometry(36, 290, 100, 36)
    save.show()
    save_clicks: list[str] = []
    save.clicked.connect(lambda: save_clicks.append("save"))

    registry = AnchorRegistry()
    registry.register(ANCHOR_IMAGES_ASK_AI, folder)
    registry.register(ANCHOR_SEARCH_RESULTS_GRID, ask)
    overlay = TourOverlay(window, registry)
    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    _assert_hole_is_native(overlay, folder)
    QTest.mouseClick(folder, Qt.LeftButton)
    QApplication.processEvents()
    assert folder_clicks == ["folder"]

    overlay.apply(_guide_view_for(ANCHOR_SEARCH_RESULTS_GRID))
    QApplication.processEvents()
    overlay.refresh_geometry()
    _assert_hole_is_native(overlay, ask)
    ask.setFocus()
    QTest.keyClicks(ask, "dog")
    QApplication.processEvents()
    assert ask.text() == "dog"

    registry.register(ANCHOR_IMAGES_ASK_AI, grid)
    overlay.apply(_guide_view_for(ANCHOR_IMAGES_ASK_AI))
    QApplication.processEvents()
    overlay.refresh_geometry()
    _assert_hole_is_native(overlay, grid)
    QTest.mouseClick(grid, Qt.LeftButton)
    QApplication.processEvents()
    assert grid_clicks == ["grid"]

    registry.register(ANCHOR_SEARCH_RESULTS_GRID, save)
    overlay.apply(_guide_view_for(ANCHOR_SEARCH_RESULTS_GRID))
    QApplication.processEvents()
    overlay.refresh_geometry()
    _assert_hole_is_native(overlay, save)
    QTest.mouseClick(save, Qt.LeftButton)
    QApplication.processEvents()
    assert save_clicks == ["save"]
    window.close()


def test_basic_search_guide_does_not_use_meaning_example(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    guide = tour.view().guide
    assert guide.step_id == STEP_IMAGES_GUIDE
    assert "dog" not in guide.hint.lower()
    assert "dog" not in guide.body.lower()
    assert "filename" in guide.body.lower()
    assert "tag" in guide.body.lower()
    assert "try:" not in guide.body.lower()
    tour.handle_event(UI_FIND_FINISHED, {"ok": True, "result_count": 2, "kind": "basic"})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_show_welcome_prefers_prototype_tour(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    tour = _controller(tmp_path, authenticated=True)
    pages = []
    window = SimpleNamespace(
        _prototype_tour=tour,
        _config={"onboarding_completed": False},
        _show_page=pages.append,
        _needs_sign_in_gate=lambda: False,
    )
    MainWindow.show_welcome_if_needed(window)
    assert tour.view().guide.step_id == STEP_WELCOME
    assert pages == []
    assert not hasattr(window, "_welcome_dialog")


def test_show_welcome_skips_legacy_dialog_when_tour_exists(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    opened = []

    class _Welcome:
        def __init__(self, _parent) -> None:
            opened.append(self)

        def isVisible(self) -> bool:
            return False

        def open(self) -> None:
            pass

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:
            pass

        @property
        def finished(self):
            class _Signal:
                def connect(self, _callback) -> None:
                    pass

            return _Signal()

    monkeypatch.setattr("app.ui.main_window.WelcomeDialog", _Welcome)
    tour = _controller(tmp_path, authenticated=False)
    window = SimpleNamespace(
        _prototype_tour=tour,
        _config={"onboarding_completed": False},
        _needs_sign_in_gate=lambda: False,
    )
    MainWindow.show_welcome_if_needed(window)
    assert opened == []
    assert tour.view().active is False
    tour.store.complete_core()
    MainWindow.show_welcome_if_needed(window)
    assert opened == []


def test_signed_in_offers_tour_once(tmp_path: Path) -> None:
    tour = _controller(tmp_path)
    tour.on_signed_in()
    assert tour.view().guide.step_id == STEP_WELCOME
    assert tour.store.record.signed_in_offer_done is True
    tour.stop()
    tour.on_signed_in()
    assert tour.view().active is False


def test_offline_budget_and_unauthenticated_do_not_start_ask_ai_tour(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    _open_ask_ai(tour)
    assert tour.view().guide.step_id == STEP_AI_INTRO
    tour.handle_event(UI_FIND_FAILED, {"reason": "offline"})
    tour.handle_event(UI_FIND_FAILED, {"reason": "unauthenticated"})
    tour.handle_event(UI_FIND_FAILED, {"reason": "budget"})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert host.prep_starts == 0
    assert host.consent == 1


def test_steps_cover_core_and_automation() -> None:
    ids = [step.step_id for step in TOUR_STEPS]
    assert STEP_FOLDER in ids
    assert STEP_LOCAL_PREP in ids
    assert STEP_IMAGES_GUIDE in ids
    assert STEP_AUTOMATE in ids
    assert ids.index(STEP_FOLDER) < ids.index(STEP_IMAGES_GUIDE)
    phases = {step.step_id: step.phase for step in TOUR_STEPS}
    assert phases[STEP_FOLDER] == "core"
    assert phases[STEP_AUTOMATE] == "automation"
    assert CORE_SEQUENCE == (STEP_FOLDER, STEP_LOCAL_PREP, STEP_IMAGES_GUIDE)
    assert STEP_AUTOMATE in AUTOMATION_SEQUENCE
    assert STEP_AUTOMATE_IMAGES_RETURN in AUTOMATION_SEQUENCE
    assert AI_SEQUENCE == (STEP_ASK_AI_OPEN, STEP_AI_INTRO)


def test_ask_ai_open_during_core_starts_intro_then_resumes_core(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.handle_event(UI_ASK_AI_OPENED, {})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert EVENT_AI_TUTORIAL_STARTED in _names(tour)
    assert host.consent == 1
    assert tour.store.status == STATUS_IN_PROGRESS
    tour.next_fallback()
    assert tour.store.record.ai_status == STATUS_COMPLETED
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_ask_ai_open_starts_intro_tutorial(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    assert host.prep_starts == 0
    tour.handle_event(UI_ASK_AI_OPENED, {})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert tour.view().guide.anchors == (ANCHOR_IMAGES_ASK_AI,)
    assert EVENT_AI_TUTORIAL_STARTED in _names(tour)
    assert host.prep_starts == 0
    assert host.consent == 1
    assert tour.store.record.ai_status == STATUS_IN_PROGRESS
    tour.next_fallback()
    assert tour.store.record.ai_status == STATUS_COMPLETED
    assert tour.view().active is False


def test_back_ignores_stale_search_and_requires_new_event(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    first_gen = tour._step_generation
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.back()
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.handle_event(
        UI_FOLDER_SELECTED,
        {"generation": first_gen},
    )
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_back_does_not_replay_other_interactive_steps(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    folder_gen = tour._step_generation - 1
    tour.back()
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.handle_event(UI_FOLDER_SELECTED, {"generation": folder_gen})
    assert tour.view().guide.step_id == STEP_FOLDER
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.next_fallback()
    _open_ask_ai(tour)
    _finish_ai(tour)
    _build_automation(tour)
    save_gen = tour._step_generation
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    assert tour.view().guide.step_id == STEP_AUTOMATE_SAVE_CONFIRM
    tour.back()
    assert tour.view().guide.step_id == STEP_AUTOMATE
    tour.handle_event(UI_AUTOMATION_SAVED, {"generation": save_gen})
    assert tour.view().guide.step_id == STEP_AUTOMATE
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    tour.next_fallback()
    run_gen = tour._step_generation
    tour.handle_event(UI_AUTOMATION_RUN, {})
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert "finished" in tour.view().guide.title.lower() or "完了" in tour.view().guide.title
    tour.back()
    assert tour.view().guide.step_id == STEP_AUTOMATE_SAVE_CONFIRM
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_AUTOMATE_RUN
    assert "finished" not in tour.view().guide.title.lower()
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True, "generation": run_gen})
    assert "finished" not in tour.view().guide.title.lower()
    tour.handle_event(UI_AUTOMATION_RUN, {})
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert "finished" in tour.view().guide.title.lower() or "完了" in tour.view().guide.title


def test_tour_copy_has_no_try_dog_prompt() -> None:
    from app.i18n import en as en_messages
    from app.i18n import ja as ja_messages
    from app.i18n import t

    for catalog in (en_messages.MESSAGES, ja_messages.MESSAGES):
        for key, value in catalog.items():
            if not str(key).startswith("tour."):
                continue
            text = str(value).lower()
            assert "try:" not in text
            assert "try: dog" not in text
            if "hint" in key or "body" in key or "title" in key:
                assert not text.strip().startswith("try:")
    meaning = t("tour.step.meaning_search.hint") + t("tour.step.meaning_search.body")
    assert "try: dog" not in meaning.lower()
    assert "find images with dogs in them" in meaning.lower()
    assert "try:" not in meaning.lower()


def test_images_guide_explains_search_without_forcing_actions(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    guide = tour.view().guide
    assert guide.step_id == STEP_IMAGES_GUIDE
    assert guide.show_back is False
    body = guide.body.lower()
    assert "filename" in body
    assert "tag" in body
    assert ANCHOR_IMAGES_FAVORITE not in guide.anchors
    assert ANCHOR_IMAGES_ORGANIZE not in guide.anchors
    tour.handle_event(UI_FAVORITE_CHANGED, {"ok": True, "favorited": True})
    tour.handle_event(UI_SELECTION_CHANGED, {"selected_count": 2})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.next_fallback()
    assert tour.store.status == STATUS_COMPLETED
    assert tour.view().active is False
    assert STEP_TAGS_SORT not in TOUR_SEQUENCE
    assert STEP_TAGS_SORT not in [item.step_id for item in TOUR_STEPS]


def test_images_guide_start_using_capixe_is_not_clipped() -> None:
    from app.i18n import t
    from app.prototype_tour.models import GuideView

    _app()
    card = TourPopover()
    label = t("tour.start_using")
    card.apply(
        GuideView(
            visible=True,
            step_id=STEP_IMAGES_GUIDE,
            phase="core",
            title=t("tour.step.images_guide.title"),
            body=t("tour.step.images_guide.body"),
            show_back=True,
            show_next=True,
            show_skip=True,
            next_label=label,
        )
    )
    card.show()
    QApplication.processEvents()
    assert card._next.text() == label
    assert "Rootlize" in card._next.text()
    assert card._back.isVisible() is False
    needed = card._next.fontMetrics().horizontalAdvance(label)
    assert card._next.width() >= needed
    assert card.rect().contains(card._next.geometry())
    assert card._next.geometry().intersects(card._skip.geometry()) is False


def test_local_prep_shows_only_when_needed(tmp_path: Path) -> None:
    host = _FakeHost()
    host.local_snapshot = {
        "ready": 2,
        "total": 10,
        "running": True,
        "needed": 8,
        "error": False,
    }
    tour = _controller(tmp_path, host=host, authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_LOCAL_PREP
    assert host.prep_starts == 0
    assert "2 / 10" in tour.view().guide.status or "2 / 10" in tour.view().guide.body
    assert tour.view().guide.show_next is False
    host.local_snapshot = {
        "ready": 10,
        "total": 10,
        "running": False,
        "needed": 0,
        "error": False,
    }
    tour.refresh_local_prep_status()
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_local_prep_idle_failures_do_not_block_core(tmp_path: Path) -> None:
    host = _FakeHost()
    host.local_snapshot = {
        "ready": 167,
        "total": 174,
        "running": True,
        "needed": 7,
        "error": False,
    }
    tour = _controller(tmp_path, host=host, authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_LOCAL_PREP
    host.local_snapshot = {
        "ready": 167,
        "total": 174,
        "running": False,
        "needed": 7,
        "error": False,
        "failed": 7,
    }
    tour.refresh_local_prep_status()
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    assert host.prep_starts == 0


def test_unused_ai_and_automation_stay_silent_after_core(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    _finish_core(tour)
    assert tour.view().active is False
    assert tour.store.record.ai_status == STATUS_NOT_STARTED
    assert tour.store.record.automation_status == STATUS_NOT_STARTED
    assert EVENT_AI_TUTORIAL_STARTED not in _names(tour)
    assert EVENT_AUTOMATION_TUTORIAL_STARTED not in _names(tour)


def test_legacy_tour_state_migrates_to_independent_tutorials(tmp_path: Path) -> None:
    completed = migrate_legacy_record({"status": STATUS_COMPLETED, "current_step": "automate_run"})
    assert completed["status"] == STATUS_COMPLETED
    assert completed["ai_status"] == STATUS_COMPLETED
    assert completed["automation_status"] == STATUS_COMPLETED
    skipped = migrate_legacy_record({"status": STATUS_SKIPPED, "current_step": "favorite"})
    assert skipped["status"] == STATUS_SKIPPED
    assert skipped["ai_status"] == STATUS_NOT_STARTED
    assert skipped["automation_status"] == STATUS_NOT_STARTED
    mid_search = migrate_legacy_record({"status": STATUS_IN_PROGRESS, "current_step": "basic_search"})
    assert mid_search["status"] == STATUS_IN_PROGRESS
    assert mid_search["current_step"] == STEP_IMAGES_GUIDE
    assert mid_search["ai_status"] == STATUS_NOT_STARTED
    mid_ai = migrate_legacy_record({"status": STATUS_IN_PROGRESS, "current_step": "meaning_search"})
    assert mid_ai["status"] == STATUS_COMPLETED
    assert mid_ai["ai_status"] == STATUS_IN_PROGRESS
    assert mid_ai["ai_step"] == STEP_AI_INTRO
    assert mid_ai["automation_status"] == STATUS_NOT_STARTED
    waiting_ai = migrate_legacy_record({"status": STATUS_IN_PROGRESS, "current_step": "ask_ai_open"})
    assert waiting_ai["status"] == STATUS_COMPLETED
    assert waiting_ai["ai_status"] == STATUS_NOT_STARTED


def test_favorite_spotlight_falls_back_to_grid_when_star_hidden() -> None:
    _app()
    window = QMainWindow()
    window.resize(800, 600)
    window.show()
    grid = QLabel("results", window)
    grid.setGeometry(40, 80, 240, 180)
    grid.show()
    registry = AnchorRegistry()
    registry.register(ANCHOR_SEARCH_RESULTS_GRID, grid)
    overlay = TourOverlay(window, registry)
    overlay.show()
    overlay.apply(
        _guide_view_for(
            ANCHOR_IMAGES_FAVORITE,
            extra_anchors=(ANCHOR_SEARCH_RESULTS_GRID,),
        )
    )
    QApplication.processEvents()
    overlay.refresh_geometry()
    assert not overlay.hole_rect().isEmpty()
    assert window.rect().contains(overlay.hole_rect())
    window.close()


def test_show_images_does_not_reload_when_already_on_images() -> None:
    from types import SimpleNamespace

    from app.ui.main_window import PAGE_IMAGES
    from app.ui.tour_host import MainWindowTourHost

    shown: list[int] = []
    window = SimpleNamespace(
        _stack=SimpleNamespace(currentIndex=lambda: PAGE_IMAGES),
        _show_page=lambda page_id: shown.append(page_id),
    )
    host = MainWindowTourHost.__new__(MainWindowTourHost)
    host.window = window
    host.show_images()
    assert shown == []
    window._stack = SimpleNamespace(currentIndex=lambda: PAGE_IMAGES + 1)
    host.show_images()
    assert shown == [PAGE_IMAGES]


def test_resume_maps_legacy_act_step(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.store.set_step(STEP_ACT)
    tour.stop()
    tour.offer_welcome()
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_resume_maps_legacy_tags_sort_to_favorite(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.store.set_step(STEP_TAGS_SORT)
    tour.stop()
    tour.offer_welcome()
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE


def test_tour_automation_draft_starts_from_folder_only() -> None:
    from app.prototype_tour.draft import tour_automation_workflow
    from app.workspace.plan import STEP_ACTION, STEP_FIND

    workflow = tour_automation_workflow(folder=r"D:\shots", query="screenshot")
    types = [step.type for step in workflow.steps]
    assert STEP_FIND not in types
    assert STEP_ACTION not in types
    assert workflow.steps == ()
    assert workflow.scope_folder is None


def test_favorite_anchor_follows_selected_star(tmp_path: Path) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QStyleOptionViewItem

    from app.services.metadata_service import MetadataService
    from app.ui.pages.images_page import ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache
    from conftest import gallery_image_items

    _app()
    folder = tmp_path / "Library"
    folder.mkdir()
    png = folder / "shot.png"
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(png), "PNG")
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=32),
        tmp_path,
    )
    page.resize(900, 700)
    page.show()
    page.refresh()
    QApplication.processEvents()
    item = gallery_image_items(page._list_widget)[0]
    item.setSelected(True)
    page._list_widget.setCurrentItem(item)
    QApplication.processEvents()
    page._sync_tour_favorite_anchor()
    widget = page._tour_favorite_anchor
    assert widget is not None
    assert widget.isVisible()
    option = QStyleOptionViewItem()
    option.rect = page._list_widget.visualItemRect(item)
    option.widget = page._list_widget
    star = page._caption_delegate.favorite_hit_rect(option)
    assert widget.geometry() == star
    page.close()


def test_favorite_toggle_emits_tour_event_without_path(tmp_path: Path) -> None:
    from PySide6.QtGui import QImage

    from app.services.metadata_service import MetadataService
    from app.ui.pages.images_page import ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache
    from conftest import gallery_image_items

    _app()
    app = QApplication.instance()
    bus = install_tour_bus(app)
    seen: list[tuple[str, dict]] = []
    bus.subscribe(lambda name, payload: seen.append((name, payload)))
    folder = tmp_path / "Library"
    folder.mkdir()
    png = folder / "shot.png"
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(png), "PNG")
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=32),
        tmp_path,
    )
    page.refresh()
    QApplication.processEvents()
    item = gallery_image_items(page._list_widget)[0]
    item.setSelected(True)
    page._list_widget.setCurrentItem(item)
    page._toggle_selected_image_favorite()
    QApplication.processEvents()
    favorite_events = [payload for name, payload in seen if name == UI_FAVORITE_CHANGED]
    assert favorite_events
    payload = favorite_events[-1]
    assert payload.get("ok") is True
    assert payload.get("favorited") is True
    assert "path" not in payload
    assert "filename" not in payload
    assert png.name not in str(payload)
    uninstall_tour_bus(app)
    page.close()


def test_emit_does_not_change_images_when_tour_off() -> None:
    emit_tour_event(UI_SELECTION_CHANGED, selected_count=2)
    emit_tour_event(UI_FAVORITE_CHANGED, ok=True, favorited=True)
    emit_tour_event(UI_ACT_COMPLETED, ok=True)
    emit_tour_event(UI_FOLDER_SELECTED)
    emit_tour_event(UI_AUTOMATION_RUN_FINISHED, ok=True)


def test_cloud_feedback_failure_keeps_local(tmp_path: Path, monkeypatch) -> None:
    from app.prototype_tour import controller as controller_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("cloud down")

    monkeypatch.setattr(controller_mod, "post_feedback", boom)
    tour = _controller(tmp_path, authenticated=True)
    tour.start()
    tour.store.complete()
    tour.open_feedback()
    payload = tour.submit_feedback(
        {
            "most_useful": "automate",
            "would_use": "definitely",
            "easier_than_current": "much_easier",
            "willingness_to_pay": "yes",
            "confusing_text": "none",
        }
    )
    assert payload.prototype_session_id
    assert payload.most_useful == "automate"
    assert tour.view().guide.mode == "thanks"
    raw = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")
    assert "prototype_session_id" in raw
    assert "most_useful" in raw
    assert "feature_feedback" not in raw
    assert EVENT_FEEDBACK_SUBMITTED in _names(tour)


class _FakeHost:
    def __init__(self) -> None:
        self.images = 0
        self.ask_ai = 0
        self.automation = 0
        self.account = 0
        self.automation_page = 0
        self.automation_list = 0
        self.already_favorite = False
        self.favorite_anchor = 0
        self.consent = 0
        self.prep_starts = 0
        self.app_closes = 0
        self.prep_snapshot = {
            "ready": 0,
            "total": 0,
            "running": False,
            "needed": 0,
            "error": False,
        }
        self.local_snapshot = {
            "ready": 4,
            "total": 4,
            "running": False,
            "needed": 0,
            "error": False,
        }

    def show_images(self) -> None:
        self.images += 1

    def open_ask_ai(self) -> None:
        self.ask_ai += 1

    def open_automation_draft(self) -> None:
        self.automation += 1

    def show_account(self) -> None:
        self.account += 1

    def show_automation(self) -> None:
        self.automation_page += 1

    def show_automation_list(self) -> None:
        self.automation_list += 1
        self.automation_page += 1

    def close_ask_ai(self) -> None:
        return

    def selected_are_favorite(self) -> bool:
        return self.already_favorite

    def sync_favorite_anchor(self) -> None:
        self.favorite_anchor += 1

    def record_ai_consent(self) -> None:
        self.consent += 1

    def show_ask_ai_explanation(self) -> bool:
        self.consent += 1
        return bool(getattr(self, "explanation_ok", True))

    def start_ai_preparation(self) -> str:
        if self.prep_snapshot.get("running"):
            return "already"
        if (
            int(self.prep_snapshot.get("total") or 0) > 0
            and int(self.prep_snapshot.get("needed") or 0) <= 0
            and not self.prep_snapshot.get("error")
        ):
            return "ready"
        self.prep_starts += 1
        self.prep_snapshot = {
            "ready": 0,
            "total": 10,
            "running": True,
            "needed": 10,
            "error": False,
        }
        return "started"

    def ai_preparation_snapshot(self) -> dict:
        return dict(self.prep_snapshot)

    def local_preparation_snapshot(self) -> dict:
        return dict(self.local_snapshot)

    def request_app_close(self) -> None:
        self.app_closes += 1


def test_skip_tour_does_not_start_ai_preparation(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    tour.start()
    assert tour.view().guide.step_id == STEP_FOLDER
    assert host.prep_starts == 0
    assert host.consent == 0
    tour.skip()
    assert tour.store.status == STATUS_SKIPPED
    assert tour.store.record.ai_status == STATUS_NOT_STARTED
    assert EVENT_ONBOARDING_SKIPPED in _names(tour)
    assert EVENT_AI_PREPARATION_STARTED not in _names(tour)
    assert host.prep_starts == 0


def test_ask_ai_explanation_cancel_does_not_start_guide(tmp_path: Path) -> None:
    host = _FakeHost()
    host.explanation_ok = False
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    tour.handle_event(UI_ASK_AI_OPENED, {})
    assert tour.view().active is False
    assert tour.store.record.ai_status == STATUS_NOT_STARTED
    assert EVENT_AI_TUTORIAL_STARTED not in _names(tour)


def test_ask_ai_skips_second_explanation_when_already_shown(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    tour.handle_event(UI_ASK_AI_OPENED, {"explanation_shown": True})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert host.consent == 0


def test_replay_ai_starts_open_step_then_intro(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    tour.replay_ai()
    assert host.consent == 1
    assert tour.view().guide.step_id == STEP_ASK_AI_OPEN
    assert tour.view().guide.anchors == (ANCHOR_IMAGES_ASK_AI_BUTTON,)
    assert EVENT_AI_TUTORIAL_STARTED in _names(tour)
    assert host.images >= 1
    assert host.prep_starts == 0
    tour.handle_event(UI_ASK_AI_OPENED, {})
    assert tour.view().guide.step_id == STEP_AI_INTRO
    assert tour.view().guide.anchors == (ANCHOR_IMAGES_ASK_AI,)
    tour.next_fallback()
    assert tour.store.record.ai_status == STATUS_COMPLETED


def test_in_progress_ai_tutorial_is_retired_without_consent(tmp_path: Path) -> None:
    path = tmp_path / "tour.json"
    path.write_text(
        '{"status": "completed", "ai_status": "in_progress", "ai_step": "meaning_search", "session_id": "s"}\n',
        encoding="utf-8",
    )
    store = TourStore(path)
    assert store.record.ai_status == STATUS_IN_PROGRESS
    assert store.record.ai_step == STEP_AI_INTRO
    retired = retire_ask_ai_tutorial({"ai_status": STATUS_IN_PROGRESS, "ai_step": STEP_MEANING_SEARCH})
    assert retired["ai_status"] == STATUS_IN_PROGRESS
    assert retired["ai_step"] == STEP_AI_INTRO


def test_send_feedback_and_exit_saves_then_closes(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    assert tour.intercept_close() is True
    payload = tour.submit_feedback(
        {
            "most_useful": "search",
            "would_use": "definitely",
            "easier_than_current": "a_little_easier",
            "willingness_to_pay": "only_if_inexpensive",
            "confusing_text": "",
        }
    )
    assert payload.confusing_text == ""
    assert payload.most_useful == "search"
    assert payload.willingness_to_pay == "only_if_inexpensive"
    raw = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")
    assert '"most_useful": "search"' in raw
    assert "C:\\\\" not in raw
    assert EVENT_FEEDBACK_SUBMITTED in _names(tour)
    assert host.app_closes == 1
    assert tour.view().active is False
    assert tour.intercept_close() is False


def test_replay_does_not_auto_complete_previous_automation_run(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    _finish_ai(tour)
    _build_automation(tour)
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    tour.next_fallback()
    tour.handle_event(UI_AUTOMATION_RUN, {})
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert tour.store.record.automation_status == STATUS_IN_PROGRESS
    tour.replay_automation()
    assert tour.view().guide.step_id == STEP_AUTOMATE_PAGE
    assert tour.store.record.automation_status == STATUS_IN_PROGRESS
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert tour.store.record.automation_status == STATUS_IN_PROGRESS
    assert tour.view().guide.step_id == STEP_AUTOMATE_PAGE


def test_tour_does_not_add_search_filters(tmp_path: Path) -> None:
    tour = _controller(tmp_path, host=_FakeHost(), authenticated=True)
    tour.start()
    tour.handle_event(UI_FOLDER_SELECTED, {})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.handle_event(UI_FIND_FINISHED, {"ok": True, "result_count": 2, "kind": "basic"})
    assert tour.view().guide.step_id == STEP_IMAGES_GUIDE
    tour.replay()
    assert tour.view().guide.step_id == STEP_WELCOME
    tour.start()
    assert tour.view().guide.step_id == STEP_FOLDER


def test_ai_consent_guide_shows_full_body() -> None:
    from app.i18n import t
    from app.prototype_tour.models import GuideView

    _app()
    body = t("tour.step.ai_consent.body")
    assert "external AI service" in body
    assert "sent" in body
    assert "folder" in body
    assert "prepared results are reused" in body.lower()
    card = TourPopover()
    card.apply(
        GuideView(
            visible=True,
            step_id=STEP_AI_CONSENT,
            phase="ask_ai",
            index=1,
            total=3,
            title=t("tour.step.ai_consent.title"),
            body=body,
            show_back=True,
            show_next=False,
            show_skip=True,
            actions=((ACTION_START_PREPARING, t("tour.step.ai_consent.start")),),
        )
    )
    card.show()
    QApplication.processEvents()
    assert card._body.text() == body
    assert card.body_shows_full_text()
    needed = wrapped_text_height(card._body, card.content_width())
    assert card._body.height() >= needed
    assert card.height() >= card.sizeHint().height()
    for widget in (card._body, card._choice_buttons[0], card._skip):
        assert widget.isVisible()
        assert card.rect().contains(widget.geometry())
    assert card._back.isVisible() is False


def test_guide_body_does_not_clip_on_resize() -> None:
    from app.i18n import t
    from app.prototype_tour.models import GuideView

    _app()
    window = QWidget()
    window.resize(1280, 720)
    card = TourPopover(window)
    card.apply(
        GuideView(
            visible=True,
            step_id=STEP_AI_CONSENT,
            phase="ask_ai",
            index=1,
            total=3,
            title=t("tour.step.ai_consent.title"),
            body=t("tour.step.ai_consent.body"),
            show_back=True,
            show_skip=True,
            actions=((ACTION_START_PREPARING, t("tour.step.ai_consent.start")),),
        )
    )
    card.show()
    window.show()
    QApplication.processEvents()
    assert card.body_shows_full_text()
    window.resize(800, 500)
    card.apply(
        GuideView(
            visible=True,
            step_id=STEP_AI_CONSENT,
            phase="ask_ai",
            index=1,
            total=3,
            title=t("tour.step.ai_consent.title"),
            body=t("tour.step.ai_consent.body"),
            show_back=True,
            show_skip=True,
            actions=((ACTION_START_PREPARING, t("tour.step.ai_consent.start")),),
        )
    )
    QApplication.processEvents()
    assert card.body_shows_full_text()
    for widget in (card._body, card._choice_buttons[0], card._skip):
        assert card.rect().contains(widget.geometry())
    assert card._back.isVisible() is False
    window.close()


def test_automation_guides_folder_search_action_save_run(tmp_path: Path) -> None:
    host = _FakeHost()
    tour = _controller(tmp_path, host=host, authenticated=True)
    _finish_core(tour)
    _finish_ai(tour)
    tour.handle_event(UI_AUTOMATION_PAGE_SHOWN, {})
    page = tour.view().guide
    assert page.step_id == STEP_AUTOMATE_PAGE
    assert page.show_next is True
    assert "workflow" in (page.title + page.body).lower()
    tour.next_fallback()
    tour.handle_event(UI_AUTOMATION_OPENED, {})
    folder = tour.view().guide
    assert folder.step_id == STEP_AUTOMATE
    assert ANCHOR_AUTOMATION_FOLDER in folder.anchors
    assert folder.show_next is False
    tour.handle_event(UI_AUTOMATION_BLOCK_CHANGED, {"has_folder": True})
    confirm = tour.view().guide
    assert confirm.show_next is True
    assert "folder" in (confirm.title + confirm.body).lower()
    tour.next_fallback()
    search = tour.view().guide
    assert search.show_next is False
    assert search.anchors == (ANCHOR_AUTOMATION_ADD_BLOCK,)
    assert search.catalog_allow == ("text",)
    tour.back()
    assert tour.view().guide.show_next is True
    tour.next_fallback()
    assert tour.view().guide.anchors == (ANCHOR_AUTOMATION_ADD_BLOCK,)
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_search": True},
    )
    assert tour.view().guide.catalog_allow == ("text",)
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_text_search": True},
    )
    query = tour.view().guide
    assert "search" in (query.title + query.body + query.hint).lower()
    assert query.anchors[0] == ANCHOR_AUTOMATION_PARAM
    assert query.placement == "below"
    assert query.show_next is False
    tour.next_fallback()
    assert query.step_id == STEP_AUTOMATE
    assert tour.view().guide.show_next is False
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {"has_folder": True, "has_text_search": True, "has_search_query": True},
    )
    assert tour.view().guide.show_next is True
    tour.next_fallback()
    action = tour.view().guide
    assert "tag" in action.body.lower()
    assert action.anchors == (ANCHOR_AUTOMATION_ADD_BLOCK,)
    assert action.catalog_allow == ("add_tag",)
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {
            "has_folder": True,
            "has_text_search": True,
            "has_search_query": True,
            "has_add_tag": True,
        },
    )
    fit = tour.view().guide
    assert "fit" in (fit.title + fit.body + fit.hint).lower()
    assert fit.anchors == (ANCHOR_AUTOMATION_FIT,)
    assert fit.show_next is False
    tour.handle_event(UI_AUTOMATION_FITTED, {})
    tag = tour.view().guide
    assert "tag" in tag.body.lower()
    assert tag.anchors[0] == ANCHOR_AUTOMATION_PARAM
    assert tag.placement == "below"
    assert tag.show_next is False
    tour.handle_event(
        UI_AUTOMATION_BLOCK_CHANGED,
        {
            "has_folder": True,
            "has_text_search": True,
            "has_search_query": True,
            "has_add_tag": True,
            "has_tag_value": True,
        },
    )
    assert tour.view().guide.show_next is True
    tour.next_fallback()
    overview = tour.view().guide
    assert "workflow" in (overview.title + overview.body).lower()
    assert overview.show_next is True
    tour.next_fallback()
    save = tour.view().guide
    assert save.step_id == STEP_AUTOMATE
    assert save.show_next is False
    assert save.anchors == (ANCHOR_AUTOMATION_SAVE,)
    tour.handle_event(UI_AUTOMATION_SAVED, {})
    assert tour.view().guide.step_id == STEP_AUTOMATE_SAVE_CONFIRM
    assert tour.store.record.automation_status == STATUS_IN_PROGRESS
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_AUTOMATE_RUN
    assert tour.view().guide.placement == "below"
    assert tour.view().guide.anchors == (ANCHOR_AUTOMATION_LIST_RUN, ANCHOR_AUTOMATION_RUN)
    tour.handle_event(UI_AUTOMATION_RUN, {})
    assert "Confirm" in tour.view().guide.title
    tour.handle_event(UI_AUTOMATION_RUN_FINISHED, {"ok": True})
    assert "finished" in tour.view().guide.title.lower() or "完了" in tour.view().guide.title
    tour.next_fallback()
    assert tour.view().guide.step_id == STEP_AUTOMATE_IMAGES_RETURN
    tour.next_fallback()
    assert tour.store.record.automation_status == STATUS_COMPLETED


def test_explanation_steps_have_a_progression_path() -> None:
    action_gated = {
        STEP_FOLDER,
        STEP_LOCAL_PREP,
        STEP_AI_CONSENT,
        STEP_AI_PREP,
        STEP_MEANING_SEARCH,
        STEP_AI_TAG,
        STEP_AI_PREVIEW,
        STEP_AI_IMAGES_RETURN,
        STEP_AUTOMATE,
        STEP_AUTOMATE_RUN,
    }
    for spec in TOUR_STEPS:
        if spec.allow_next:
            continue
        assert spec.step_id in action_gated, f"{spec.step_id} has no progression path"


def _guide_view_for(anchor: str, extra_anchors: tuple[str, ...] = ()):
    from app.prototype_tour.models import GuideView, TourView

    return TourView(
        active=True,
        guide=GuideView(
            visible=True,
            step_id=STEP_FIND,
            index=1,
            total=3,
            phase="ask_ai",
            title="Find an image",
            body="Search by meaning, not just filenames.",
            anchors=(anchor, *extra_anchors),
            mode="guide",
            show_next=True,
            show_skip=True,
        ),
    )
