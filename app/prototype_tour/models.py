"""Prototype Guided Experience contracts. No image or library data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TourStatus = Literal["not_started", "in_progress", "completed", "skipped"]

STATUS_NOT_STARTED: TourStatus = "not_started"
STATUS_IN_PROGRESS: TourStatus = "in_progress"
STATUS_COMPLETED: TourStatus = "completed"
STATUS_SKIPPED: TourStatus = "skipped"

TUTORIAL_CORE = "core"
TUTORIAL_AI = "ai"
TUTORIAL_AUTOMATION = "automation"

STEP_AUTH = "auth"
STEP_WELCOME = "welcome"
STEP_FOLDER_INTRO = "folder_intro"
STEP_FOLDER = "folder"
STEP_LOCAL_PREP_EXPLAIN = "local_prep_explain"
STEP_LOCAL_PREP = "local_prep"
STEP_IMAGES_GUIDE = "images_guide"
STEP_BASIC_SEARCH = "basic_search"
STEP_BASIC_SEARCH_CONFIRM = "basic_search_confirm"
STEP_SELECT = "select"
STEP_SELECT_CONFIRM = "select_confirm"
STEP_FAVORITE = "favorite"
STEP_CHAPTER1_DONE = "chapter1_done"
STEP_ASK_AI_OPEN = "ask_ai_open"
STEP_AI_INTRO = "ai_intro"
STEP_AI_CHOICE = "ai_choice"
STEP_AI_CONSENT = "ai_consent"
STEP_AI_PREP = "ai_prep"
STEP_MEANING_EXPLAIN = "meaning_explain"
STEP_MEANING_SEARCH = "meaning_search"
STEP_MEANING_CONFIRM = "meaning_confirm"
STEP_AI_ACTION = "ai_action"
STEP_AI_TAG = "ai_tag"
STEP_AI_PREVIEW = "ai_preview"
STEP_AI_DONE = "ai_action_done"
STEP_AI_IMAGES_RETURN = "ai_images_return"
STEP_AI_RESULT = "ai_result"
STEP_CHAPTER2_DONE = "chapter2_done"
STEP_ORGANIZE_HINT = "organize_hint"
STEP_FIND = "find"
STEP_TAGS_SORT = "tags_sort"
STEP_AUTOMATE_INTRO = "automate_intro"
STEP_AUTOMATE_NAV = "automate_nav"
STEP_AUTOMATE_PAGE = "automate_page"
STEP_ACT = "act"
STEP_TAG_VALUE = "tag_value"
STEP_AUTOMATE = "automate"
STEP_AUTOMATE_SAVE_CONFIRM = "automate_save_confirm"
STEP_AUTOMATE_RUN = "automate_run"
STEP_AUTOMATE_IMAGES_RETURN = "automate_images_return"
STEP_COMPLETE = "complete"
STEP_FEEDBACK = "feedback"
STEP_THANKS = "thanks"
STEP_IDLE = "idle"

PHASE_CORE = "core"
PHASE_FIND = PHASE_CORE
PHASE_ASK_AI = "ask_ai"
PHASE_AUTOMATION = "automation"
PHASE_EXPLORE = PHASE_CORE
PHASE_ORGANIZE = PHASE_CORE
PHASE_AUTOMATE = PHASE_AUTOMATION
PHASE_TOTAL = 1

TOUR_STEP_IDS = (
    STEP_FOLDER,
    STEP_LOCAL_PREP,
    STEP_IMAGES_GUIDE,
    STEP_ASK_AI_OPEN,
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
    STEP_AI_IMAGES_RETURN,
    STEP_AI_RESULT,
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_IMAGES_RETURN,
)

ROUTE_AI = "ai"
ROUTE_NO_AI = "no_ai"

ACTION_USE_AI = "use_ai"
ACTION_SKIP_AI = "skip_ai"
ACTION_START_PREPARING = "start_preparing"
ACTION_TRY_AI_SEARCH = "try_ai_search"

# Older in-progress tours stored these step ids. Resume maps them forward.
LEGACY_STEP_IDS = {
    STEP_AUTH: STEP_FOLDER,
    STEP_WELCOME: STEP_FOLDER,
    STEP_FOLDER_INTRO: STEP_FOLDER,
    STEP_LOCAL_PREP_EXPLAIN: STEP_LOCAL_PREP,
    STEP_AI_CHOICE: STEP_IMAGES_GUIDE,
    STEP_ACT: STEP_IMAGES_GUIDE,
    STEP_TAG_VALUE: STEP_AUTOMATE,
    STEP_TAGS_SORT: STEP_IMAGES_GUIDE,
    STEP_ORGANIZE_HINT: STEP_IMAGES_GUIDE,
    STEP_FIND: STEP_IMAGES_GUIDE,
    STEP_BASIC_SEARCH: STEP_IMAGES_GUIDE,
    STEP_BASIC_SEARCH_CONFIRM: STEP_IMAGES_GUIDE,
    STEP_SELECT: STEP_IMAGES_GUIDE,
    STEP_SELECT_CONFIRM: STEP_IMAGES_GUIDE,
    STEP_FAVORITE: STEP_IMAGES_GUIDE,
    STEP_CHAPTER1_DONE: STEP_IMAGES_GUIDE,
    STEP_CHAPTER2_DONE: STEP_AI_DONE,
    STEP_AUTOMATE_INTRO: STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE_NAV: STEP_AUTOMATE_PAGE,
}

EVENT_ONBOARDING_STARTED = "onboarding_started"
EVENT_FOLDER_SELECTED = "folder_selected"
EVENT_ONBOARDING_COMPLETED = "onboarding_completed"
EVENT_ONBOARDING_SKIPPED = "onboarding_skipped"
EVENT_AI_TUTORIAL_STARTED = "ai_tutorial_started"
EVENT_AI_PREPARATION_STARTED = "ai_preparation_started"
EVENT_MEANING_SEARCH_COMPLETED = "meaning_search_completed"
EVENT_AI_TUTORIAL_COMPLETED = "ai_tutorial_completed"
EVENT_AI_TUTORIAL_SKIPPED = "ai_tutorial_skipped"
EVENT_ASK_AI_CONSENT_SHOWN = "ask_ai_consent_shown"
EVENT_ASK_AI_CONSENT_ACCEPTED = "ask_ai_consent_accepted"
EVENT_ASK_AI_CONSENT_CANCELLED = "ask_ai_consent_cancelled"
EVENT_AUTOMATION_TUTORIAL_STARTED = "automation_tutorial_started"
EVENT_WORKFLOW_SAVED = "workflow_saved"
EVENT_WORKFLOW_RUN = "workflow_run"
EVENT_AUTOMATION_TUTORIAL_COMPLETED = "automation_tutorial_completed"
EVENT_AUTOMATION_TUTORIAL_SKIPPED = "automation_tutorial_skipped"
EVENT_FEEDBACK_SHOWN = "feedback_shown"
EVENT_FEEDBACK_SUBMITTED = "feedback_submitted"
EVENT_FEEDBACK_DISMISSED = "feedback_dismissed"

# Legacy names kept as aliases so older tests / local files can migrate.
EVENT_PROTOTYPE_STARTED = EVENT_ONBOARDING_STARTED
EVENT_CHAPTER_FIND_STARTED = EVENT_ONBOARDING_STARTED
EVENT_CHAPTER_FIND_COMPLETED = EVENT_ONBOARDING_COMPLETED
EVENT_CHAPTER_AI_STARTED = EVENT_AI_TUTORIAL_STARTED
EVENT_CHAPTER_AI_COMPLETED = EVENT_AI_TUTORIAL_COMPLETED
EVENT_CHAPTER_AUTOMATION_STARTED = EVENT_AUTOMATION_TUTORIAL_STARTED
EVENT_CHAPTER_AUTOMATION_COMPLETED = EVENT_AUTOMATION_TUTORIAL_COMPLETED
EVENT_PROTOTYPE_COMPLETED = EVENT_ONBOARDING_COMPLETED
EVENT_PROTOTYPE_SKIPPED = EVENT_ONBOARDING_SKIPPED
EVENT_AI_SETUP_OFFERED = "ai_setup_offered"
EVENT_AI_SETUP_ACCEPTED = "ai_setup_accepted"
EVENT_AI_SETUP_DECLINED = "ai_setup_declined"
EVENT_FIND_COMPLETED = EVENT_MEANING_SEARCH_COMPLETED
EVENT_SELECT_COMPLETED = "select_completed"
EVENT_ACT_COMPLETED = "act_completed"
EVENT_FAVORITE_ADDED = "favorite_added"
EVENT_TAG_ADDED = "tag_added"
EVENT_AI_ACTION_COMPLETED = "ai_action_completed"
EVENT_BASIC_SEARCH_COMPLETED = "basic_search_completed"
EVENT_AUTOMATION_CREATED = EVENT_WORKFLOW_SAVED
EVENT_AUTOMATION_RUN = EVENT_WORKFLOW_RUN
EVENT_AUTOMATION_COMPLETED = EVENT_WORKFLOW_SAVED
EVENT_FEEDBACK_OPENED = "feedback_opened"
EVENT_TOUR_STARTED = EVENT_ONBOARDING_STARTED
EVENT_TOUR_SKIPPED = EVENT_ONBOARDING_SKIPPED

LEGACY_ANALYTICS_EVENTS = {
    "tour_started": EVENT_ONBOARDING_STARTED,
    "prototype_started": EVENT_ONBOARDING_STARTED,
    "chapter_find_started": EVENT_ONBOARDING_STARTED,
    "chapter_find_completed": EVENT_ONBOARDING_COMPLETED,
    "prototype_completed": EVENT_ONBOARDING_COMPLETED,
    "prototype_skipped": EVENT_ONBOARDING_SKIPPED,
    "tour_skipped": EVENT_ONBOARDING_SKIPPED,
    "chapter_ai_started": EVENT_AI_TUTORIAL_STARTED,
    "chapter_ai_completed": EVENT_AI_TUTORIAL_COMPLETED,
    "ai_setup_offered": EVENT_AI_TUTORIAL_STARTED,
    "ai_setup_accepted": EVENT_AI_TUTORIAL_STARTED,
    "ai_setup_declined": EVENT_ONBOARDING_STARTED,
    "find_completed": EVENT_MEANING_SEARCH_COMPLETED,
    "chapter_automation_started": EVENT_AUTOMATION_TUTORIAL_STARTED,
    "chapter_automation_completed": EVENT_AUTOMATION_TUTORIAL_COMPLETED,
    "automation_created": EVENT_WORKFLOW_SAVED,
    "automation_completed": EVENT_WORKFLOW_SAVED,
    "automation_run": EVENT_WORKFLOW_RUN,
    "act_completed": EVENT_FAVORITE_ADDED,
    "tag_added": EVENT_FAVORITE_ADDED,
}

UI_FOLDER_SELECTED = "folder_selected"
UI_FIND_FINISHED = "find_finished"
UI_FIND_FAILED = "find_failed"
UI_SELECTION_CHANGED = "selection_changed"
UI_FAVORITE_CHANGED = "favorite_changed"
UI_ASK_AI_OPENED = "ask_ai_opened"
UI_ACT_PREVIEW_SHOWN = "act_preview_shown"
UI_ACT_COMPLETED = "act_completed"
UI_IMAGES_PAGE_SHOWN = "images_page_shown"
UI_AUTOMATION_OPENED = "automation_opened"
UI_AUTOMATION_PAGE_SHOWN = "automation_page_shown"
UI_AUTOMATION_BLOCK_CHANGED = "automation_block_changed"
UI_AUTOMATION_FITTED = "automation_fitted"
UI_AUTOMATION_SAVED = "automation_saved"
UI_AUTOMATION_RUN = "automation_run_started"
UI_AUTOMATION_RUN_FINISHED = "automation_run_finished"

MOST_USEFUL_CHOICES = ("search", "favorite", "ai_search", "automate")
LEGACY_MOST_USEFUL = {
    "find": "search",
    "select": "search",
    "act": "favorite",
}
WOULD_USE_CHOICES = ("definitely", "probably", "not_sure", "probably_not")
EASIER_CHOICES = ("much_easier", "a_little_easier", "about_the_same", "harder")
PAYMENT_CHOICES = ("yes", "maybe", "only_if_inexpensive", "no")

ALLOWED_ANALYTICS_EVENTS = frozenset(
    {
        EVENT_ONBOARDING_STARTED,
        EVENT_FOLDER_SELECTED,
        EVENT_ONBOARDING_COMPLETED,
        EVENT_ONBOARDING_SKIPPED,
        EVENT_AI_TUTORIAL_STARTED,
        EVENT_AI_PREPARATION_STARTED,
        EVENT_MEANING_SEARCH_COMPLETED,
        EVENT_AI_TUTORIAL_COMPLETED,
        EVENT_AI_TUTORIAL_SKIPPED,
        EVENT_ASK_AI_CONSENT_SHOWN,
        EVENT_ASK_AI_CONSENT_ACCEPTED,
        EVENT_ASK_AI_CONSENT_CANCELLED,
        EVENT_AUTOMATION_TUTORIAL_STARTED,
        EVENT_WORKFLOW_SAVED,
        EVENT_WORKFLOW_RUN,
        EVENT_AUTOMATION_TUTORIAL_COMPLETED,
        EVENT_AUTOMATION_TUTORIAL_SKIPPED,
        EVENT_FEEDBACK_SHOWN,
        EVENT_FEEDBACK_SUBMITTED,
        EVENT_FEEDBACK_DISMISSED,
    }
)

# Widget identifiers. Positions come from live widgets, never hardcoded coords.
ANCHOR_ACCOUNT_NAV = "account_nav"
ANCHOR_ACCOUNT_SIGN_IN = "account_sign_in"
ANCHOR_IMAGES_NAV = "images_nav"
ANCHOR_IMAGES_FOLDER = "images_folder"
ANCHOR_IMAGES_SEARCH = "images_search"
ANCHOR_IMAGES_ORGANIZE = "images_organize"
ANCHOR_IMAGES_TAGS = "images_tags"
ANCHOR_IMAGES_FAVORITE = "images_favorite"
ANCHOR_IMAGES_ASK_AI = "images_ask_ai"
ANCHOR_IMAGES_ASK_AI_BUTTON = "images_ask_ai_button"
ANCHOR_SEARCH_RESULTS_GRID = "search_results_grid"
ANCHOR_ACT_PREVIEW = "act_preview"
ANCHOR_AUTOMATION_NAV = "automation_nav"
ANCHOR_AUTOMATION_NEW = "automation_new"
ANCHOR_AUTOMATION_LIST = "automation_list"
ANCHOR_AUTOMATION_BUILDER = "automation_builder"
ANCHOR_AUTOMATION_ADD_BLOCK = "automation_add_block"
ANCHOR_AUTOMATION_FOLDER = "automation_folder"
ANCHOR_AUTOMATION_INSPECTOR = "automation_inspector"
ANCHOR_AUTOMATION_CHOICE = "automation_choice"
ANCHOR_AUTOMATION_PARAM = "automation_param"
ANCHOR_AUTOMATION_SAVE = "automation_save"
ANCHOR_AUTOMATION_RUN = "automation_run"
ANCHOR_AUTOMATION_LIST_RUN = "automation_list_run"
ANCHOR_AUTOMATION_FIT = "automation_fit"
ANCHOR_ASK_AI_SAVE = "ask_ai_save_automation"

SUGGESTED_TAG = "prototype-test"
ACTION_ADD_TAG = "add_tag"


@dataclass(frozen=True)
class TourStepSpec:
    step_id: str
    phase: str
    phase_index: int
    title_key: str
    body_key: str
    anchors: tuple[str, ...] = ()
    allow_next: bool = False
    allow_back: bool = True
    index: int = 0
    total: int = PHASE_TOTAL
    chapter_break: bool = False
    tutorial: str = TUTORIAL_CORE


@dataclass
class TourRecord:
    status: TourStatus = STATUS_NOT_STARTED
    session_id: str = ""
    current_step: str = STEP_IDLE
    welcome_seen: bool = False
    signed_in_offer_done: bool = False
    started_at: str = ""
    completed_at: str = ""
    skipped_at: str = ""
    ai_calls: int = 0
    ai_route: str = ""
    ai_prep_started: bool = False
    ai_status: TourStatus = STATUS_NOT_STARTED
    ai_step: str = STEP_IDLE
    automation_status: TourStatus = STATUS_NOT_STARTED
    automation_step: str = STEP_IDLE
    feedback_offered: bool = False


@dataclass(frozen=True)
class AnalyticsEvent:
    event_name: str
    occurred_at: str
    session_id: str
    user_id: str = ""


FEEDBACK_VERSION = "v2"


@dataclass(frozen=True)
class FeedbackPayload:
    prototype_session_id: str
    completed_at: str
    most_useful: str = ""
    would_use: str = ""
    easier_than_current: str = ""
    confusing_text: str = ""
    willingness_to_pay: str = ""
    app_version: str = ""
    user_id: str = ""
    feedback_version: str = FEEDBACK_VERSION

    def public_fields(self) -> dict[str, str]:
        """Fields safe to persist. No query, path, image, facts, or OCR."""
        return {
            "prototype_session_id": self.prototype_session_id,
            "completed_at": self.completed_at,
            "most_useful": self.most_useful,
            "would_use": self.would_use,
            "easier_than_current": self.easier_than_current,
            "confusing_text": self.confusing_text,
            "willingness_to_pay": self.willingness_to_pay,
            "app_version": self.app_version,
            "user_id": self.user_id,
            "feedback_version": self.feedback_version,
        }


@dataclass
class GuideView:
    visible: bool = False
    step_id: str = STEP_IDLE
    index: int = 0
    total: int = PHASE_TOTAL
    phase: str = ""
    title: str = ""
    body: str = ""
    hint: str = ""
    status: str = ""
    anchors: tuple[str, ...] = ()
    show_back: bool = False
    show_next: bool = False
    show_skip: bool = True
    mode: str = "guide"  # welcome | guide | complete | feedback | thanks
    actions: tuple[tuple[str, str], ...] = ()
    next_label: str = ""
    placement: str = ""
    catalog_allow: tuple[str, ...] = ()
    blocking: bool = True
    highlight_all: bool = False
    hidden_feedback_choices: tuple[str, ...] = ()
    chapter_break: bool = False


@dataclass
class TourView:
    active: bool = False
    guide: GuideView = field(default_factory=GuideView)
