"""Keep small named UI surfaces in first-Vision facts. Schema and search stay frozen."""

from __future__ import annotations

from tools.meaning_eval import db_sot_facts_v6 as facts_v6
from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_surface_v8 as v8
from tools.meaning_eval.db_sot_surface_v8_identity import configure as configure_identity


PROMPT_VERSION = "db-sot-facts-v8-small-named-surface"
SCHEMA_VERSION = v8.SCHEMA_VERSION

SMALL_NAMED_SURFACE_PROMPT = r"""

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

FACT_PROMPT = v8.FACT_PROMPT + SMALL_NAMED_SURFACE_PROMPT


def configure() -> None:
    configure_identity()
    facts_v6.FACT_PROMPT = FACT_PROMPT
    poc.FACT_PROMPT = FACT_PROMPT
    poc.PROMPT_VERSION = PROMPT_VERSION
    poc.SCHEMA_VERSION = SCHEMA_VERSION
    v8.FACT_PROMPT = FACT_PROMPT
    v8.PROMPT_VERSION = PROMPT_VERSION
