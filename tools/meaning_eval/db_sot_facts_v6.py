"""Generalized first-Vision facts improvements for the DB-SoT evaluation only."""

import base64
import hashlib
from io import BytesIO
import time

from PIL import Image, ImageOps

from tools.meaning_eval import db_sot_poc as poc


PROMPT_VERSION = "db-sot-facts-v6b-multiscale-evidence"
SCHEMA_VERSION = poc.SCHEMA_VERSION
DEFAULT_MAX_EDGE = 1536

FACT_PROMPT = poc.FACT_PROMPT + r"""

Systematic coverage pass (query-independent):
- Before returning, scan the image region by region from top-left to
  bottom-right. Treat galleries, result lists, contact sheets, preview panes,
  chat result cards, and images embedded inside other UI as visual content,
  not as decoration.
- Within every region, inventory each independently identifiable subject up
  to the schema limit. When several individuals differ in type, color,
  posture, distinctive feature, position, or container, keep separate entity
  rows. Do not replace several distinct animals with one generic animal row.
- For each recorded subject, make a second visual pass over: type; canonical
  colors/patterns; posture or activity; visually distinctive anatomy, shape,
  markings, clothing, or accessories; relative position/grouping; and whether
  it is nested in a thumbnail, preview, result card, or other container.
- `attributes` is the general home for visually conspicuous, search-useful
  features that distinguish the subject. Describe only what the pixels make
  reasonably clear. This instruction is not a request to guess breed,
  identity, anatomy, state, or any hidden property.
- Use attributes/states/relationships to retain position and grouping when
  useful (for example left thumbnail, right result, grouped with another
  animal, inside a gallery cell). Never use a filename alone to infer the
  depicted subject or its attributes.
- Small size raises the confirmation bar for a field but does not excuse
  skipping a clearly identifiable subject. If type is clear but an attribute
  is not, record the type and leave only that attribute empty.

Application, environment, and surface-role evidence:
- `applications` is only for an OS environment that is visibly present, an
  application/site/service whose rendered interface or content is visibly
  open, or an application that is otherwise directly and reasonably
  identifiable as present. A desktop shortcut, launcher icon, taskbar icon,
  filename, thumbnail of an application, or text mention alone is not an open
  application and must not be put in `applications`.
- Record a visible shortcut/icon as an entity with kind=object and a state or
  attribute such as `desktop shortcut`; name it only if its label/mark is
  identifiable. Record an application screenshot inside a gallery as nested
  content, not as a running application.
- A desktop application title bar alone does not prove that the desktop
  environment is visible. Store Windows desktop only when desktop chrome is
  actually visible: taskbar, wallpaper, desktop icons, or multiple windows
  spatially arranged on the desktop.
- Generic UI resemblance does not establish a product or functional
  category. Name/category claims need visible branding, distinctive product
  UI, or explicit functional evidence on screen. An OCR test/validation panel
  is an OCR tool or test panel; it is not a screenshot manager merely because
  it processes image files. If the evidence supports only a generic type,
  store the generic type and leave the product identity/category narrower
  than the evidence.

Final audit before returning:
1. Did every independently identifiable nested subject get an entity row?
2. Did every entity get its own confirmable color, posture/activity, and
   distinctive visible features without borrowing from another entity?
3. Did any shortcut/icon/thumbnail incorrectly become an open application?
4. Did any OS environment or product/category claim exceed visible evidence?
If yes, correct the record. Empty fields remain preferable to uncertain facts.
"""


def configure() -> None:
    poc.PROMPT_VERSION = PROMPT_VERSION
    poc.SCHEMA_VERSION = SCHEMA_VERSION
    poc.FACT_PROMPT = FACT_PROMPT
    poc.analyze_image = analyze_image_multiscale


def _encode_pil(image: Image.Image, *, max_edge: int) -> dict:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90, optimize=True)
    raw = buffer.getvalue()
    return {
        "data_url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"),
        "width": image.width,
        "height": image.height,
        "bytes": len(raw),
    }


def _multiscale_views(path, *, max_edge: int) -> list[tuple[str, dict]]:
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        views = [("Full image overview", _encode_pil(source.copy(), max_edge=max_edge))]
        if source.width < 900 and source.height < 700:
            return views
        overlap = 0.08
        x_mid = source.width // 2
        y_mid = source.height // 2
        x_pad = int(source.width * overlap)
        y_pad = int(source.height * overlap)
        boxes = (
            (0, 0, min(source.width, x_mid + x_pad), min(source.height, y_mid + y_pad)),
            (max(0, x_mid - x_pad), 0, source.width, min(source.height, y_mid + y_pad)),
            (0, max(0, y_mid - y_pad), min(source.width, x_mid + x_pad), source.height),
            (max(0, x_mid - x_pad), max(0, y_mid - y_pad), source.width, source.height),
        )
        for index, box in enumerate(boxes, 1):
            views.append((f"Detail region {index} of 4", _encode_pil(source.crop(box), max_edge=1024)))
        return views


def _normalize_record(record: dict) -> dict:
    """Enforce facts-layer surface roles without touching search matching."""
    blocked_surfaces = ("shortcut", "taskbar icon", "launcher icon", "thumbnail")
    record["applications"] = [
        item
        for item in record.get("applications") or []
        if not any(token in (item.get("visible_content") or "").lower() for token in blocked_surfaces)
    ]
    for entity in record.get("entities") or []:
        posture = (entity.get("posture") or "").strip().lower()
        attributes = list(entity.get("attributes") or [])
        posture_attributes = [
            item for item in attributes if str(item).strip().lower() in {"sitting", "standing", "lying"}
        ]
        if not posture and len(posture_attributes) == 1:
            entity["posture"] = str(posture_attributes[0]).strip().lower()
            entity["attributes"] = [item for item in attributes if item not in posture_attributes]
    return record


def analyze_image_multiscale(
    *, image_id, path, api_key, model, endpoint, max_edge, image_detail,
    temperature, timeout_seconds, retries
):
    views = _multiscale_views(path, max_edge=max_edge)
    content = [{
        "type": "text",
        "text": (
            f"Record one unified fact record for image_id {image_id}. The first image is the full "
            "overview and the following images are overlapping detail regions of that same image, "
            "not separate images. Merge observations by subject and do not duplicate an individual "
            "merely because it appears in overview and detail. Do not infer a user query."
        ),
    }]
    for label, encoded in views:
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": encoded["data_url"], "detail": image_detail}})
    payload = poc.chat_payload(
        model=model,
        system=FACT_PROMPT,
        user=content,
        schema_name="image_facts",
        schema=poc.fact_schema([image_id]),
        temperature=temperature,
    )
    started = time.perf_counter()
    response = poc.post_chat(payload, api_key=api_key, endpoint=endpoint, timeout_seconds=timeout_seconds, retries=retries)
    elapsed = time.perf_counter() - started
    parsed = poc.parse_message(response)
    results = parsed.get("results") or []
    if len(results) != 1 or int(results[0].get("image_id")) != image_id:
        raise RuntimeError(f"unexpected fact payload for {path.name}")
    usage = poc.usage_from_response(response)
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    usage["sent_image_count"] = len(views)
    record = _normalize_record(dict(results[0]))
    raw = path.read_bytes()
    record["filename"] = path.name
    record["encode"] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": views[0][1]["width"],
        "height": views[0][1]["height"],
        "bytes": views[0][1]["bytes"],
        "max_edge": max_edge,
        "image_detail": image_detail,
        "multiscale_views": len(views),
    }
    return record, usage, elapsed
