"""Eval-only Vision Judge candidates for Phase E A/B.

These prompts are not imported by app/. Product search keeps
vision-meaning-v1. usefulness-v2 failed smoke (dog FP, UI FP almost
unchanged, mountain wallpaper FN unchanged) and must not be copied into
the product judge.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.relevance.openai_provider import PROMPT_VERSION, SYSTEM_PROMPT
from tools.meaning_eval.describe_judge import (
    DESCRIBE_JUDGE_VERSION,
    DESCRIBE_PROMPT,
    TEXT_JUDGE_VERSION,
)

# Stage 1: recall-oriented screen. Pass unless clearly unrelated.
# Prefer true when uncertain so a later high-detail pass can decide.
STAGE1_SCREENING_PROMPT = """You are a generic image-search candidate screener.

A user searched their own image library with the given query.
For every supplied image, decide whether it should continue to a stricter
second review.

This is a low-detail screening pass. Details of a scene can be easy to miss.
When you are uncertain, relevant is true.

Do not drop a candidate merely because the wording is imperfect, the view is
partial, or the main content is an ordinary visual equivalent of the query.
If the main visible content might reasonably be what the user asked for,
relevant is true.

Return relevant false only when the image is clearly about something else —
the query does not describe the main content even loosely, including common
synonyms and ordinary visual equivalents.

Use the same standard for every query. Do not classify the query into types,
and do not apply special-case rules for particular words.

relevant true means the image should be reviewed again. relevant false means
it is not a useful search result.
relevance_score is a number from 0 to 1 for how likely the image is useful
as a result. confidence is how sure you are of this judgement. confidence is
not relevance_score.

Judge the visible image itself. Do not use similarity scores, filenames,
ranking, or assumed metadata.
Return exactly one result for every supplied image_id."""

# Stage 2: precision-oriented usefulness. Primary subject, not medium,
# not nested thumbnails, ordinary equivalents still allowed.
STAGE2_USEFULNESS_PROMPT = """You are a generic image-search result judge.

A user searched their own image library with the given query.
For every supplied image, judge how reasonable it would be to show that
image as a search result for this query.

Judge search-result usefulness / image-query relevance, not mere object
presence. Ask: if the user ran this query, would they expect this image
in the result list because this picture itself is what they asked for?

Apply these rules to every query:

The query must fit the image as a whole: its primary subject, type, style,
scene, or state. A match that is only incidental, tiny, background,
peripheral, a fragment, a crop, or a small element inside UI or chrome is
not useful. Do not mark those as relevant.

Nested pictures, thumbnails, previews, or rows inside another screen are
incidental. A useful result is an image whose own main content is the query,
not a browser, gallery, or manager that happens to display it.

Treat capture medium as medium. Words that only say the image is a photo,
screenshot, or screen capture do not make every captured image a match.
The rest of the query must be the main subject shown. If the query asks for
an environment or workspace, that environment must be the main scene, not
merely the place where some other program was captured.

Do not stretch wording that is true of many library images, such as being
a screen capture, a window, or software on a display. Shared computer-screen
context is not enough. The distinctive part of the query must be the main
thing shown. A different screen, tool, or subject is false even if it is
weakly related.

For style, state, or scene wording, object presence alone is not enough.
The requested look, state, or scene must be the dominant impression.

Do not reject an image only because a more precise caption would use
slightly different words. If the main content is what people commonly mean
by the query, relevant is true.

relevant is true only when a typical user would reasonably expect this
image in the result list. relevant is false when they would not. If you
would describe the image as not really what was asked for, only related,
only a fragment, or mainly something else, relevant is false and
relevance_score is low. relevant must agree with that judgement.

Use the same usefulness standard for every query. Do not classify the
query into types, and do not apply special-case rules for particular words.

relevance_score is a number from 0 to 1 for how useful the image is as a
result for this query. Higher means a more primary, intended match.
confidence is how sure you are of this judgement. confidence is not
relevance_score.

Judge the visible image itself. Do not use similarity scores, filenames,
ranking, or assumed metadata.
Return exactly one result for every supplied image_id."""


STRUCTURE_TWO_STAGE = "two_stage"
STRUCTURE_DESCRIBE_THEN_JUDGE = "describe_then_judge"
STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE = "describe_then_text_judge"
DESCRIBE_STRUCTURES = frozenset({
    STRUCTURE_DESCRIBE_THEN_JUDGE,
    STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE,
})


@dataclass(frozen=True)
class JudgeCandidate:
    name: str
    version: str
    low_prompt: str | None
    high_prompt: str | None
    structure: str = STRUCTURE_TWO_STAGE
    describe_prompt: str | None = None


CANDIDATES = {
    "baseline": JudgeCandidate(
        name="baseline",
        version=PROMPT_VERSION,
        low_prompt=None,
        high_prompt=None,
    ),
    "usefulness-v2": JudgeCandidate(
        name="usefulness-v2",
        version="vision-usefulness-v2",
        low_prompt=STAGE1_SCREENING_PROMPT,
        high_prompt=STAGE2_USEFULNESS_PROMPT,
    ),
    "describe-judge-v1": JudgeCandidate(
        name="describe-judge-v1",
        version=DESCRIBE_JUDGE_VERSION,
        low_prompt=None,
        high_prompt=None,
        structure=STRUCTURE_DESCRIBE_THEN_JUDGE,
        describe_prompt=DESCRIBE_PROMPT,
    ),
    "describe-text-judge-v1": JudgeCandidate(
        name="describe-text-judge-v1",
        version=TEXT_JUDGE_VERSION,
        low_prompt=None,
        high_prompt=None,
        structure=STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE,
        describe_prompt=DESCRIBE_PROMPT,
    ),
}

BASELINE_PROMPT = SYSTEM_PROMPT
