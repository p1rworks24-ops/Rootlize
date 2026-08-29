"""TourController owns step progression. Screens only emit events and anchors."""

from __future__ import annotations

from collections.abc import Callable

from app.i18n import t
from app.prototype_tour.cloud import post_analytics, post_feedback
from app.prototype_tour.entitlement import PrototypeEntitlement
from app.prototype_tour.events import TourEventBus, bump_tour_generation
from app.prototype_tour.models import (
    ACTION_START_PREPARING,
    ANCHOR_AUTOMATION_ADD_BLOCK,
    ANCHOR_AUTOMATION_BUILDER,
    ANCHOR_AUTOMATION_CHOICE,
    ANCHOR_AUTOMATION_FOLDER,
    ANCHOR_AUTOMATION_INSPECTOR,
    ANCHOR_AUTOMATION_NEW,
    ANCHOR_AUTOMATION_PARAM,
    ANCHOR_AUTOMATION_SAVE,
    ANCHOR_AUTOMATION_FIT,
    ANCHOR_IMAGES_ASK_AI,
    EVENT_AI_PREPARATION_STARTED,
    EVENT_AI_TUTORIAL_STARTED,
    EVENT_AI_TUTORIAL_COMPLETED,
    EVENT_AI_TUTORIAL_SKIPPED,
    EVENT_AUTOMATION_TUTORIAL_COMPLETED,
    EVENT_AUTOMATION_TUTORIAL_SKIPPED,
    EVENT_AUTOMATION_TUTORIAL_STARTED,
    EVENT_FEEDBACK_DISMISSED,
    EVENT_FEEDBACK_SHOWN,
    EVENT_FEEDBACK_SUBMITTED,
    EVENT_FOLDER_SELECTED,
    EVENT_MEANING_SEARCH_COMPLETED,
    EVENT_ONBOARDING_COMPLETED,
    EVENT_ONBOARDING_SKIPPED,
    EVENT_ONBOARDING_STARTED,
    EVENT_WORKFLOW_RUN,
    EVENT_WORKFLOW_SAVED,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
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
    STEP_AUTOMATE,
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE_IMAGES_RETURN,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_COMPLETE,
    STEP_FEEDBACK,
    STEP_FOLDER,
    STEP_IDLE,
    STEP_IMAGES_GUIDE,
    STEP_LOCAL_PREP,
    STEP_MEANING_CONFIRM,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    STEP_THANKS,
    STEP_WELCOME,
    TOUR_STEP_IDS,
    TUTORIAL_AI,
    TUTORIAL_AUTOMATION,
    TUTORIAL_CORE,
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
    FeedbackPayload,
    GuideView,
    TourView,
)
from app.prototype_tour.state.analytics import TourAnalytics
from app.prototype_tour.state.feedback import FeedbackStore, build_feedback
from app.prototype_tour.state.store import TourStore
from app.prototype_tour.steps import (
    AI_SEQUENCE,
    AUTOMATION_SEQUENCE,
    next_step_id,
    previous_step_id,
    resume_step_id,
    step_spec,
    tutorial_for_step,
)
from app.utils.logger import setup_logger

ViewListener = Callable[[TourView], None]

logger = setup_logger()

_AUTOMATE_NEW = 0
_AUTOMATE_FOLDER = 1
_AUTOMATE_FOLDER_CONFIRM = 2
_AUTOMATE_ADD_SEARCH = 3
_AUTOMATE_SET_QUERY = 4
_AUTOMATE_ADD_ACTION = 5
_AUTOMATE_FIT = 6
_AUTOMATE_SET_TAG = 7
_AUTOMATE_OVERVIEW = 8
_AUTOMATE_SAVE = 9

_CORE_STEPS = {STEP_FOLDER, STEP_LOCAL_PREP, STEP_IMAGES_GUIDE}
_AI_STEPS = set(AI_SEQUENCE)
_AI_PANEL_STEPS = {
    STEP_AI_INTRO,
    STEP_AI_CONSENT,
    STEP_AI_PREP,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    STEP_MEANING_CONFIRM,
    STEP_AI_ACTION,
    STEP_AI_TAG,
    STEP_AI_PREVIEW,
    STEP_AI_DONE,
}
_AUTOMATION_STEPS = set(AUTOMATION_SEQUENCE)
_GENERATION_FREE_EVENTS = {
    UI_FIND_FINISHED,
    UI_FIND_FAILED,
    UI_ASK_AI_OPENED,
    UI_ACT_PREVIEW_SHOWN,
    UI_ACT_COMPLETED,
    UI_IMAGES_PAGE_SHOWN,
    UI_AUTOMATION_FITTED,
}


class TourController:
    def __init__(
        self,
        store: TourStore | None = None,
        analytics: TourAnalytics | None = None,
        feedback: FeedbackStore | None = None,
        entitlement: PrototypeEntitlement | None = None,
        *,
        host=None,
        auth_provider=None,
    ) -> None:
        self.store = store or TourStore()
        self.analytics = analytics or TourAnalytics()
        self.feedback_store = feedback or FeedbackStore()
        self.entitlement = entitlement or PrototypeEntitlement(self.store.record.ai_calls)
        self.host = host
        self.auth_provider = auth_provider
        self._listeners: list[ViewListener] = []
        self._mode = STEP_IDLE
        self._step = STEP_IDLE
        self._tutorial = TUTORIAL_CORE
        self._status = ""
        self._preview_ready = False
        self._meaning_ready = False
        self._favorite_already = False
        self._pending_favorite_already = False
        self._automation_opened = False
        self._automation_phase = 0
        self._automation_block_flags: dict[str, bool] = {}
        self._automation_saved = False
        self._run_confirmed = False
        self._run_done = False
        self._step_generation = 0
        self._completed_steps: set[str] = set()
        self._entering = False
        self._ai_prep_started = False
        self._close_after_feedback = False
        self._allow_close = False
        self._prep_ready = 0
        self._prep_total = 0
        self._prep_running = False
        self._prep_needed = 0
        self._prep_error = False
        self._local_ready = 0
        self._local_total = 0
        self._local_running = False
        self._local_needed = 0
        self._local_error = False
        self._view = TourView()

    def attach_bus(self, bus: TourEventBus) -> None:
        bus.subscribe(self.handle_event)

    def subscribe(self, listener: ViewListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def should_auto_start(self) -> bool:
        return self.store.should_auto_start()

    def has_in_progress(self) -> bool:
        return self.store.has_in_progress()

    def is_authenticated(self) -> bool:
        if self.auth_provider is None:
            return True
        identity = self._identity()
        return bool(identity.get("user_id") or identity.get("access_token"))

    def should_offer_after_sign_in(self) -> bool:
        return (
            self.store.should_auto_start()
            and not self.store.record.signed_in_offer_done
            and self._mode == STEP_IDLE
        )

    def offer_welcome(self) -> None:
        if self._mode in TOUR_STEP_IDS:
            self._publish()
            return
        if self.has_in_progress():
            self._resume_active()
            return
        self.store.mark_welcome_seen()
        if not self.is_authenticated():
            return
        self._show_welcome()

    def on_signed_in(self) -> None:
        if not self.is_authenticated():
            return
        if self._mode in TOUR_STEP_IDS or self._mode == STEP_WELCOME:
            return
        if not self.should_offer_after_sign_in():
            return
        self.store.mark_signed_in_offer_done()
        self._show_welcome()

    def _show_welcome(self) -> None:
        if not self.is_authenticated():
            return
        self._reset_runtime()
        self._tutorial = TUTORIAL_CORE
        self._mode = STEP_WELCOME
        self._step = STEP_WELCOME
        self.store.mark_welcome_seen()
        host = self.host
        show_images = getattr(host, "show_images", None) if host is not None else None
        if callable(show_images):
            show_images()
        self._publish()

    def start(self) -> None:
        if not self.is_authenticated():
            return
        self._reset_runtime()
        self._tutorial = TUTORIAL_CORE
        self.store.start_core(STEP_FOLDER)
        self._track(EVENT_ONBOARDING_STARTED)
        self._enter_step(STEP_FOLDER, persist=False)

    def start_ai_tutorial(self, *, opened: bool = False, explanation_done: bool = False) -> None:
        if not self.is_authenticated():
            return
        if self.store.record.ai_status not in {STATUS_NOT_STARTED, STATUS_IN_PROGRESS}:
            return
        if self.store.record.ai_status == STATUS_NOT_STARTED and not explanation_done:
            if not self._offer_ask_ai_explanation():
                return
        self._reset_runtime()
        self._tutorial = TUTORIAL_AI
        if opened:
            step = STEP_AI_INTRO
        elif self.store.record.ai_status == STATUS_IN_PROGRESS:
            step = resume_step_id(self.store.record.ai_step)
            if step not in {STEP_ASK_AI_OPEN, STEP_AI_INTRO}:
                step = STEP_ASK_AI_OPEN
        else:
            step = STEP_ASK_AI_OPEN
        if self.store.record.ai_status == STATUS_NOT_STARTED:
            self.store.start_ai(step)
            self._track(EVENT_AI_TUTORIAL_STARTED)
        self._enter_step(step, persist=False)

    def _offer_ask_ai_explanation(self) -> bool:
        host = self.host
        shower = getattr(host, "show_ask_ai_explanation", None) if host is not None else None
        if not callable(shower):
            return True
        return bool(shower())

    def start_automation_tutorial(self) -> None:
        if not self.is_authenticated():
            return
        if self.store.record.automation_status not in {STATUS_NOT_STARTED, STATUS_IN_PROGRESS}:
            return
        self._reset_runtime()
        self._tutorial = TUTORIAL_AUTOMATION
        if self.store.record.automation_status == STATUS_IN_PROGRESS:
            step = resume_step_id(self.store.record.automation_step)
            if step not in _AUTOMATION_STEPS:
                step = STEP_AUTOMATE_PAGE
            self._enter_step(step, persist=False)
            return
        self.store.start_automation(STEP_AUTOMATE_PAGE)
        self._track(EVENT_AUTOMATION_TUTORIAL_STARTED)
        self._enter_step(STEP_AUTOMATE_PAGE, persist=False)

    def replay(self) -> None:
        self.replay_core()

    def replay_core(self) -> None:
        self.stop()
        self.store.reset_core_for_replay()
        self.offer_welcome()

    def replay_ai(self) -> None:
        self.stop()
        self.store.reset_ai_for_replay()
        if not self.is_authenticated():
            return
        host = self.host
        show_images = getattr(host, "show_images", None) if host is not None else None
        if callable(show_images):
            show_images()
        if not self._offer_ask_ai_explanation():
            return
        self.start_ai_tutorial(explanation_done=True)

    def replay_automation(self) -> None:
        self.stop()
        self.store.reset_automation_for_replay()
        if self.is_authenticated():
            self.start_automation_tutorial()

    def skip(self) -> None:
        if self._mode == STEP_IDLE:
            return
        if self._mode == STEP_FEEDBACK:
            self.decline_feedback()
            return
        if self._mode in {STEP_COMPLETE, STEP_THANKS}:
            self.stop()
            return
        self._skip_active_tutorial()
        self.stop()

    def dismiss(self) -> None:
        if self._mode == STEP_IDLE:
            return
        if self._mode == STEP_FEEDBACK:
            return
        if self._mode in {STEP_COMPLETE, STEP_THANKS, STEP_WELCOME}:
            self.stop()
            return
        self._skip_active_tutorial()
        self.stop()

    def intercept_close(self) -> bool:
        """Keep the app open and offer first-time feedback instead of quitting."""
        if self._allow_close:
            return False
        if self._mode == STEP_THANKS and not self._close_after_feedback:
            self.stop()
            return False
        if self._mode == STEP_FEEDBACK:
            return True
        if self._should_prompt_feedback_on_close():
            if self._mode not in {STEP_IDLE, STEP_FEEDBACK, STEP_THANKS}:
                self._skip_active_tutorial()
                self.stop()
            self._close_after_feedback = True
            self.open_feedback()
            return True
        if self._mode not in {STEP_IDLE, STEP_THANKS}:
            self._skip_active_tutorial()
            self.stop()
        return False

    def decline_feedback(self) -> None:
        self.store.mark_feedback_offered()
        self._track(EVENT_FEEDBACK_DISMISSED)
        if self._close_after_feedback:
            self._finish_close_after_feedback()
            return
        self.stop()

    def _skip_active_tutorial(self) -> None:
        if self._tutorial == TUTORIAL_AI:
            self.store.skip_ai()
            self._track(EVENT_AI_TUTORIAL_SKIPPED)
        elif self._tutorial == TUTORIAL_AUTOMATION:
            self.store.skip_automation()
            self._track(EVENT_AUTOMATION_TUTORIAL_SKIPPED)
        else:
            self.store.skip_core()
            self._track(EVENT_ONBOARDING_SKIPPED)

    def stop(self) -> None:
        self._mode = STEP_IDLE
        self._step = STEP_IDLE
        self._tutorial = TUTORIAL_CORE
        self._status = ""
        self._preview_ready = False
        self._publish()

    def next_fallback(self) -> None:
        if self._mode == STEP_WELCOME:
            self.start()
            return
        if self._mode == STEP_COMPLETE:
            self.open_feedback()
            return
        if self._mode == STEP_THANKS:
            self.stop()
            return
        if self._step == STEP_IMAGES_GUIDE:
            self._finish_core()
            return
        if self._step == STEP_LOCAL_PREP and self._local_prep_is_ready():
            self._advance(STEP_IMAGES_GUIDE)
            return
        if self._step == STEP_AI_PREP and self._prep_is_ready():
            self._advance(STEP_MEANING_EXPLAIN)
            return
        if self._step == STEP_MEANING_EXPLAIN and self._meaning_ready:
            self._advance(STEP_MEANING_CONFIRM)
            return
        if self._step == STEP_AUTOMATE and self._automation_phase == _AUTOMATE_FOLDER_CONFIRM:
            self._set_automation_phase(_AUTOMATE_ADD_SEARCH)
            return
        if self._step == STEP_AUTOMATE and self._automation_phase == _AUTOMATE_SET_QUERY:
            if self._automation_flags()["has_search_query"]:
                self._set_automation_phase(_AUTOMATE_ADD_ACTION)
            return
        if self._step == STEP_AUTOMATE and self._automation_phase == _AUTOMATE_FIT:
            self._fit_automation_canvas()
            self._set_automation_phase(_AUTOMATE_SET_TAG)
            return
        if self._step == STEP_AUTOMATE and self._automation_phase == _AUTOMATE_SET_TAG:
            if self._automation_flags()["has_tag_value"]:
                self._set_automation_phase(_AUTOMATE_OVERVIEW)
            return
        if self._step == STEP_AUTOMATE and self._automation_phase == _AUTOMATE_OVERVIEW:
            self._set_automation_phase(_AUTOMATE_SAVE)
            return
        if self._step == STEP_AI_INTRO:
            self._finish_ai()
            return
        if self._step == STEP_AUTOMATE_RUN and self._run_done:
            self._advance(STEP_AUTOMATE_IMAGES_RETURN)
            return
        spec = step_spec(self._step)
        if spec is not None and (spec.allow_next or self._step in self._completed_steps):
            nxt = next_step_id(self._step, self._tutorial)
            if nxt:
                self._advance(nxt)
            elif self._tutorial == TUTORIAL_CORE:
                self._finish_core()
            elif self._tutorial == TUTORIAL_AI:
                self._finish_ai()
            elif self._tutorial == TUTORIAL_AUTOMATION:
                self._finish_automation()

    def back(self) -> None:
        if self._mode in {STEP_FEEDBACK, STEP_THANKS, STEP_COMPLETE, STEP_WELCOME}:
            return
        if self._step == STEP_AUTOMATE and self._automation_phase > 0:
            self._automation_phase -= 1
            self._publish()
            return
        if self._step == STEP_IMAGES_GUIDE and STEP_LOCAL_PREP not in self._completed_steps:
            self._advance(STEP_FOLDER)
            return
        prev = previous_step_id(self._step, self._tutorial)
        if prev:
            self._advance(prev)

    def handle_event(self, name: str, payload: dict) -> None:
        if self._entering:
            return
        data = payload if isinstance(payload, dict) else {}
        if (
            name == UI_ASK_AI_OPENED
            and self.store.record.ai_status == STATUS_NOT_STARTED
            and self.store.record.automation_status != STATUS_IN_PROGRESS
        ):
            self.start_ai_tutorial(
                opened=True,
                explanation_done=bool(data.get("explanation_shown")),
            )
            return
        if self._mode == STEP_IDLE:
            self._maybe_start_contextual(name)
            return
        if name not in _GENERATION_FREE_EVENTS and not self._accepts_event(data):
            return
        handlers = {
            UI_FOLDER_SELECTED: lambda _data: self._on_folder_selected(),
            UI_FIND_FINISHED: self._on_find_finished,
            UI_FIND_FAILED: self._on_find_failed,
            UI_SELECTION_CHANGED: self._on_selection,
            UI_FAVORITE_CHANGED: self._on_favorite_changed,
            UI_ASK_AI_OPENED: lambda _data: self._on_ask_ai_opened(),
            UI_ACT_PREVIEW_SHOWN: self._on_act_preview,
            UI_ACT_COMPLETED: self._on_act_completed,
            UI_IMAGES_PAGE_SHOWN: lambda _data: self._on_images_page_shown(),
            UI_AUTOMATION_PAGE_SHOWN: lambda _data: self._on_automation_page_shown(),
            UI_AUTOMATION_OPENED: lambda _data: self._on_automation_opened(),
            UI_AUTOMATION_BLOCK_CHANGED: self._on_automation_blocks,
            UI_AUTOMATION_FITTED: lambda _data: self._on_automation_fitted(),
            UI_AUTOMATION_SAVED: lambda _data: self._on_automation_saved(),
            UI_AUTOMATION_RUN: lambda _data: self._on_automation_run(),
            UI_AUTOMATION_RUN_FINISHED: self._on_automation_run_finished,
        }
        handler = handlers.get(name)
        if handler is not None:
            handler(data)

    def handle_guide_action(self, action_id: str) -> None:
        if self._mode == STEP_IDLE or self._entering:
            return
        if self._step == STEP_AI_CONSENT and str(action_id or "").strip() == ACTION_START_PREPARING:
            self._start_ai_preparation()

    def refresh_ai_prep_status(self) -> None:
        if self._step != STEP_AI_PREP:
            return
        self._read_prep_snapshot()
        self._publish()

    def refresh_local_prep_status(self) -> None:
        if self._step != STEP_LOCAL_PREP:
            return
        self._read_local_snapshot()
        if self._local_prep_is_ready():
            self._advance(STEP_IMAGES_GUIDE)
            return
        self._publish()

    def note_ai_call(self) -> None:
        self.entitlement.note_call()
        self.store.note_ai_call()

    def open_feedback(self) -> None:
        if self._mode != STEP_FEEDBACK:
            self._track(EVENT_FEEDBACK_SHOWN)
        self._mode = STEP_FEEDBACK
        self._publish()

    def submit_feedback(self, answers: dict) -> FeedbackPayload:
        identity = self._identity()
        payload = build_feedback(
            session_id=self.store.record.session_id,
            user_id=identity.get("user_id", ""),
            **{key: answers.get(key, "") for key in (
                "most_useful",
                "most_useful_step",
                "would_use",
                "easier_than_current",
                "willingness_to_pay",
                "payment_interest",
                "confusing_text",
                "confusing_feedback",
            )},
        )
        try:
            self.feedback_store.save(payload)
        except OSError:
            logger.warning("Prototype feedback local save failed", exc_info=True)
        try:
            post_feedback(
                payload,
                config=identity.get("config"),
                access_token=identity.get("access_token", ""),
            )
        except Exception:
            pass
        self._track(EVENT_FEEDBACK_SUBMITTED)
        self.store.mark_feedback_offered()
        if self._close_after_feedback:
            self._finish_close_after_feedback()
            return payload
        self._mode = STEP_THANKS
        self._publish()
        return payload

    def track_event(self, event_name: str) -> None:
        self._track(event_name)

    def view(self) -> TourView:
        return self._view

    def _maybe_start_contextual(self, name: str) -> None:
        if self.store.status == STATUS_IN_PROGRESS:
            return
        if name == UI_ASK_AI_OPENED and self.store.record.ai_status == STATUS_NOT_STARTED:
            self.start_ai_tutorial(opened=True, explanation_done=bool(data.get("explanation_shown")))
            return
        if name == UI_AUTOMATION_PAGE_SHOWN and self.store.record.automation_status == STATUS_NOT_STARTED:
            self.start_automation_tutorial()

    def _resume_active(self) -> None:
        self._ai_prep_started = bool(self.store.record.ai_prep_started)
        if self.store.status == STATUS_IN_PROGRESS:
            self._tutorial = TUTORIAL_CORE
            step = resume_step_id(self.store.record.current_step)
            if step not in _CORE_STEPS:
                step = STEP_FOLDER
            self._enter_step(step)
            return
        if self.store.record.ai_status == STATUS_IN_PROGRESS:
            self.start_ai_tutorial()
            return
        if self.store.record.automation_status == STATUS_IN_PROGRESS:
            self.start_automation_tutorial()

    def _reset_runtime(self) -> None:
        self._completed_steps.clear()
        self._status = ""
        self._ai_prep_started = bool(self.store.record.ai_prep_started)
        self._reset_prep_status()
        self._reset_local_status()
        self._preview_ready = False
        self._meaning_ready = False
        self._favorite_already = False
        self._automation_opened = False
        self._automation_phase = 0
        self._automation_block_flags = {}
        self._automation_saved = False
        self._run_confirmed = False
        self._run_done = False

    def _on_folder_selected(self) -> None:
        if self._step != STEP_FOLDER:
            return
        self._track(EVENT_FOLDER_SELECTED)
        self._mark_completed(STEP_FOLDER)
        self._read_local_snapshot()
        if self._local_prep_is_ready():
            self._advance(STEP_IMAGES_GUIDE)
            return
        self._advance(STEP_LOCAL_PREP)

    def _on_find_finished(self, data: dict) -> None:
        ok = bool(data.get("ok", False))
        count = int(data.get("result_count") or 0)
        kind = self._search_kind(data)
        if data.get("ai") or kind == "meaning":
            self.note_ai_call()
        if not ok or count <= 0:
            if self._step in {STEP_MEANING_EXPLAIN, STEP_MEANING_SEARCH}:
                self._status = "unavailable" if not ok else "empty"
                self._publish()
            return
        if kind != "meaning":
            return
        if self._step not in {
            STEP_AI_INTRO,
            STEP_AI_CONSENT,
            STEP_AI_PREP,
            STEP_MEANING_EXPLAIN,
            STEP_MEANING_SEARCH,
        }:
            return
        self._meaning_ready = True
        self._track(EVENT_MEANING_SEARCH_COMPLETED)
        self._mark_completed(STEP_MEANING_SEARCH)
        if self._step == STEP_MEANING_SEARCH:
            self._advance(STEP_MEANING_CONFIRM)

    def _on_find_failed(self, data: dict) -> None:
        if self._step not in {STEP_MEANING_EXPLAIN, STEP_MEANING_SEARCH}:
            return
        reason = str(data.get("reason") or "error")
        self._status = reason if reason in {"unavailable", "offline", "unauthenticated", "budget"} else "unavailable"
        self._publish()

    def _on_selection(self, data: dict) -> None:
        del data

    def _on_favorite_changed(self, data: dict) -> None:
        del data

    def _on_act_preview(self, data: dict) -> None:
        if not self._is_add_tag_action(data):
            return
        if self._step in {
            STEP_MEANING_EXPLAIN,
            STEP_MEANING_SEARCH,
            STEP_MEANING_CONFIRM,
            STEP_AI_ACTION,
            STEP_AI_TAG,
        }:
            self._preview_ready = True
            self._advance(STEP_AI_PREVIEW)
            return
        if self._step != STEP_AI_PREVIEW:
            return
        self._preview_ready = True
        self._publish()

    def _on_act_completed(self, data: dict) -> None:
        if self._step not in {
            STEP_MEANING_EXPLAIN,
            STEP_MEANING_SEARCH,
            STEP_MEANING_CONFIRM,
            STEP_AI_ACTION,
            STEP_AI_TAG,
            STEP_AI_PREVIEW,
        }:
            return
        if not self._is_add_tag_action(data):
            return
        if not bool(data.get("ok", False)):
            self._status = "act_failed"
            if self._step != STEP_AI_PREVIEW:
                self._advance(STEP_AI_PREVIEW)
            else:
                self._publish()
            return
        self._mark_completed(STEP_AI_PREVIEW)
        self._advance(STEP_AI_DONE)

    def _on_ask_ai_opened(self) -> None:
        if self._step != STEP_ASK_AI_OPEN:
            return
        self._mark_completed(STEP_ASK_AI_OPEN)
        self._advance(STEP_AI_INTRO)

    def _on_images_page_shown(self) -> None:
        if self._step != STEP_AI_IMAGES_RETURN:
            return
        self._mark_completed(STEP_AI_IMAGES_RETURN)
        self._advance(STEP_AI_RESULT)

    def _on_automation_page_shown(self) -> None:
        if self._step == STEP_AUTOMATE and self._automation_phase < _AUTOMATE_FOLDER:
            self._set_automation_phase(_AUTOMATE_NEW)

    def _on_automation_opened(self) -> None:
        if self._step == STEP_AUTOMATE_PAGE:
            self._mark_completed(STEP_AUTOMATE_PAGE)
            self._advance(STEP_AUTOMATE)
            self._set_automation_phase(_AUTOMATE_FOLDER)
            return
        if self._step != STEP_AUTOMATE:
            return
        self._automation_opened = True
        if self._automation_phase < _AUTOMATE_FOLDER:
            self._set_automation_phase(_AUTOMATE_FOLDER)
        else:
            self._publish()

    def _on_automation_blocks(self, data: dict) -> None:
        if self._step != STEP_AUTOMATE:
            return
        flags = self._automation_flags(data)
        self._automation_block_flags = flags
        desired = self._automation_phase
        if self._automation_phase == _AUTOMATE_FOLDER and flags["has_folder"]:
            desired = _AUTOMATE_FOLDER_CONFIRM
        elif self._automation_phase == _AUTOMATE_ADD_SEARCH and flags["has_text_search"]:
            desired = _AUTOMATE_SET_QUERY
        elif self._automation_phase == _AUTOMATE_ADD_ACTION and flags["has_add_tag"]:
            desired = _AUTOMATE_FIT
        if desired > self._automation_phase:
            self._set_automation_phase(desired)
            return
        self._publish()

    def _on_automation_fitted(self) -> None:
        if self._step != STEP_AUTOMATE:
            return
        if self._automation_phase != _AUTOMATE_FIT:
            return
        self._set_automation_phase(_AUTOMATE_SET_TAG)

    def _fit_automation_canvas(self) -> None:
        fitter = getattr(self.host, "fit_automation_canvas", None) if self.host is not None else None
        if callable(fitter):
            fitter()

    def _automation_flags(self, data: dict | None = None) -> dict[str, bool]:
        event = data if isinstance(data, dict) else {}
        snap = self._read_builder_snapshot()
        stored = self._automation_block_flags

        def flag(name: str) -> bool:
            if name in event:
                return bool(event.get(name))
            if name in stored:
                return bool(stored.get(name))
            return bool(snap.get(name))

        return {
            "has_folder": flag("has_folder"),
            "has_search": flag("has_search"),
            "has_action": flag("has_action"),
            "has_text_search": flag("has_text_search"),
            "has_search_query": flag("has_search_query"),
            "has_add_tag": flag("has_add_tag"),
            "has_tag_value": flag("has_tag_value"),
        }

    def _set_automation_phase(self, phase: int) -> None:
        if phase == self._automation_phase:
            return
        self._automation_phase = phase
        self._focus_automation_phase()
        self._publish()

    def _focus_automation_phase(self) -> None:
        focus = getattr(self.host, "focus_automation_inspector", None) if self.host is not None else None
        if not callable(focus):
            return
        if self._automation_phase in {_AUTOMATE_FOLDER, _AUTOMATE_FOLDER_CONFIRM}:
            focus("folder")
        if self._automation_phase == _AUTOMATE_SET_QUERY:
            focus("search")
        if self._automation_phase == _AUTOMATE_SET_TAG:
            focus("action")

    def _read_builder_snapshot(self) -> dict:
        reader = getattr(self.host, "automation_builder_snapshot", None) if self.host is not None else None
        data = reader() if callable(reader) else {}
        return data if isinstance(data, dict) else {}

    def _builder_is_complete(self, data: dict | None = None) -> bool:
        flags = self._automation_flags(data)
        return flags["has_folder"] and flags["has_text_search"] and flags["has_add_tag"]

    def _on_automation_saved(self) -> None:
        if self._step != STEP_AUTOMATE:
            return
        if not self._builder_is_complete() and STEP_AUTOMATE not in self._completed_steps:
            return
        self._automation_saved = True
        self._track(EVENT_WORKFLOW_SAVED)
        self._mark_completed(STEP_AUTOMATE)
        self._advance(STEP_AUTOMATE_SAVE_CONFIRM)

    def _on_automation_run(self) -> None:
        if self._step != STEP_AUTOMATE_RUN:
            return
        self._run_confirmed = True
        self._publish()

    def _on_automation_run_finished(self, data: dict) -> None:
        if self._step != STEP_AUTOMATE_RUN:
            return
        if not bool(data.get("ok", False)):
            self._status = "act_failed"
            self._publish()
            return
        self._run_done = True
        self._track(EVENT_WORKFLOW_RUN)
        self._mark_completed(STEP_AUTOMATE_RUN)
        self._publish()

    def _finish_core(self) -> None:
        self.store.complete_core()
        self._track(EVENT_ONBOARDING_COMPLETED)
        self.stop()

    def _finish_ai(self) -> None:
        self.store.complete_ai()
        self._track(EVENT_AI_TUTORIAL_COMPLETED)
        if self.store.status == STATUS_IN_PROGRESS:
            self._resume_active()
            return
        self.stop()

    def _finish_automation(self) -> None:
        self.store.complete_automation()
        self._track(EVENT_AUTOMATION_TUTORIAL_COMPLETED)
        self.stop()

    def _offer_feedback_or_stop(self) -> None:
        self.stop()

    def _should_prompt_feedback_on_close(self) -> bool:
        return not self.store.record.feedback_offered and not self.feedback_store.has_entries()

    def _finish_close_after_feedback(self) -> None:
        self._allow_close = True
        self._close_after_feedback = False
        self.stop()
        closer = getattr(self.host, "request_app_close", None) if self.host is not None else None
        if callable(closer):
            closer()

    def _advance(self, step_id: str, *, track: bool = True) -> None:
        del track
        self._enter_step(step_id)

    def _mark_completed(self, step_id: str) -> None:
        self._completed_steps.add(step_id)

    def _accepts_event(self, data: dict) -> bool:
        if "generation" not in data:
            return True
        try:
            return int(data.get("generation") or 0) == self._step_generation
        except (TypeError, ValueError):
            return False

    def _enter_step(self, step_id: str, *, persist: bool = True) -> None:
        self._entering = True
        try:
            self._step_generation = bump_tour_generation()
            self._status = ""
            self._preview_ready = False
            self._favorite_already = False
            self._automation_opened = False
            self._automation_saved = False
            self._run_confirmed = False
            self._run_done = False
            if step_id != STEP_AUTOMATE:
                self._automation_phase = 0
                self._automation_block_flags = {}
            self._step = step_id
            self._mode = step_id
            self._tutorial = tutorial_for_step(step_id)
            if persist:
                self.store.set_step(step_id, self._tutorial)
            if step_id == STEP_AI_PREP:
                self._read_prep_snapshot()
            if step_id == STEP_LOCAL_PREP:
                self._read_local_snapshot()
            self._prepare_step(step_id)
            if step_id == STEP_AUTOMATE and STEP_AUTOMATE in self._completed_steps:
                self._automation_phase = _AUTOMATE_SAVE
            self._publish()
        finally:
            self._entering = False
        if step_id == STEP_MEANING_SEARCH and self._meaning_ready:
            self._advance(STEP_MEANING_CONFIRM)

    def _prepare_step(self, step_id: str) -> None:
        host = self.host
        if host is None:
            return
        if step_id == STEP_AI_IMAGES_RETURN:
            return
        if step_id == STEP_ASK_AI_OPEN:
            show_images = getattr(host, "show_images", None)
            if callable(show_images):
                show_images()
            close_ask_ai = getattr(host, "close_ask_ai", None)
            if callable(close_ask_ai):
                close_ask_ai()
            return
        if step_id == STEP_AUTOMATE_IMAGES_RETURN:
            show_images = getattr(host, "show_images", None)
            if callable(show_images):
                show_images()
            return
        if step_id in _CORE_STEPS or step_id in _AI_PANEL_STEPS:
            show_images = getattr(host, "show_images", None)
            if callable(show_images):
                show_images()
        if step_id in _AI_PANEL_STEPS:
            open_ask_ai = getattr(host, "open_ask_ai", None)
            if callable(open_ask_ai):
                open_ask_ai()
        elif step_id == STEP_AI_RESULT:
            show_images = getattr(host, "show_images", None)
            if callable(show_images):
                show_images()
            close_ask_ai = getattr(host, "close_ask_ai", None)
            if callable(close_ask_ai):
                close_ask_ai()
        elif step_id in _AUTOMATION_STEPS:
            show_automation = getattr(host, "show_automation", None)
            if callable(show_automation):
                show_automation()
            if step_id in {STEP_AUTOMATE_SAVE_CONFIRM, STEP_AUTOMATE_RUN}:
                show_list = getattr(host, "show_automation_list", None)
                if callable(show_list):
                    show_list()

    def _search_kind(self, data: dict) -> str:
        kind = str(data.get("kind") or "").strip()
        if kind in {"basic", "meaning"}:
            return kind
        return "meaning" if data.get("ai") else "basic"

    def _is_add_tag_action(self, data: dict) -> bool:
        action = str(data.get("action") or "").strip()
        return not action or action == "add_tag"

    def _reset_prep_status(self) -> None:
        self._prep_ready = 0
        self._prep_total = 0
        self._prep_running = False
        self._prep_needed = 0
        self._prep_error = False

    def _reset_local_status(self) -> None:
        self._local_ready = 0
        self._local_total = 0
        self._local_running = False
        self._local_needed = 0
        self._local_error = False

    def _read_prep_snapshot(self) -> None:
        reader = getattr(self.host, "ai_preparation_snapshot", None) if self.host is not None else None
        data = reader() if callable(reader) else {}
        if not isinstance(data, dict):
            data = {}
        self._prep_ready = max(0, int(data.get("ready") or 0))
        self._prep_total = max(0, int(data.get("total") or 0))
        self._prep_running = bool(data.get("running"))
        self._prep_needed = max(0, int(data.get("needed") or 0))
        self._prep_error = bool(data.get("error"))

    def _read_local_snapshot(self) -> None:
        reader = getattr(self.host, "local_preparation_snapshot", None) if self.host is not None else None
        data = reader() if callable(reader) else {}
        if not isinstance(data, dict):
            data = {}
        self._local_ready = max(0, int(data.get("ready") or 0))
        self._local_total = max(0, int(data.get("total") or 0))
        self._local_running = bool(data.get("running"))
        self._local_needed = max(0, int(data.get("needed") or 0))
        self._local_error = bool(data.get("error"))

    def _prep_is_ready(self) -> bool:
        if self._prep_error and self._prep_needed > 0:
            return False
        if self._prep_total <= 0:
            return not self._prep_running and not self._prep_error
        return (not self._prep_running) and self._prep_needed <= 0

    def _local_prep_is_ready(self) -> bool:
        # Core waits only while OCR / search-document work is in flight.
        # Idle leftovers (failed or unreadable files) must not block Getting started.
        return not self._local_running

    def _start_ai_preparation(self) -> None:
        record = getattr(self.host, "record_ai_consent", None) if self.host is not None else None
        if callable(record):
            record()
        start = getattr(self.host, "start_ai_preparation", None) if self.host is not None else None
        result = start() if callable(start) else "failed"
        if result not in {"started", "already", "ready"}:
            self._status = "unavailable"
            self._publish()
            return
        if result == "started":
            self._track(EVENT_AI_PREPARATION_STARTED)
        self._ai_prep_started = True
        self.store.set_ai_prep_started(True)
        self._advance(STEP_AI_PREP)

    def _track(self, event_name: str) -> None:
        identity = self._identity()
        event = self.analytics.record(
            event_name,
            session_id=self.store.record.session_id,
            user_id=identity.get("user_id", ""),
        )
        if event is None:
            return
        try:
            post_analytics(
                event,
                config=identity.get("config"),
                access_token=identity.get("access_token", ""),
            )
        except Exception:
            pass

    def _identity(self) -> dict:
        provider = self.auth_provider
        if provider is None:
            return {}
        try:
            return dict(provider() or {})
        except Exception:
            return {}

    def _publish(self) -> None:
        self._view = self._build_view()
        for listener in list(self._listeners):
            listener(self._view)

    def _build_view(self) -> TourView:
        if self._mode == STEP_IDLE:
            return TourView(active=False)
        if self._mode == STEP_WELCOME:
            return TourView(
                active=True,
                guide=GuideView(
                    visible=True,
                    step_id=STEP_WELCOME,
                    mode="welcome",
                    title=t("tour.welcome.title"),
                    body=t("tour.welcome.body"),
                    show_skip=True,
                    show_next=True,
                    chapter_break=True,
                ),
            )
        if self._mode == STEP_COMPLETE:
            return TourView(
                active=True,
                guide=GuideView(
                    visible=True,
                    step_id=STEP_COMPLETE,
                    mode="complete",
                    title=t("tour.complete.title"),
                    body=t("tour.complete.body"),
                    show_skip=True,
                    show_next=True,
                    chapter_break=True,
                ),
            )
        if self._mode == STEP_FEEDBACK:
            return TourView(
                active=True,
                guide=GuideView(
                    visible=True,
                    step_id=STEP_FEEDBACK,
                    mode="feedback",
                    title=t("tour.feedback.title"),
                    show_skip=True,
                ),
            )
        if self._mode == STEP_THANKS:
            return TourView(
                active=True,
                guide=GuideView(
                    visible=True,
                    step_id=STEP_THANKS,
                    mode="thanks",
                    title=t("tour.thanks.title"),
                    show_next=True,
                    show_skip=False,
                ),
            )
        spec = step_spec(self._step)
        if spec is None:
            return TourView(active=False)
        title = t(spec.title_key)
        body = t(spec.body_key)
        hint = ""
        next_label = ""
        actions: tuple[tuple[str, str], ...] = ()
        show_next = spec.allow_next or spec.step_id in self._completed_steps
        anchors = spec.anchors
        placement = ""
        catalog_allow: tuple[str, ...] = ()
        blocking = True
        highlight_all = False
        status = ""
        if spec.step_id == STEP_IMAGES_GUIDE:
            next_label = t("tour.start_using")
            blocking = False
        elif spec.step_id == STEP_AI_CONSENT:
            actions = ((ACTION_START_PREPARING, t("tour.step.ai_consent.start")),)
            show_next = False
            status = self._search_status_text()
        elif spec.step_id == STEP_LOCAL_PREP:
            if self._local_prep_is_ready():
                title = t("tour.step.local_prep.ready.title")
                body = t("tour.step.local_prep.ready.body")
                show_next = True
            else:
                show_next = False
                if self._local_total > 0:
                    status = t(
                        "tour.step.local_prep.progress",
                        ready=self._local_ready,
                        total=self._local_total,
                    )
                if self._local_error:
                    status = t("tour.status.unavailable")
        elif spec.step_id == STEP_AI_PREP:
            if self._prep_is_ready():
                title = t("tour.step.ai_prep.ready.title")
                body = t("tour.step.ai_prep.ready.body")
                hint = t("tour.step.ai_prep.ready.hint")
                next_label = t("tour.next")
                show_next = True
            else:
                hint = t("tour.step.ai_prep.hint")
                show_next = False
                if self._prep_total > 0:
                    status = t(
                        "tour.step.ai_prep.progress",
                        ready=self._prep_ready,
                        total=self._prep_total,
                    )
                if self._prep_error:
                    status = t("tour.status.unavailable")
        elif spec.step_id == STEP_MEANING_SEARCH:
            hint = t("tour.step.meaning_search.hint")
            status = self._search_status_text()
        elif spec.step_id == STEP_AI_TAG:
            hint = t("tour.step.ai_tag.hint")
        elif spec.step_id == STEP_AI_PREVIEW:
            status = t("tour.status.act_failed") if self._status == "act_failed" else ""
            highlight_all = True
        elif spec.step_id == STEP_ASK_AI_OPEN:
            hint = t("tour.step.ask_ai_open.hint")
            placement = "left"
        elif spec.step_id == STEP_AI_INTRO:
            hint = t("tour.step.ai_intro.hint")
            placement = "left"
        elif spec.step_id == STEP_AI_RESULT:
            next_label = t("tour.finish")
        elif spec.step_id == STEP_AUTOMATE:
            (
                show_next,
                title,
                body,
                hint,
                anchors,
                placement,
                catalog_allow,
                blocking,
            ) = self._automate_guide(title, body)
        elif spec.step_id == STEP_AUTOMATE_IMAGES_RETURN:
            hint = t("tour.step.automate_images_return.hint")
            placement = "right"
        elif spec.step_id == STEP_AUTOMATE_RUN and self._run_done:
            title = t("tour.step.automate_done.title")
            body = t("tour.step.automate_done.body")
            hint = t("tour.step.automate_done.hint")
            show_next = True
        elif spec.step_id == STEP_AUTOMATE_RUN and self._run_confirmed:
            title = t("tour.step.automate_confirm.title")
            body = t("tour.step.automate_confirm.body")
            placement = "below"
            status = t("tour.status.act_failed") if self._status == "act_failed" else ""
        elif spec.step_id == STEP_AUTOMATE_RUN:
            hint = t("tour.step.automate_run.hint")
            placement = "below"
            status = t("tour.status.act_failed") if self._status == "act_failed" else ""
        if not placement and spec.anchors[:1] == (ANCHOR_IMAGES_ASK_AI,):
            placement = "left"
        return TourView(
            active=True,
            guide=GuideView(
                visible=True,
                step_id=spec.step_id,
                index=spec.phase_index,
                total=spec.total,
                phase=spec.phase,
                title=title,
                body=body,
                hint=hint,
                status=status,
                anchors=anchors,
                show_back=False,
                show_next=show_next,
                show_skip=True,
                mode="guide",
                actions=actions,
                next_label=next_label,
                placement=placement,
                catalog_allow=catalog_allow,
                blocking=blocking,
                highlight_all=highlight_all,
                chapter_break=spec.chapter_break,
            ),
        )

    def _automate_guide(self, title: str, body: str) -> tuple:
        hint = ""
        show_next = False
        anchors: tuple[str, ...] = (ANCHOR_AUTOMATION_FOLDER,)
        placement = ""
        catalog_allow: tuple[str, ...] = ()
        blocking = True
        flags = self._automation_flags()
        phase = self._automation_phase
        if phase >= _AUTOMATE_SAVE:
            hint = t("tour.step.automate.hint.save")
            anchors = (ANCHOR_AUTOMATION_SAVE,)
        elif phase == _AUTOMATE_OVERVIEW:
            title = t("tour.step.automate.overview.title")
            body = t("tour.step.automate.overview.body")
            show_next = True
            anchors = (ANCHOR_AUTOMATION_BUILDER,)
        elif phase == _AUTOMATE_SET_TAG:
            title = t("tour.step.automate.tag.title")
            body = t("tour.step.automate.tag.body")
            hint = t("tour.step.automate.tag.hint")
            show_next = bool(flags["has_tag_value"])
            catalog_allow = ("add_tag",)
            anchors = (ANCHOR_AUTOMATION_PARAM, ANCHOR_AUTOMATION_INSPECTOR)
            placement = "below"
            blocking = False
        elif phase == _AUTOMATE_FIT:
            title = t("tour.step.automate.fit.title")
            body = t("tour.step.automate.fit.body")
            hint = t("tour.step.automate.fit.hint")
            anchors = (ANCHOR_AUTOMATION_FIT,)
            placement = "below"
            blocking = False
        elif phase == _AUTOMATE_SET_QUERY:
            title = t("tour.step.automate.query.title")
            body = t("tour.step.automate.query.body")
            hint = t("tour.step.automate.query.hint")
            show_next = bool(flags["has_search_query"])
            anchors = (ANCHOR_AUTOMATION_PARAM, ANCHOR_AUTOMATION_INSPECTOR)
            placement = "below"
            blocking = False
        elif phase == _AUTOMATE_ADD_ACTION:
            title = t("tour.step.automate.action.title")
            catalog_allow = ("add_tag",)
            blocking = False
            if flags["has_action"] and not flags["has_add_tag"]:
                body = t("tour.step.automate.choose_tag.body")
                hint = t("tour.step.automate.choose_tag.hint")
                anchors = (ANCHOR_AUTOMATION_CHOICE, ANCHOR_AUTOMATION_INSPECTOR)
                placement = "below"
            else:
                body = t("tour.step.automate.action.body")
                hint = t("tour.step.automate.action.hint")
                anchors = (ANCHOR_AUTOMATION_ADD_BLOCK,)
        elif phase == _AUTOMATE_ADD_SEARCH:
            title = t("tour.step.automate.search.title")
            catalog_allow = ("text",)
            if flags["has_search"] and not flags["has_text_search"]:
                body = t("tour.step.automate.choose_text.body")
                hint = t("tour.step.automate.choose_text.hint")
                anchors = (ANCHOR_AUTOMATION_CHOICE,)
                placement = "below"
            else:
                body = t("tour.step.automate.search.body")
                hint = t("tour.step.automate.hint")
                anchors = (ANCHOR_AUTOMATION_ADD_BLOCK,)
        elif phase == _AUTOMATE_FOLDER_CONFIRM:
            title = t("tour.step.automate.folder_confirm.title")
            body = t("tour.step.automate.folder_confirm.body")
            show_next = True
            anchors = (ANCHOR_AUTOMATION_FOLDER, ANCHOR_AUTOMATION_INSPECTOR)
        elif phase == _AUTOMATE_NEW:
            title = t("tour.step.automate.new.title")
            body = t("tour.step.automate.new.body")
            hint = t("tour.step.automate.new.hint")
            anchors = (ANCHOR_AUTOMATION_NEW,)
        else:
            title = t("tour.step.automate.title")
            body = t("tour.step.automate.body")
            hint = t("tour.step.automate.hint")
            anchors = (ANCHOR_AUTOMATION_FOLDER, ANCHOR_AUTOMATION_INSPECTOR)
            placement = "below"
            blocking = False
        return show_next, title, body, hint, anchors, placement, catalog_allow, blocking

    def _search_status_text(self) -> str:
        if self._status == "empty":
            return t("tour.status.empty")
        if self._status in {"unavailable", "offline", "unauthenticated", "budget"}:
            return t(f"tour.status.{self._status}")
        return ""
