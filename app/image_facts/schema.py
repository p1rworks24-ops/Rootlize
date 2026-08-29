"""Query-independent image facts and DB-only search schemas.

Product persistence and Meaning Search share this module. Facts generation
is `db-sot-facts-v8-small-named-surface`. Search meaning is identity-bound
surfaces with a wide bare-entity contract: only conditions the query named
are required.
"""

from __future__ import annotations

from collections.abc import Sequence

FACTS_PROMPT_VERSION = "db-sot-facts-v8-small-named-surface"
FACTS_SCHEMA_VERSION = "image-facts-v3"
FACTS_VERSION = FACTS_PROMPT_VERSION
SEARCH_PROMPT_VERSION = "db-sot-search-v1.7-query-target"
SEARCH_SCHEMA_VERSION = "db-sot-relevance-v3"
DEFAULT_MAX_EDGE = 1536
DEFAULT_IMAGE_DETAIL = "high"
DEFAULT_DETAIL_CROP_MAX = 4
FACTS_SHORTLIST_SIZE = 40
FACTS_SEARCH_BATCH_SIZE = 5
FACTS_FIRST_CHUNK_SIZE = 8

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
Return exactly one result for every image_id.

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

Host application vs inner content (query-independent):
- Name a host application only when that application's own chrome or
  distinctive product UI is visible: window frame/title bar, tab strip,
  address bar, branded window controls, or a layout that is recognizably
  that product rather than generic content.
- Inner content is not host evidence. A web page, form, document, video, or
  settings sheet can live in many hosts. If the host is not visible, record
  the content/site and leave the host unnamed. Do not default a web page to
  a particular browser.
- `ui_types` may include "browser window" only when browser chrome is
  visible. A cropped webpage is web content, not a named browser.

Controls vs open panels:
- A button, tab, or menu labeled X is a control. Record it as an object
  entity with an attribute such as `button` or `ui control`, and/or as
  notable_text. Do not record a control as an open panel, open application,
  or ui_type of that panel.
- Record a panel/pane/sidebar only when that workspace is actually visible
  as an open region.

File and folder names:
- An identifiable file/folder label is notable_text, or an object entity
  with an attribute such as `folder name` / `file name`. It is not the
  named application.

Keep using existing fields. Nested visual subjects (animals, people,
characters, and nested screenshots of UI) remain ordinary entities.
When the entity budget is tight, keep independently identifiable depicted
subjects before a long tail of similar shortcuts; leftover shortcut names
may stay in notable_text.

Small named UI surfaces (query-independent):
- Also keep visually clear, searchable named surfaces even when they are
  small or peripheral: identifiable application icons on a taskbar or dock;
  labeled navigation / sidebar items; labeled Quick Actions or similar
  named buttons; and visible file/folder tree labels that a later search
  could use.
- Record them as object entities with a surface attribute such as
  `taskbar icon`, `app icon`, `nav item`, `button`, `quick action`, or
  `folder name`. Distinctive names may also go in notable_text, but an
  entity row with that surface attribute is required. notable_text alone
  is not enough for a later search to treat them as that surface.
- If a taskbar or dock is visible, do not stop at a generic taskbar row.
  Add separate entities for identifiable named application icons, each with
  `taskbar icon` or `app icon`. If that same app is also an open window,
  store two entities: the window, and a distinct icon entity that must not
  use window, toolbar, or tab-strip attributes. Skip unlabeled OS chrome
  such as Start, Search, Task View, and system-tray status icons. Keep a
  few such icons even when a folder tree is also using entity slots.
- In a visible folder/file tree, keep distinctive folder labels as
  `folder name` entities, not only the selected row.
- Keep a labeled nav item or control-group name as that named control even
  when inner action buttons are also visible. A page title does not replace
  a labeled button or nav item of the same name.
- Do not dump every OCR string, every unlabeled icon, or an unbounded
  folder/file list. Prefer a few independently identifiable named surfaces
  over many similar chips, generic headings, or dropdown values.
- When the entity or notable_text budget is tight, keep those named surfaces
  before repeated similar tag chips, generic chrome labels, and unlabeled
  OS chrome. Named taskbar/nav/button/folder-label surfaces are not the
  long tail.

Final audit:
5. Did identifiable named taskbar, nav, Quick Action, or folder-label
   surfaces get omitted because they were small or off-center? If a
   taskbar/dock is visible, were identifiable named app icons recorded as
   separate `taskbar icon` entities?
"""

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
- "google chrome images" -> [Google Chrome]
- "search for google chrome images from this folder" -> [Google Chrome]
- "images of a dog" / "dog images" -> [dog]
Library-search wrappers are not conditions: images, screenshots, photos,
pictures, search for, find, show me, from this folder. They describe the
request to search this library, not an extra visual requirement such as
an Images page, a gallery, or a folder-named surface.
Do not split a single concept into words. Do not drop a named target.
Do not add sitting, standing, typical screen type, primary-subject,
gallery, Images page, or "image-related" requirements the query did not
name. Other visible apps, webpages, dialogs, or desktop chrome are not
negatives when the named identity is present.
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

Return exactly one result for every image_id.

Meaning contract for simple queries:
- Visual objects (dog, cat, anime character, person, logo, depicted photo):
  presence anywhere counts, including nested thumbnails/previews. Nested
  placement is not a negative.
- Bare named-entity queries (Google Chrome, a dog, screenshot manager) ask
  only whether that identity is sufficiently present. Confirm from a rendered
  interface, a nested screenshot of that identity, a clear icon, or a clear
  shortcut. Do not add a presence form the query did not name. Do not reject
  an icon, shortcut, or nested screenshot of that identity merely because it
  is not an open window. Inner webpage content, another app, or a dialog
  coexisting with that identity is not a negative. Weak evidence is not
  enough: a mere text string, tag chip, folder name, search-result label,
  or a false-friend phrase such as "window chrome".
- If the query itself names a surface or state (icon, shortcut, button,
  folder, text mention, open, panel, location), evaluate only those stated
  conditions, bound to the same identity. An open application does not
  satisfy "icon" / "button" / "folder name" / "text mention" unless that
  surface is also recorded. A labeled control does not satisfy "panel" /
  "open" unless the panel/workspace is recorded as visible.
- "X open" requires that identity to be open or rendered, not merely named.
- Bare browser/product identity is not the same as "a web page is visible".
  If stored facts do not identify the host application, do not confirm a
  specific browser from page content alone.

Color adjectives:
- Confirm a color on a target when that color is the dominant recorded
  color of the same entity: it is the first canonical color, the only
  canonical color, or the observed description says "mostly <color>".
- Extra markings do not falsify a dominant color. "mostly white" confirms
  white. Adjacent hues still do not match (tan is not orange-brown).

Condition completeness:
- Every image must list the same independent conditions taken from the
  query. If a condition is unsupported, still list it with confirmed=false.
  Omitting an unconfirmed condition is an error.
- The confirmed boolean must agree with the reason. If the reason says a
  condition is not confirmed or not supported, that row must be false.

Identity-bound surfaces (do not use bag-of-words):
- A named surface is one condition. Do not split it into independent words.
  "Chrome icon" -> [Chrome icon]. "Tags button" -> [Tags button].
  "Chrome text mention" -> [Chrome text mention].
  "Microsoft VS Code folder" -> [Microsoft VS Code folder].
  "Tags panel open" -> [Tags panel open]. "Ask AI open" -> [Ask AI open].
  "Preview panel" -> [Preview panel].
- "X icon" is an icon whose identity is X. An open X window plus some other
  icon is not an X icon.
- "X button" is a control whose identity is X, not an X workspace.
- "X text mention" is X as actual visible text (notable_text, a tag chip, a
  text label). An open X application plus unrelated text is not a text mention.
- "X folder" is a folder whose identity is X, not an open X application.

Workspace / open-panel:
- "X panel", "X open", "Preview panel", "Ask AI open" mean a workspace whose
  identity is X is actually displayed. page, workspace, pane, panel, and
  screen are the same workspace family for that purpose.
- An X button, quick action, nav item, text mention, statistics widget, or
  an X input on a different page is not an X workspace.
- Do not confirm from co-occurrence of X with an unrelated panel/open/page.

If a stored visible_content or relationship already names a displayed
entity, use that fact. Do not ignore it.
"""

FACTS_USER_PREFIX = (
    "Record one unified fact record. The first image is the full overview "
    "and the following images are overlapping detail regions of that same "
    "image, not separate images. Merge observations by subject and do not "
    "duplicate an individual merely because it appears in overview and "
    "detail. Do not infer a user query."
)

SEARCH_USER_PREFIX = (
    "Stored facts (source of truth). Judge only from these facts. "
    "List every independent condition the query states. Do not add extra "
    "conditions. Named surfaces are one condition. Library-search wrappers "
    "such as images/screenshots/from this folder are not conditions. "
    "Bare named-entity queries need sufficient identity presence (rendered UI, "
    "clear icon, clear shortcut, or nested screenshot), not a weak text or "
    "folder-name mention. Do not require a presence form the query did not "
    "name. Workspace queries need that identity's page/pane/panel. Do not "
    "output a final relevant flag."
)

FACT_FIELDS = (
    "media_type",
    "scene_description",
    "environment",
    "ui_types",
    "entities",
    "applications",
    "activities",
    "relationships",
    "notable_text",
)


def fact_schema(image_ids: Sequence[int]) -> dict:
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
            "image_id": {"type": "integer", "enum": list(image_ids)},
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


def search_schema(image_ids: Sequence[int]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_id": {"type": "integer", "enum": list(image_ids)},
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


def unknown_facts_record(image_id: int, reason: str) -> dict:
    return {
        "image_id": int(image_id),
        "unknown_reason": reason,
        "media_type": "other",
        "scene_description": "",
        "environment": "",
        "ui_types": [],
        "entities": [],
        "applications": [],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }
