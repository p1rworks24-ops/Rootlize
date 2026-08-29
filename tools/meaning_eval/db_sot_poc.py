"""Independent DB Source-of-Truth search PoC.

Parse a small image set once with Vision, store facts as the search source of
truth, then judge queries from those facts only. Search never resends images.

Does not change product search, Hybrid, Vision Judge, matcher, threshold,
GT v2, or artifacts/meaning-eval/latest.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval.describe_judge import add_usage, empty_usage, estimate_usd
from tools.meaning_eval.identity import corpus_identity, git_identity
from tools.meaning_eval.metrics import end_to_end_counts, f1_score, summarize_end_to_end

DEFAULT_FOLDER = Path(r"D:\07_Programs\shotlogue_test")
DEFAULT_OUTPUT = (
    ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-poc-facts-v5"
)
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
INPUT_USD_PER_MILLION = 0.75
OUTPUT_USD_PER_MILLION = 4.50
PROMPT_VERSION = "db-sot-facts-v5"
SCHEMA_VERSION = "image-facts-v3"
SEARCH_PROMPT_VERSION = "db-sot-search-v1.4"
SEARCH_SCHEMA_VERSION = "db-sot-relevance-v3"

SELECTED_IMAGES = (
    {
        "name": "A2.png",
        "reason": "一般物体の代表。座位のオレンジブラウン柴犬で、属性・状態の段階絞り込みに使える。",
    },
    {
        "name": "images.jpg",
        "reason": "別の犬。立ち姿勢・白茶の毛色で、A2.png との属性/状態対比に使う。",
    },
    {
        "name": "27750021_m.jpg",
        "reason": "猫の写真。dog の明確な負例であり、属性・状態・床との関係条件も試せる。",
    },
    {
        "name": "20260716_194437.png",
        "reason": "Windows desktop 上で PowerShell が Chrome (vlr.gg) に重なる複合画面。環境+アプリ+関係を試す。",
    },
    {
        "name": "20260718_201711.png",
        "reason": "Windows desktop の Google Chrome で ChatGPT を表示。application + content + environment。",
    },
    {
        "name": "20260718_210026.png",
        "reason": "暗い Cursor のコードエディタ。ターミナル前面表示はなく、204024 との関係条件対比に使う。",
    },
    {
        "name": "20260718_204024.png",
        "reason": "暗いコードエディタの前面に PowerShell がある。code editor with terminal の関係条件用。",
    },
    {
        "name": "Screenshot_001.png",
        "reason": "Windows File Explorer。Capixe.exe 選択状態があり、folder UI と具体状態を試せる。",
    },
    {
        "name": "about.png",
        "reason": "Capixe の About/Feedback UI。desktop を含まない設定系画面として負例・設定query用。",
    },
    {
        "name": "20260813_225929.png",
        "reason": "Screenshot manager のギャラリー。犬サムネイルが同居し、入れ子対象と複雑queryを試せる。",
    },
    {
        "name": "20260718_205213.png",
        "reason": "Windows desktop の Chrome / YouTube で VALORANT 試合。game + browser + environment。",
    },
    {
        "name": "ScreenShot_Atest_002.png",
        "reason": "Screenshot Manager + PowerShell + Chrome ChatGPT + Windows desktop が同居する最複雑例。",
    },
)

QUERIES = (
    {
        "query": "dog",
        "kind": "entity",
        "difficulty": "easy",
        "must_include": ["A2.png", "images.jpg", "20260813_225929.png"],
        "notes": "入れ子サムネイルの犬も実画像上は識別できる。",
    },
    {
        "query": "cat",
        "kind": "entity",
        "difficulty": "easy",
        "must_include": ["27750021_m.jpg"],
    },
    {
        "query": "orange brown dog",
        "kind": "attribute",
        "difficulty": "medium",
        "must_include": ["A2.png", "20260813_225929.png"],
        "notes": "images.jpg は白+薄茶の立ち犬で、主色はオレンジブラウンではない。",
    },
    {
        "query": "sitting dog",
        "kind": "state",
        "difficulty": "medium",
        "must_include": ["A2.png", "20260813_225929.png"],
        "notes": "images.jpg は立ち。ギャラリー内の A2 サムネは座位。",
    },
    {
        "query": "standing dog",
        "kind": "state",
        "difficulty": "medium",
        "must_include": ["images.jpg", "20260813_225929.png"],
    },
    {
        "query": "sitting orange brown dog",
        "kind": "and",
        "difficulty": "hard",
        "must_include": ["A2.png", "20260813_225929.png"],
    },
    {
        "query": "Google Chrome",
        "kind": "application",
        "difficulty": "easy",
        "must_include": [
            "20260716_194437.png",
            "20260718_201711.png",
            "20260718_205213.png",
            "ScreenShot_Atest_002.png",
        ],
        "notes": "タスクバーの Chrome アイコンのみは含めない。",
    },
    {
        "query": "Windows desktop",
        "kind": "environment",
        "difficulty": "easy",
        "must_include": [
            "20260716_194437.png",
            "20260718_201711.png",
            "20260718_210026.png",
            "20260718_204024.png",
            "Screenshot_001.png",
            "20260718_205213.png",
            "ScreenShot_Atest_002.png",
        ],
        "notes": "about.png とギャラリー作物、写真は desktop 環境ではない。",
    },
    {
        "query": "Google Chrome in Windows desktop",
        "kind": "app_env",
        "difficulty": "medium",
        "must_include": [
            "20260716_194437.png",
            "20260718_201711.png",
            "20260718_205213.png",
            "ScreenShot_Atest_002.png",
        ],
    },
    {
        "query": "ChatGPT in a browser",
        "kind": "relationship",
        "difficulty": "medium",
        "must_include": ["20260718_201711.png", "ScreenShot_Atest_002.png"],
    },
    {
        "query": "Google Chrome showing YouTube VALORANT",
        "kind": "relationship",
        "difficulty": "hard",
        "must_include": ["20260718_205213.png"],
        "notes": "194437 は vlr.gg の大会表で、YouTube 上の試合映像ではない。",
    },
    {
        "query": "code editor",
        "kind": "ui",
        "difficulty": "easy",
        "must_include": ["20260718_210026.png", "20260718_204024.png"],
        "notes": "ChatGPT 画面はコードエディタではない。",
    },
    {
        "query": "dark code editor",
        "kind": "attribute",
        "difficulty": "medium",
        "must_include": ["20260718_210026.png", "20260718_204024.png"],
    },
    {
        "query": "code editor with terminal visible",
        "kind": "relationship",
        "difficulty": "hard",
        "must_include": ["20260718_204024.png"],
        "notes": "210026 は Cursor だが前面のターミナルウィンドウは見えない。",
    },
    {
        "query": "file explorer window",
        "kind": "ui",
        "difficulty": "easy",
        "must_include": ["Screenshot_001.png"],
    },
    {
        "query": "screenshot manager",
        "kind": "application",
        "difficulty": "easy",
        "must_include": [
            "about.png",
            "20260813_225929.png",
            "ScreenShot_Atest_002.png",
        ],
        "notes": "Capixe About も製品UIとして含める。ログに名前が出るだけの 194437 は除外。",
    },
    {
        "query": "screenshot manager showing a dog",
        "kind": "coexistence",
        "difficulty": "hard",
        "must_include": ["20260813_225929.png"],
    },
    {
        "query": "PowerShell",
        "kind": "application",
        "difficulty": "easy",
        "must_include": [
            "20260716_194437.png",
            "20260718_204024.png",
            "ScreenShot_Atest_002.png",
        ],
    },
    {
        "query": "Windows desktop with Chrome and PowerShell",
        "kind": "and",
        "difficulty": "hard",
        "must_include": ["20260716_194437.png", "ScreenShot_Atest_002.png"],
        "notes": "204024 の Chrome はタスクバーアイコンのみ。",
    },
    {
        "query": "calico cat lying on a wooden floor",
        "kind": "and",
        "difficulty": "hard",
        "must_include": ["27750021_m.jpg"],
    },
    {
        "query": "File Explorer with Capixe.exe selected",
        "kind": "state",
        "difficulty": "hard",
        "must_include": ["Screenshot_001.png"],
    },
)

FACT_PROMPT = """You record visible facts from images.

A later search will treat this record as the only evidence. It will not see
the original pixels again. Store confirmed, reusable facts that a later
reader could use against an unknown query. Do not label the image for a
guessed search term. Do not write a keyword dump. Do not judge usefulness.

Record only what you can confirm. If uncertain, omit it rather than guess.

scene / environment:
- scene_description: compact factual summary. This is not the source of truth.
- environment: the visible setting only, such as outdoor grass, indoor wooden
  floor, or Windows desktop environment. Record Windows desktop only when
  desktop chrome is visible (taskbar, wallpaper, desktop icons, overlapping
  windows on the desktop). Do not infer Windows desktop just because an
  application window exists.

applications:
- name: canonical product/OS/site name if identifiable (Cursor, Google Chrome,
  Windows PowerShell, Capixe, File Explorer, YouTube).
- category: the product's ordinary function category. If the product identity
  is already confirmed, attach that identity's ordinary category even when
  the visible screen is settings, about, feedback, or help rather than the
  main workspace. This is not guessing an unknown app from generic UI.
  Examples of confirmed identity -> category: Cursor -> code editor / IDE;
  Google Chrome -> web browser; Windows PowerShell -> terminal /
  command-line shell; File Explorer -> file manager / file explorer;
  Capixe -> screenshot manager / image management application.
- If the product is unidentified, leave category empty rather than inventing
  a function from a generic layout. Do not stop at the proper name when the
  identity's ordinary category is known.

ui_types:
- What kind of screen/window is actually present: Windows desktop environment,
  browser window, code editor, terminal window, file explorer window,
  image gallery, settings screen, screenshot manager, folder-selection UI.
- Record multiple if several are visible. Do not record a type you cannot see.
- If a background window is identifiably a code editor / IDE, record
  code editor. Do not reduce it to generic "application window" because a
  terminal is in front.

entities / objects:
- Name the depicted subject (dog, cat, Capixe.exe). Do not use chrome
  labels ("thumbnail", "preview widget") or a filename as the entity name
  when the depicted subject is identifiable. A separate container entity is
  optional and extra, never a substitute for the depicted subject.
- A thumbnail of an identifiable dog is still name=dog, kind=animal. Do not
  record only the filename (A2.png, images.jpg) in place of that animal.
- Record every independently identifiable entity. Identifiability is the
  test. Size, off-center placement, being secondary, or living inside
  another image/window/cell does not remove this duty.
- If you cannot tell what the subject is, omit it. Do not exhaustively
  parse every icon or unreadable fragment.

Completing an identified entity:
- After an entity is independently identifiable, check the same fields you
  would check for any other entity. Do not stop after naming it.
- Record a field only when it is confirmable. Completing an entity does
  not mean filling every slot. Unconfirmed fields stay empty.
- A wrong stored value is worse than an empty field on that same entity.
  That is not a reason to omit the entity, omit a visible ui_type, or
  replace a depicted dog with a filename.
- If you can identify a dog, record the dog. If you cannot confirm its
  posture or a color distinction, leave those fields empty.
- Partial identifiability is enough to record the entity. Do not skip the
  whole entity because one field is unclear.
- Do not treat secondary, nested, small, or off-center entities as a
  different class. They use the same fields and the same confirmation bar.
- Size, off-center placement, secondary role, or nested placement are not
  a reason to omit a confirmable field, and are not a reason to guess an
  unconfirmable one.

attributes, colors, posture, states:
- Record clearly visible attributes and states: sitting / standing / lying,
  empty, selected, dark / light.
- posture: if sitting, standing, or lying is visually clear, store that
  value. If those three cannot be told apart, leave posture empty rather
  than picking the nearest or a typical pose. Do not fill from breed or
  "probably". Empty is for ambiguity, not a default for every animal.
- sitting: haunches on the ground, front legs upright, chest off the
  ground.
- standing: four (or the visible supporting) legs extended, torso off the
  ground. A full-body dog standing on a checkerboard is standing.
- lying: the torso is on the ground.
- Nested or small animals: if sitting vs standing vs lying is not
  distinguishable at the available size, leave posture empty. Do not guess
  lying. Do not skip the animal.
- Do not write sitting, standing, or lying into attributes, states, or
  observed_color_description unless posture stores that same value.
- colors: canonical color concepts a person might type, normalized, not a
  synonym dump. Separate nearby hues. orange-brown is a saturated reddish
  or orange brown (example: Shiba-like red coat). Do not collapse that to
  brown. tan is pale sandy / beige tan. light brown is light brown. These
  are not interchangeable. If a coat is fairly orange-brown, write
  orange-brown. If it is only pale tan / cream / white, write those and do
  not also add orange-brown. If orange-brown vs brown vs tan is not
  actually distinguishable, omit the uncertain color rather than collapsing
  to a nearby generic brown.
- Ordinary coat patterns belong in attributes when clearly visible: calico,
  tabby, spotted. These are pattern names a person would type, not extra
  color synonyms.
- observed_color_description: a short description of the seen coloring
  (for example "reddish orange-brown coat with white muzzle" or "mostly
  white coat with pale tan patches"). This is not a license to add extra
  canonical colors.
- Put colors, posture, states, visibility, and identifiability on the same
  entity they belong to. Do not mix one entity's color with another's pose.

relationships:
- Record important visible relations: ChatGPT displayed in Google Chrome,
  Chrome running within Windows desktop environment, PowerShell in front of
  or behind another application, YouTube displaying VALORANT content,
  selected file is Capixe.exe, a depicted subject shown inside a gallery.
- Record what is actually visible, not a query-specific answer.

visibility / identifiability:
- visible, partially_visible, or nested. clear or partial.
- Background windows that are identifiable by title or distinctive UI must be
  named. Do not leave an identifiable Cursor/IDE window as "dark application".

Do not invent names, brands, animals, or states. Empty arrays are allowed.
Return exactly one result for every image_id."""

SEARCH_PROMPT = """You search an image library using stored facts only.

You will not see any image. For each image you receive a fact record that
was written earlier from Vision. That record is the source of truth.

You do not decide the final relevant flag. You only extract independent
conditions and mark each one confirmed or not from the stored facts.
Later code sets relevant from those condition results:
- every listed condition confirmed=true -> relevant=true
- any listed condition confirmed=false -> relevant=false
Do not add a second judgment after the conditions. Do not use typicality,
aboutness, primary-subject, screen type, or "the query asked for the name
X rather than product Y" to reverse a condition result.

Interpret the user query as meaning, not as a bag of words.
A named concept is one condition even if it has several words
("code editor" is one concept).
Independent extra conditions are attributes, states, additional targets,
an environment, or a relation.

How to split conditions:
- "code editor" -> [code editor]
- "screenshot manager" -> [screenshot manager]
- "screenshot manager showing a dog" -> [screenshot manager, dog]
- "sitting orange brown dog" -> one target with [dog, sitting, orange-brown]
- "orange brown dog" -> one target with [dog, orange-brown]
- "Google Chrome in Windows desktop" -> [Google Chrome, Windows desktop,
  relation between them]
Do not split a single concept into words. Do not drop a named target.
Do not add sitting, standing, typical screen type, or primary-subject
requirements the query did not name.
Every image in this response must use the same condition labels, taken
only from the query. If the query is "dog", every image lists only [dog].
Do not copy attributes from a record into the condition list.

A recorded product whose category is screenshot manager / image management
application confirms the condition "screenshot manager". The product's
proper name (Capixe) does not block that confirmation.

A condition is confirmed only when the stored facts support it.

Existence is not inferred.
If the query explicitly requires an entity or object, that entity must appear
in the record as that entity itself, or as a record that is clearly the same
thing. Taxonomy / identity mapping is allowed (Shiba Inu or puppy -> dog;
recorded "code editor / IDE" -> "code editor").
Existence guessing is forbidden. Do not supply a missing entity from general
knowledge, UI context, thumbnail grids, preview panes, selected files, or
colors.
A screenshot manager with blue / green / tan thumbnails is not a dog.
A selected thumbnail or image file is not a dog.
"showing a dog" requires a recorded dog (or clearly the same animal), not
merely that some image is shown.
If the required entity is absent from the facts, it is unconfirmed.

Attributes, states, and relations follow the same rule: confirm only what the
record states. Do not guess a missing color, posture, or relation.

Color matching:
- Confirm a color only when the recorded canonical colors or observed color
  description express that same color concept.
- Equivalent wording of one recorded concept is allowed
  (orange brown = orange-brown; sitting = seated).
- Adjacent hues are not the same concept. tan is not orange-brown.
  light brown is not orange-brown. white + tan is not orange-brown.
- Do not widen the query color toward a nearby recorded color to force a
  match. If orange-brown is not in the record, "orange brown dog" fails.

Same-target conditions:
- If the query attributes several facts to one target, those facts must hold
  of the same recorded entity. Do not combine sitting from one entity with
  orange-brown from another.
- A relation query needs the participants and a recorded basis for the
  relation (environment, relationships, or equivalent). Chrome and a Windows
  desktop listed separately are not enough without that relation.

A recorded incidental or nested fact still counts if the query does not
require the match to be the primary subject.
Do not add extra requirements the query did not state.
Do not use the filename as evidence.
Do not assume the real image contains extra unrecorded details.

independent_conditions must list every independent query condition as a short
label (dog, sitting, orange-brown, screenshot manager, code editor), whether
the record confirms it, and the evidence taken from the record (empty if
absent). List only conditions the query actually states. If the query names
a target you did not list, that is an error; list it.
reason summarizes which listed conditions the record confirms or does not
confirm. Do not add a second judgment after those conditions.

Return exactly one result for every image_id."""


def _json_load(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _api_key() -> str:
    import os

    return os.environ.get("OPENAI_API_KEY", "")


def encode_image(path: Path, *, max_edge: int) -> dict:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        width, height = image.size
        output = BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
    jpeg = output.getvalue()
    encoded = base64.b64encode(jpeg).decode("ascii")
    return {
        "data_url": f"data:image/jpeg;base64,{encoded}",
        "sha256": hashlib.sha256(jpeg).hexdigest(),
        "width": width,
        "height": height,
        "bytes": len(jpeg),
    }


def post_chat(
    payload: dict,
    *,
    api_key: str,
    endpoint: str,
    timeout_seconds: float,
    retries: int,
) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries + 1):
        request = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
            if not retryable or attempt >= retries:
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt >= retries:
                raise RuntimeError("request timed out or could not connect") from exc
        time.sleep((2 ** attempt) + random.random() * 0.25)
    raise AssertionError("unreachable")


def parse_message(response: dict) -> dict:
    content = response["choices"][0]["message"]["content"]
    parsed = json.loads(content) if isinstance(content, str) else content
    if not isinstance(parsed, dict):
        raise RuntimeError("structured result was not an object")
    return parsed


def usage_from_response(response: dict) -> dict:
    usage = response.get("usage") or {}
    return {
        "request_count": 1,
        "request_attempt_count": 1,
        "retry_count": 0,
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        "api_seconds": 0.0,
        "total_seconds": 0.0,
        "sent_image_count": 0,
    }


def fact_schema(image_ids: list[int]) -> dict:
    entity = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 80},
            "kind": {
                "type": "string",
                "enum": ["animal", "person", "character", "object", "place", "other"],
            },
            "attributes": {
                "type": "array",
                "items": {"type": "string", "maxLength": 80},
                "maxItems": 8,
            },
            "colors": {
                "type": "array",
                "items": {"type": "string", "maxLength": 40},
                "maxItems": 6,
            },
            "states": {
                "type": "array",
                "items": {"type": "string", "maxLength": 60},
                "maxItems": 6,
            },
            "posture": {"type": "string", "maxLength": 40},
            "observed_color_description": {"type": "string", "maxLength": 120},
            "visibility": {
                "type": "string",
                "enum": ["visible", "partially_visible", "nested"],
            },
            "identifiability": {
                "type": "string",
                "enum": ["clear", "partial"],
            },
        },
        "required": [
            "name",
            "kind",
            "attributes",
            "colors",
            "states",
            "posture",
            "observed_color_description",
            "visibility",
            "identifiability",
        ],
        "additionalProperties": False,
    }
    application = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 80},
            "category": {"type": "string", "maxLength": 80},
            "kind": {
                "type": "string",
                "enum": ["os", "application", "website", "service", "game", "other"],
            },
            "role": {
                "type": "string",
                "enum": ["primary", "secondary", "incidental"],
            },
            "theme": {
                "type": "string",
                "enum": ["dark", "light", "mixed", "unknown"],
            },
            "visible_content": {"type": "string", "maxLength": 240},
        },
        "required": [
            "name",
            "category",
            "kind",
            "role",
            "theme",
            "visible_content",
        ],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "image_id": {"type": "integer", "enum": image_ids},
            "media_type": {
                "type": "string",
                "enum": ["photograph", "screenshot", "illustration", "mixed", "other"],
            },
            "scene_description": {"type": "string", "maxLength": 500},
            "environment": {"type": "string", "maxLength": 240},
            "ui_types": {
                "type": "array",
                "items": {"type": "string", "maxLength": 80},
                "maxItems": 8,
            },
            "entities": {"type": "array", "items": entity, "maxItems": 12},
            "applications": {"type": "array", "items": application, "maxItems": 12},
            "activities": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 10,
            },
            "relationships": {
                "type": "array",
                "items": {"type": "string", "maxLength": 180},
                "maxItems": 12,
            },
            "notable_text": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 12,
            },
        },
        "required": [
            "image_id",
            "media_type",
            "scene_description",
            "environment",
            "ui_types",
            "entities",
            "applications",
            "activities",
            "relationships",
            "notable_text",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
        "additionalProperties": False,
    }


def search_schema(image_ids: list[int]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_id": {"type": "integer", "enum": image_ids},
                        "independent_conditions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "condition": {"type": "string", "maxLength": 80},
                                    "confirmed": {"type": "boolean"},
                                    "evidence": {"type": "string", "maxLength": 140},
                                },
                                "required": ["condition", "confirmed", "evidence"],
                                "additionalProperties": False,
                            },
                            "maxItems": 8,
                        },
                        "reason": {"type": "string", "maxLength": 180},
                    },
                    "required": [
                        "image_id",
                        "independent_conditions",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def chat_payload(
    *,
    model: str,
    system: str,
    user: list | str,
    schema_name: str,
    schema: dict,
    temperature: float | None,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user,
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def format_fact_record(record: dict) -> str:
    apps = record.get("applications") or []
    entities = record.get("entities") or []
    app_lines = []
    for item in apps:
        category = item.get("category") or "(no category)"
        theme = item.get("theme") or "unknown"
        app_lines.append(
            f"  - {item.get('name')} [{category}] "
            f"({item.get('kind')}, {item.get('role')}, {theme}): "
            f"{item.get('visible_content')}"
        )
    entity_lines = []
    for item in entities:
        colors = "/".join(item.get("colors") or []) or "(none)"
        observed = item.get("observed_color_description") or "(none)"
        posture = item.get("posture") or "(unconfirmed)"
        states = "/".join(item.get("states") or []) or "(none)"
        attributes = "/".join(item.get("attributes") or []) or "(none)"
        entity_lines.append(
            "  - "
            f"name={item.get('name')}; kind={item.get('kind')}; "
            f"posture={posture}; canonical_colors={colors}; "
            f"observed_color={observed}; states={states}; "
            f"attributes={attributes}; visibility={item.get('visibility')}; "
            f"identifiability={item.get('identifiability')}"
        )
    ui_types = record.get("ui_types") or []
    lines = [
        f"image_id: {record.get('image_id')}",
        f"media_type: {record.get('media_type')}",
        f"environment: {record.get('environment') or '(none)'}",
        "ui_types: " + ", ".join(ui_types) if ui_types else "ui_types: (none)",
        f"scene: {record.get('scene_description')}",
        "entities:",
        *(entity_lines or ["  - (none)"]),
        "applications:",
        *(app_lines or ["  - (none)"]),
        "activities: " + "; ".join(record.get("activities") or []) or "activities: (none)",
        "relationships: " + "; ".join(record.get("relationships") or []) or "relationships: (none)",
        "notable_text: " + "; ".join(record.get("notable_text") or []) or "notable_text: (none)",
    ]
    return "\n".join(lines)


def flatten_fact_text(record: dict) -> str:
    chunks = [
        record.get("scene_description") or "",
        record.get("environment") or "",
        record.get("media_type") or "",
        " ".join(record.get("ui_types") or []),
    ]
    for item in record.get("entities") or []:
        chunks.extend(
            [
                item.get("name") or "",
                item.get("kind") or "",
                " ".join(item.get("states") or []),
                item.get("posture") or "",
                " ".join(item.get("attributes") or []),
                " ".join(item.get("colors") or []),
                item.get("observed_color_description") or "",
                item.get("visibility") or "",
                item.get("identifiability") or "",
            ]
        )
    for item in record.get("applications") or []:
        chunks.extend(
            [
                item.get("name") or "",
                item.get("category") or "",
                item.get("kind") or "",
                item.get("theme") or "",
                item.get("visible_content") or "",
            ]
        )
    chunks.extend(record.get("activities") or [])
    chunks.extend(record.get("relationships") or [])
    chunks.extend(record.get("notable_text") or [])
    return " ".join(str(part).lower() for part in chunks if part)


def analyze_image(
    *,
    image_id: int,
    path: Path,
    api_key: str,
    model: str,
    endpoint: str,
    max_edge: int,
    image_detail: str,
    temperature: float | None,
    timeout_seconds: float,
    retries: int,
) -> tuple[dict, dict, float]:
    encoded = encode_image(path, max_edge=max_edge)
    payload = chat_payload(
        model=model,
        system=FACT_PROMPT,
        user=[
            {
                "type": "text",
                "text": (
                    f"Record visible facts for image_id {image_id}. "
                    "Do not infer a user query. Record independently "
                    "identifiable depicted subjects as those subjects, not "
                    "as filenames. Leave unconfirmed posture/color/state "
                    "empty. Do not guess a pose. Do not omit a dog or a "
                    "visible code editor because a field is unconfirmed."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": encoded["data_url"], "detail": image_detail},
            },
        ],
        schema_name="image_facts",
        schema=fact_schema([image_id]),
        temperature=temperature,
    )
    started = time.perf_counter()
    response = post_chat(
        payload,
        api_key=api_key,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    elapsed = time.perf_counter() - started
    parsed = parse_message(response)
    results = parsed.get("results") or []
    if len(results) != 1 or int(results[0].get("image_id")) != image_id:
        raise RuntimeError(f"unexpected fact payload for {path.name}")
    usage = usage_from_response(response)
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    usage["sent_image_count"] = 1
    record = dict(results[0])
    record["filename"] = path.name
    record["encode"] = {
        "sha256": encoded["sha256"],
        "width": encoded["width"],
        "height": encoded["height"],
        "bytes": encoded["bytes"],
        "max_edge": max_edge,
        "image_detail": image_detail,
    }
    return record, usage, elapsed


def search_query(
    *,
    query: str,
    records: list[dict],
    api_key: str,
    model: str,
    endpoint: str,
    temperature: float | None,
    timeout_seconds: float,
    retries: int,
) -> tuple[list[dict], dict, float]:
    image_ids = [int(item["image_id"]) for item in records]
    record_by_id = {int(item["image_id"]): item for item in records}
    docs = "\n\n".join(format_fact_record(item) for item in records)
    payload = chat_payload(
        model=model,
        system=SEARCH_PROMPT,
        user=(
            f"Query: {query}\n\n"
            "Stored facts (source of truth). Judge only from these facts.\n"
            "List every independent condition the query states. Do not add "
            "extra conditions. If the query names an entity, that entity "
            "must be listed. A thumbnail is not that entity. Do not output "
            "a final relevant flag.\n\n"
            f"{docs}"
        ),
        schema_name="db_sot_relevance",
        schema=search_schema(image_ids),
        temperature=temperature,
    )
    started = time.perf_counter()
    response = post_chat(
        payload,
        api_key=api_key,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    elapsed = time.perf_counter() - started
    parsed = parse_message(response)
    by_id = {
        int(item["image_id"]): item
        for item in parsed.get("results") or []
        if isinstance(item, dict) and "image_id" in item
    }
    missing = [image_id for image_id in image_ids if image_id not in by_id]
    if missing:
        raise RuntimeError(f"search omitted image_ids={missing} query={query!r}")
    usage = usage_from_response(response)
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    ordered = [
        enforce_condition_consistency(
            filter_query_conditions(by_id[image_id], query=query),
            query=query,
            record=record_by_id[image_id],
        )
        for image_id in image_ids
    ]
    return ordered, usage, elapsed


EXPLICIT_ENTITY_ALIASES = (
    ("dog", ("dog", "puppy", "puppies", "shiba inu", "shiba")),
    ("cat", ("cat", "kitten", "kittens", "calico")),
)


def missing_explicit_entities(query: str, record: dict) -> list[str]:
    blob = flatten_fact_text(record).replace("-", " ")
    query_text = f" {query.lower().replace('-', ' ')} "
    missing = []
    for name, aliases in EXPLICIT_ENTITY_ALIASES:
        if f" {name} " not in query_text and f" {name}s " not in query_text:
            continue
        if not any(alias in blob for alias in aliases):
            missing.append(name)
    return missing


def normalize_condition_label(label: object) -> str:
    return " ".join(str(label or "").strip().lower().replace("-", " ").split())


GLUE_CONDITION_LABELS = {
    "showing",
    "show",
    "with",
    "in",
    "and",
    "of",
    "on",
    "a",
    "the",
    "for",
    "visible",
}


def condition_mentioned_in_query(label: str, query: str) -> bool:
    query_n = normalize_condition_label(query)
    return bool(label) and label in query_n


def filter_query_conditions(item: dict, *, query: str) -> dict:
    """Keep query meaning-units; drop glue words and attributes the query did not name."""
    original = [row for row in (item.get("independent_conditions") or []) if isinstance(row, dict)]
    kept = []
    extras = []
    for row in original:
        label = normalize_condition_label(row.get("condition"))
        if not label or label in GLUE_CONDITION_LABELS or not condition_mentioned_in_query(label, query):
            extras.append(str(row.get("condition") or ""))
            continue
        kept.append(row)
    item["independent_conditions"] = kept
    item["ignored_extra_conditions"] = extras
    return item


def relevant_from_conditions(
    conditions: list,
    *,
    extra_unconfirmed: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Final relevant is decided from condition rows, not from a model flag."""
    rows = [row for row in conditions if isinstance(row, dict)]
    unconfirmed = [
        str(row.get("condition") or "")
        for row in rows
        if row.get("confirmed") is not True
    ]
    for name in extra_unconfirmed or []:
        if name not in unconfirmed:
            unconfirmed.append(name)
    if not rows:
        return False, unconfirmed
    return (len(unconfirmed) == 0, unconfirmed)


def enforce_condition_consistency(item: dict, *, query: str, record: dict) -> dict:
    """relevant is true iff every listed condition is confirmed and no required entity is missing."""
    conditions = item.get("independent_conditions") or []
    relevant, unconfirmed = relevant_from_conditions(
        conditions,
        extra_unconfirmed=missing_explicit_entities(query, record),
    )
    item["unconfirmed_conditions"] = unconfirmed
    item["relevant"] = relevant
    item["relevant_source"] = "conditions"
    return item


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def write_report(output: Path, report: dict) -> None:
    identity = report["identity"]
    model = report["model"]
    usage = report["usage"]
    metrics = report["metrics"]
    lines = [
        "# DB Source-of-Truth PoC",
        "",
        "## Run identity",
        "",
        f"- timestamp: `{identity['timestamp']}`",
        f"- git commit: `{identity['git_commit']}` dirty={identity['git_dirty']}",
        f"- vision/search model: `{model['model']}`",
        f"- API: `{model['endpoint']}`",
        f"- temperature: `{model['temperature']}`",
        f"- vision: `{model['prompt_version']}` / `{model['schema_version']}` "
        f"max_edge={model['max_edge']} detail={model['image_detail']}",
        f"- search: `{model['search_prompt_version']}` / `{model['search_schema_version']}`",
        f"- corpus: {identity['corpus']['count']} selected images",
        f"- queries: {len(report['queries'])}",
        "",
        "## Design",
        "",
        "First Vision pass stores confirmed visible facts as the search source of truth.",
        "v5 keeps image-facts-v3. Unconfirmed posture/color/state stay empty;",
        "a wrong stored fact is worse than a blank. Search v1.4 lists",
        "independent conditions only. Final relevant is decided in code from",
        "those rows: all confirmed -> true; any unconfirmed -> false.",
        "Conditions not stated by the query, and glue words such as showing,",
        "are dropped before that decision.",
        "Search may map identity but must not invent missing entities or",
        "nearby color synonyms. Search sends query + stored facts only.",
        "Images are not resent. No lexical threshold, Hybrid band, or Vision Judge.",
        "",
        "## Selected images",
        "",
        "| file | reason |",
        "|---|---|",
    ]
    for item in report["selected_images"]:
        lines.append(f"| `{item['name']}` | {item['reason']} |")
    lines.extend(
        [
            "",
            "## Cost and time",
            "",
            f"- vision requests: {usage['vision']['request_count']}",
            f"- vision tokens: {usage['vision']['input_tokens']} in / {usage['vision']['output_tokens']} out",
            f"- vision estimated USD: ${usage['vision']['estimated_usd']:.4f}",
            f"- vision USD / image: ${usage['per_image_vision_usd']:.4f}",
            f"- search requests: {usage['search']['request_count']}",
            f"- search tokens: {usage['search']['input_tokens']} in / {usage['search']['output_tokens']} out",
            f"- search estimated USD: ${usage['search']['estimated_usd']:.4f}",
            f"- search USD / query: ${usage['per_query_search_usd']:.4f}",
            f"- total estimated USD: ${usage['total_estimated_usd']:.4f}",
            f"- vision seconds: {usage['vision']['total_seconds']:.1f}",
            f"- search seconds: {usage['search']['total_seconds']:.1f}",
            f"- total seconds: {usage['total_seconds']:.1f}",
            "",
            "## Metrics",
            "",
            f"- macro P/R/F1: {metrics['all']['macro_precision']:.3f} / "
            f"{metrics['all']['macro_recall']:.3f} / {metrics['all']['macro_f1']:.3f}",
            f"- micro TP/FP/FN: {metrics['all']['micro_tp']} / "
            f"{metrics['all']['micro_fp']} / {metrics['all']['micro_fn']}",
            "",
            "| difficulty | n | macro P | macro R | macro F1 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for key in ("easy", "medium", "hard"):
        row = metrics[key]
        lines.append(
            f"| {key} | {row['n']} | {row['macro_precision']:.3f} | "
            f"{row['macro_recall']:.3f} | {row['macro_f1']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Per query",
            "",
            "| query | kind | difficulty | P | R | F1 | TP | FP | FN | predicted | expected |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in report["queries"]:
        lines.append(
            "| `{query}` | {kind} | {difficulty} | {precision:.3f} | {recall:.3f} | "
            "{f1:.3f} | {tp} | {fp} | {fn} | {predicted} | {expected} |".format(
                query=row["query"],
                kind=row["kind"],
                difficulty=row["difficulty"],
                precision=row["precision"],
                recall=row["recall"],
                f1=row["f1"],
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                predicted=", ".join(f"`{name}`" for name in row["predicted"]) or "(none)",
                expected=", ".join(f"`{name}`" for name in row["must_include"]) or "(none)",
            )
        )
    lines.extend(["", "## Errors", ""])
    if not report["errors"]:
        lines.append("None.")
    else:
        for row in report["errors"]:
            lines.append(
                f"- `{row['query']}` {row['kind']} `{row['name']}`: {row['reason']}"
            )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--max-edge", type=int, default=768)
    parser.add_argument("--image-detail", default="high")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--reuse-facts", action="store_true")
    args = parser.parse_args()

    api_key = _api_key()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing")

    folder = args.folder
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    selected = list(SELECTED_IMAGES)
    paths = []
    for item in selected:
        path = folder / item["name"]
        if not path.is_file():
            raise SystemExit(f"missing image: {path}")
        paths.append(path)
    id_by_name = {path.name: index + 1 for index, path in enumerate(paths)}
    name_by_id = {image_id: name for name, image_id in id_by_name.items()}

    facts_path = output / "facts.json"
    search_path = output / "search.jsonl"
    existing_facts = _json_load(facts_path) if args.reuse_facts else None
    records = []
    vision_usage = empty_usage()
    vision_seconds = 0.0
    if existing_facts and existing_facts.get("records"):
        records = list(existing_facts["records"])
        vision_usage = add_usage(vision_usage, existing_facts.get("usage") or {})
        print(json.dumps({"stage": "reuse_facts", "count": len(records)}, ensure_ascii=False), flush=True)
    completed_image_ids = {int(item["image_id"]) for item in records}
    if len(completed_image_ids) < len(paths):
        for path in paths:
            image_id = id_by_name[path.name]
            if image_id in completed_image_ids:
                continue
            print(
                json.dumps({"stage": "vision", "image": path.name, "image_id": image_id}, ensure_ascii=False),
                flush=True,
            )
            record, usage, elapsed = analyze_image(
                image_id=image_id,
                path=path,
                api_key=api_key,
                model=args.model,
                endpoint=args.endpoint,
                max_edge=args.max_edge,
                image_detail=args.image_detail,
                temperature=0.0,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
            )
            records.append(record)
            vision_usage = add_usage(vision_usage, usage)
            vision_seconds += elapsed
            _write_json(
                facts_path,
                {
                    "prompt_version": PROMPT_VERSION,
                    "schema_version": SCHEMA_VERSION,
                    "records": records,
                    "usage": vision_usage,
                },
            )
        vision_usage["total_seconds"] = vision_seconds
        vision_usage["api_seconds"] = vision_seconds

    records.sort(key=lambda item: int(item["image_id"]))
    _write_json(
        facts_path,
        {
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "records": records,
            "usage": vision_usage,
        },
    )

    done_queries = {}
    if search_path.is_file():
        for line in search_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done_queries[row["query"]] = row

    search_usage = empty_usage()
    query_rows = []
    errors = []
    if search_path.exists() and not done_queries:
        search_path.unlink()
    for spec in QUERIES:
        cached = done_queries.get(spec["query"])
        if cached:
            query_rows.append(cached)
            search_usage = add_usage(search_usage, cached.get("usage") or {})
            continue
        print(json.dumps({"stage": "search", "query": spec["query"]}, ensure_ascii=False), flush=True)
        judged, usage, elapsed = search_query(
            query=spec["query"],
            records=records,
            api_key=api_key,
            model=args.model,
            endpoint=args.endpoint,
            temperature=0.0,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        usage["total_seconds"] = elapsed
        predicted = [
            name_by_id[int(item["image_id"])]
            for item in judged
            if item.get("relevant") is True
        ]
        counts = end_to_end_counts(
            must_include=set(spec["must_include"]),
            acceptable=set(),
            predicted=set(predicted),
        )
        row = {
            "query": spec["query"],
            "kind": spec["kind"],
            "difficulty": spec["difficulty"],
            "notes": spec.get("notes") or "",
            "must_include": list(spec["must_include"]),
            "predicted": predicted,
            "precision": counts["precision"],
            "recall": counts["recall"],
            "f1": f1_score(counts["precision"], counts["recall"]),
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "tp_names": counts["tp_names"],
            "fp_names": counts["fp_names"],
            "fn_names": counts["fn_names"],
            "judgements": [
                {
                    "name": name_by_id[int(item["image_id"])],
                    "relevant": item.get("relevant"),
                    "independent_conditions": item.get("independent_conditions") or [],
                    "presence_validation_failures": item.get("presence_validation_failures") or [],
                    "unconfirmed_conditions": item.get("unconfirmed_conditions") or [],
                    "ignored_extra_conditions": item.get("ignored_extra_conditions") or [],
                    "relevant_source": item.get("relevant_source") or "conditions",
                    "reason": item.get("reason"),
                }
                for item in judged
            ],
            "usage": usage,
        }
        query_rows.append(row)
        search_usage = add_usage(search_usage, usage)
        with search_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    for row in query_rows:
        fact_by_name = {item["filename"]: item for item in records}
        for name in row["fn_names"]:
            errors.append(
                {
                    "query": row["query"],
                    "kind": "FN",
                    "name": name,
                    "reason": next(
                        (
                            item["reason"]
                            for item in row["judgements"]
                            if item["name"] == name
                        ),
                        "",
                    ),
                    "fact_text": flatten_fact_text(fact_by_name[name]),
                }
            )
        for name in row["fp_names"]:
            errors.append(
                {
                    "query": row["query"],
                    "kind": "FP",
                    "name": name,
                    "reason": next(
                        (
                            item["reason"]
                            for item in row["judgements"]
                            if item["name"] == name
                        ),
                        "",
                    ),
                    "fact_text": flatten_fact_text(fact_by_name[name]),
                }
            )

    metrics = {
        "all": summarize_end_to_end(query_rows),
        "easy": summarize_end_to_end([row for row in query_rows if row["difficulty"] == "easy"]),
        "medium": summarize_end_to_end([row for row in query_rows if row["difficulty"] == "medium"]),
        "hard": summarize_end_to_end([row for row in query_rows if row["difficulty"] == "hard"]),
        "by_kind": {},
    }
    kinds = sorted({row["kind"] for row in query_rows})
    for kind in kinds:
        metrics["by_kind"][kind] = summarize_end_to_end(
            [row for row in query_rows if row["kind"] == kind]
        )

    vision_usd = estimate_usd(int(vision_usage["input_tokens"]), int(vision_usage["output_tokens"]))
    search_usd = estimate_usd(int(search_usage["input_tokens"]), int(search_usage["output_tokens"]))
    n_images = max(1, len(records))
    n_queries = max(1, len(query_rows))
    vision_usage["estimated_usd"] = vision_usd
    search_usage["estimated_usd"] = search_usd
    report = {
        "identity": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **git_identity(),
            "corpus": corpus_identity(paths),
        },
        "model": {
            "model": args.model,
            "endpoint": args.endpoint,
            "temperature": 0.0,
            "max_edge": args.max_edge,
            "image_detail": args.image_detail,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "search_prompt_version": SEARCH_PROMPT_VERSION,
            "search_schema_version": SEARCH_SCHEMA_VERSION,
        },
        "selected_images": selected,
        "usage": {
            "vision": vision_usage,
            "search": search_usage,
            "total_estimated_usd": vision_usd + search_usd,
            "per_image_vision_usd": vision_usd / n_images,
            "per_query_search_usd": search_usd / n_queries,
            "total_seconds": float(vision_usage.get("total_seconds") or 0)
            + float(search_usage.get("total_seconds") or 0),
        },
        "metrics": metrics,
        "queries": query_rows,
        "errors": errors,
        "pricing": {
            "input_usd_per_million": INPUT_USD_PER_MILLION,
            "output_usd_per_million": OUTPUT_USD_PER_MILLION,
        },
    }
    _write_json(output / "results.json", report)
    write_report(output / "summary.md", report)
    print(
        json.dumps(
            {
                "stage": "done",
                "macro_f1": metrics["all"]["macro_f1"],
                "usd": report["usage"]["total_estimated_usd"],
                "output": str(output),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
