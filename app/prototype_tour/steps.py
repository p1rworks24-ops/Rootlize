"""Independent Core / Ask AI / Automation guide steps."""

from __future__ import annotations

from app.prototype_tour.models import (
    ANCHOR_AUTOMATION_LIST,
    ANCHOR_AUTOMATION_NEW,
    ANCHOR_AUTOMATION_ADD_BLOCK,
    ANCHOR_AUTOMATION_FOLDER,
    ANCHOR_AUTOMATION_LIST_RUN,
    ANCHOR_AUTOMATION_RUN,
    ANCHOR_AUTOMATION_SAVE,
    ANCHOR_ACT_PREVIEW,
    ANCHOR_IMAGES_ASK_AI,
    ANCHOR_IMAGES_ASK_AI_BUTTON,
    ANCHOR_IMAGES_FOLDER,
    ANCHOR_IMAGES_NAV,
    ANCHOR_IMAGES_SEARCH,
    ANCHOR_SEARCH_RESULTS_GRID,
    LEGACY_STEP_IDS,
    PHASE_ASK_AI,
    PHASE_AUTOMATION,
    PHASE_CORE,
    PHASE_TOTAL,
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
    STEP_AUTOMATE_IMAGES_RETURN,
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_FOLDER,
    STEP_IMAGES_GUIDE,
    STEP_LOCAL_PREP,
    STEP_MEANING_CONFIRM,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    TUTORIAL_AI,
    TUTORIAL_AUTOMATION,
    TUTORIAL_CORE,
    TourStepSpec,
)

CORE_STEPS: tuple[TourStepSpec, ...] = (
    TourStepSpec(
        step_id=STEP_FOLDER,
        phase=PHASE_CORE,
        phase_index=1,
        title_key="tour.step.folder.title",
        body_key="tour.step.folder.body",
        anchors=(ANCHOR_IMAGES_FOLDER,),
        allow_back=False,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_CORE,
    ),
    TourStepSpec(
        step_id=STEP_LOCAL_PREP,
        phase=PHASE_CORE,
        phase_index=1,
        title_key="tour.step.local_prep.title",
        body_key="tour.step.local_prep.body",
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_CORE,
    ),
    TourStepSpec(
        step_id=STEP_IMAGES_GUIDE,
        phase=PHASE_CORE,
        phase_index=1,
        title_key="tour.step.images_guide.title",
        body_key="tour.step.images_guide.body",
        anchors=(ANCHOR_IMAGES_SEARCH,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_CORE,
    ),
)

AI_STEPS: tuple[TourStepSpec, ...] = (
    TourStepSpec(
        step_id=STEP_ASK_AI_OPEN,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ask_ai_open.title",
        body_key="tour.step.ask_ai_open.body",
        anchors=(ANCHOR_IMAGES_ASK_AI_BUTTON,),
        allow_next=True,
        allow_back=False,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_INTRO,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_intro.title",
        body_key="tour.step.ai_intro.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        allow_next=True,
        allow_back=False,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_CONSENT,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_consent.title",
        body_key="tour.step.ai_consent.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_PREP,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_prep.title",
        body_key="tour.step.ai_prep.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_MEANING_EXPLAIN,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.meaning_explain.title",
        body_key="tour.step.meaning_explain.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_MEANING_SEARCH,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.meaning_search.title",
        body_key="tour.step.meaning_search.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_MEANING_CONFIRM,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.meaning_confirm.title",
        body_key="tour.step.meaning_confirm.body",
        anchors=(ANCHOR_SEARCH_RESULTS_GRID, ANCHOR_IMAGES_ASK_AI),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_ACTION,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_action.title",
        body_key="tour.step.ai_action.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_TAG,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_tag.title",
        body_key="tour.step.ai_tag.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_PREVIEW,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_preview.title",
        body_key="tour.step.ai_preview.body",
        anchors=(ANCHOR_ACT_PREVIEW, ANCHOR_IMAGES_ASK_AI),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_DONE,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_done.title",
        body_key="tour.step.ai_done.body",
        anchors=(ANCHOR_IMAGES_ASK_AI,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_IMAGES_RETURN,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_images_return.title",
        body_key="tour.step.ai_images_return.body",
        anchors=(ANCHOR_IMAGES_NAV,),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
    TourStepSpec(
        step_id=STEP_AI_RESULT,
        phase=PHASE_ASK_AI,
        phase_index=1,
        title_key="tour.step.ai_result.title",
        body_key="tour.step.ai_result.body",
        anchors=(ANCHOR_SEARCH_RESULTS_GRID,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AI,
    ),
)

AUTOMATION_STEPS: tuple[TourStepSpec, ...] = (
    TourStepSpec(
        step_id=STEP_AUTOMATE_PAGE,
        phase=PHASE_AUTOMATION,
        phase_index=1,
        title_key="tour.step.automate_page.title",
        body_key="tour.step.automate_page.body",
        anchors=(ANCHOR_AUTOMATION_LIST, ANCHOR_AUTOMATION_NEW),
        allow_next=True,
        allow_back=False,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AUTOMATION,
    ),
    TourStepSpec(
        step_id=STEP_AUTOMATE,
        phase=PHASE_AUTOMATION,
        phase_index=1,
        title_key="tour.step.automate.title",
        body_key="tour.step.automate.body",
        anchors=(ANCHOR_AUTOMATION_FOLDER, ANCHOR_AUTOMATION_ADD_BLOCK),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AUTOMATION,
    ),
    TourStepSpec(
        step_id=STEP_AUTOMATE_SAVE_CONFIRM,
        phase=PHASE_AUTOMATION,
        phase_index=1,
        title_key="tour.step.automate_save_confirm.title",
        body_key="tour.step.automate_save_confirm.body",
        anchors=(ANCHOR_AUTOMATION_SAVE,),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AUTOMATION,
    ),
    TourStepSpec(
        step_id=STEP_AUTOMATE_RUN,
        phase=PHASE_AUTOMATION,
        phase_index=1,
        title_key="tour.step.automate_run.title",
        body_key="tour.step.automate_run.body",
        anchors=(ANCHOR_AUTOMATION_LIST_RUN, ANCHOR_AUTOMATION_RUN),
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AUTOMATION,
    ),
    TourStepSpec(
        step_id=STEP_AUTOMATE_IMAGES_RETURN,
        phase=PHASE_AUTOMATION,
        phase_index=1,
        title_key="tour.step.automate_images_return.title",
        body_key="tour.step.automate_images_return.body",
        anchors=(ANCHOR_IMAGES_NAV, ANCHOR_SEARCH_RESULTS_GRID),
        allow_next=True,
        index=1,
        total=PHASE_TOTAL,
        tutorial=TUTORIAL_AUTOMATION,
    ),
)

TOUR_STEPS: tuple[TourStepSpec, ...] = CORE_STEPS + AI_STEPS + AUTOMATION_STEPS
CORE_SEQUENCE: tuple[str, ...] = tuple(step.step_id for step in CORE_STEPS)
AI_SEQUENCE: tuple[str, ...] = (STEP_ASK_AI_OPEN, STEP_AI_INTRO)
AUTOMATION_SEQUENCE: tuple[str, ...] = tuple(step.step_id for step in AUTOMATION_STEPS)
TOUR_SEQUENCE: tuple[str, ...] = CORE_SEQUENCE
AI_ON_SEQUENCE = AI_SEQUENCE
NO_AI_SEQUENCE = CORE_SEQUENCE
PRE_ROUTE_SEQUENCE = CORE_SEQUENCE

_BY_ID = {step.step_id: step for step in TOUR_STEPS}
_SEQUENCE_BY_TUTORIAL = {
    TUTORIAL_CORE: CORE_SEQUENCE,
    TUTORIAL_AI: AI_SEQUENCE,
    TUTORIAL_AUTOMATION: AUTOMATION_SEQUENCE,
}


def step_spec(step_id: str) -> TourStepSpec | None:
    mapped = LEGACY_STEP_IDS.get(step_id, step_id)
    return _BY_ID.get(mapped)


def tutorial_for_step(step_id: str) -> str:
    spec = step_spec(step_id)
    if spec is not None:
        return spec.tutorial
    return TUTORIAL_CORE


def inferred_route(step_id: str, route: str = "") -> str:
    del step_id, route
    return ""


def sequence_for(route: str = "") -> tuple[str, ...]:
    return _SEQUENCE_BY_TUTORIAL.get(str(route or TUTORIAL_CORE), CORE_SEQUENCE)


def next_step_id(step_id: str, route: str = "") -> str | None:
    current = LEGACY_STEP_IDS.get(step_id, step_id)
    seq = _SEQUENCE_BY_TUTORIAL.get(str(route or tutorial_for_step(current)), CORE_SEQUENCE)
    if current not in seq:
        return None
    index = seq.index(current)
    if index + 1 < len(seq):
        return seq[index + 1]
    return None


def previous_step_id(step_id: str, route: str = "") -> str | None:
    current = LEGACY_STEP_IDS.get(step_id, step_id)
    seq = _SEQUENCE_BY_TUTORIAL.get(str(route or tutorial_for_step(current)), CORE_SEQUENCE)
    if current not in seq:
        return None
    index = seq.index(current)
    if index > 0:
        return seq[index - 1]
    return None


def resume_step_id(step_id: str) -> str:
    mapped = LEGACY_STEP_IDS.get(step_id, step_id)
    if mapped in _BY_ID:
        return mapped
    return STEP_FOLDER
