"""Automation Puzzle Builder: Start, Target, Action, drag, zoom, safety."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QToolButton,
    QWidget,
)

from app.automation import (
    AutomationService,
    Workflow,
    WorkflowStore,
    draft_workflow_from_text,
    validate_workflow,
    workflow_from_session,
    workflow_step_summary,
    workflow_to_payload,
)
from app.automation.blocks import (
    CATALOG_CATEGORY_ORDER,
    CATEGORY_ACTION,
    CATEGORY_CONDITION,
    CATEGORY_SELECT,
    CATEGORY_TARGET,
    CATEGORY_TRIGGER,
    KIND_FIND,
    KIND_SELECT,
    KIND_UNSUPPORTED,
    START_BLOCK_ID,
    TARGET_ALL,
    TARGET_MEANING,
    TARGET_TEXT,
    add_block_catalog,
    block_category,
    block_kind,
    block_title,
    catalog_item_is_builder_ready,
    category_style,
    make_act_step,
    make_find_step,
    make_select_step,
    visual_blocks_for,
)
from app.i18n import t
from app.ui.automation_run_dialog import AutomationRunDialog
from app.ui.design_tokens import COLORS, RADIUS_CARD, WORKFLOW_BOARD_BG
from app.ui.main_window import PAGE_AUTOMATION, MainWindow
from app.ui.workflow_canvas import (
    BLOCK_GAP,
    BLOCK_HEIGHT,
    BLOCK_ICON_SIZE,
    BLOCK_TITLE_PX,
    BLOCK_WIDTH,
    CONNECTOR_R,
    GROUP_PAD_X,
    GROUP_PAD_Y,
    MAX_ZOOM,
    MIN_ZOOM,
    WorkflowCanvas,
    WorkflowGroupItem,
    puzzle_path,
)
from app.ui.workflow_editor import AddBlockMenuItem, InspectorTabs, WorkflowEditor
from app.workspace import ORIGIN_BROWSE, ORIGIN_MEANING, ORIGIN_TEXT, SearchResultContext
from app.workspace.plan import STEP_ACTION, STEP_FIND, STEP_NARROW, PlanStep


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_window() -> MainWindow:
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    return MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1100,
            "window_height": 740,
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
            "developer_ask_ai_preview": True,
        }
    )


def _editor(tmp_path: Path) -> WorkflowEditor:
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    editor = WorkflowEditor(service)
    editor.load(None, scope_folder=str(tmp_path))
    return editor


def _assert_add_block_labels_fit(popup) -> None:
    for button in popup.findChildren(QPushButton, "workflowAddBlockItem"):
        name = button.findChild(QLabel, "workflowAddBlockName")
        assert name is not None
        assert name.wordWrap() is True
        assert "\u2026" not in name.text()
        visible = name.text().replace("\n", " ").strip()
        assert visible
        avail = name.width()
        if avail < 8:
            avail = max(48, button.width() - AddBlockMenuItem._TEXT_CHROME)
        metrics = name.fontMetrics()
        bounds = metrics.boundingRect(
            QRect(0, 0, avail, 4000),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            name.text(),
        )
        assert bounds.width() <= avail + 2, visible
        assert bounds.height() <= max(name.height(), button.height()) + 2, visible


def test_new_workflow_default_start_and_all_images(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    blocks = editor.visual_blocks()
    assert len(blocks) == 1
    assert blocks[0].block_id == START_BLOCK_ID
    assert blocks[0].locked is True
    assert blocks[0].category == CATEGORY_SELECT
    assert all(block.category != CATEGORY_TARGET for block in blocks)
    assert all(block.category != CATEGORY_ACTION for block in blocks)
    assert editor.current_steps() == ()
    assert editor._canvas.block_count() == 1
    assert editor._add_block.text() == t("automation.add_block")
    assert editor._add_block.icon() is not None and not editor._add_block.icon().isNull()
    assert editor._add_block.toolTip() == t("automation.add_block")
    toolbar = editor.findChild(QFrame, "workflowCanvasToolbar")
    assert toolbar is not None
    assert toolbar.parent() is editor._workspace
    assert editor._workspace.toolbar is toolbar
    assert editor._canvas._group.boundingRect().isValid()
    before = len(editor.visual_blocks())
    editor.remove_block(0)
    assert len(editor.visual_blocks()) == before
    assert editor.visual_blocks()[0].block_id == START_BLOCK_ID
    assert editor._selected == 0
    assert editor._folder_pick.isVisible()
    assert editor._kind_label.text() == t("automation.category_select")
    assert editor._block_title.text() == t("automation.trigger_folder")
    editor.close()


def test_folder_and_target_modes_toggle_query(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor._scope_folder = str(tmp_path / "FolderA")
    editor._set_target(TARGET_ALL)
    editor._canvas.select_index(1)
    app.processEvents()
    assert editor._target_mode == TARGET_ALL
    assert editor._param.isVisible() is False
    assert editor._ai_hint.isVisible() is False
    editor._set_target(TARGET_TEXT, "report")
    editor._canvas.select_index(1)
    app.processEvents()
    assert editor._param.isVisible() is True
    assert editor._param.text() == "report"
    assert editor._ai_hint.isVisible() is False
    assert [step.type for step in editor.current_steps()] == [STEP_FIND]
    assert editor._origin == ORIGIN_TEXT
    editor._set_target(TARGET_MEANING, "dog")
    editor._canvas.select_index(1)
    app.processEvents()
    assert editor._param.isVisible() is True
    assert editor._ai_hint.isVisible() is True
    assert editor.visual_blocks()[1].uses_ai is True
    assert editor._origin == ORIGIN_MEANING
    summary = workflow_step_summary(editor.current_steps(), folder=editor._scope_folder, origin=editor._origin)
    assert "Folder" in summary
    assert "Meaning" in summary
    assert "Find → Select → Act" not in summary
    assert "Narrow" not in block_title(editor.current_steps()[0], origin=ORIGIN_MEANING)
    editor.close()


def test_category_colors_and_add_block_catalog(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    assert category_style(CATEGORY_SELECT).ink == COLORS.select
    assert category_style(CATEGORY_TARGET).ink == COLORS.target
    assert category_style(CATEGORY_ACTION).ink == COLORS.success
    assert category_style(CATEGORY_TRIGGER).ink == COLORS.trigger
    blocks = editor.visual_blocks()
    assert block_category(make_find_step("dog")) == CATEGORY_TARGET
    assert block_category(make_act_step("add_tag", {"tag": "dog"})) == CATEGORY_ACTION
    assert blocks[0].category == CATEGORY_SELECT
    editor._apply_catalog(type("item", (), {"category": CATEGORY_ACTION, "item_id": "add_tag", "enabled": True, "coming_soon": False})())
    types = [step.type for step in editor.current_steps()]
    assert STEP_ACTION in types
    editor._apply_catalog(type("item", (), {"category": CATEGORY_TARGET, "item_id": TARGET_TEXT, "enabled": True, "coming_soon": False})())
    assert editor._target_mode == TARGET_TEXT
    editor._apply_catalog(type("item", (), {"category": CATEGORY_SELECT, "item_id": "folder", "enabled": True, "coming_soon": False})())
    assert editor.visual_blocks()[0].visual_kind == "folder"
    assert editor._selected == 0
    assert editor._folder_pick.isVisible()
    assert editor._add_block.objectName() == "automationAddBlockButton"
    editor.close()


def test_block_catalog_keeps_internal_find_narrow():
    find = make_find_step("dog")
    select = make_select_step("night")
    move = make_act_step("move", {"destination_name": "Dogs"})
    bad = PlanStep(step_id="x", type="shell", parameters={"sql": "1"})
    assert block_kind(find) == KIND_FIND
    assert block_kind(select) == KIND_SELECT
    assert block_kind(bad) == KIND_UNSUPPORTED
    assert select.type == STEP_NARROW
    assert block_title(select) == t("automation.block_narrow")
    summary = workflow_step_summary((find, select, move), folder=r"D:\Images\FolderA", origin=ORIGIN_MEANING)
    assert "Folder" in summary
    assert "Meaning" in summary or "dog" in summary
    assert "Move" in summary
    assert "Find → Select → Act" not in summary


def test_draft_from_natural_language_find_select_move():
    outcome = draft_workflow_from_text(
        "犬の画像を探して Dogs フォルダに移動したい",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is True
    assert [step.type for step in outcome.steps] == [STEP_FIND, STEP_ACTION]
    assert "dog" in outcome.steps[0].query.lower() or "犬" in outcome.steps[0].query
    assert outcome.steps[1].action_id == "move"
    assert outcome.steps[1].parameters.get("destination_name") == "Dogs"


def test_draft_english_and_clarify_without_act():
    planned = draft_workflow_from_text(
        "find dogs and move them to Dogs",
        SearchResultContext(),
        allow_ai=False,
    )
    assert planned.ok is True
    assert planned.steps[0].type == STEP_FIND
    assert planned.steps[-1].action_id == "move"
    partial = draft_workflow_from_text("犬の画像を探して", SearchResultContext(), allow_ai=False)
    assert partial.ok is False
    assert partial.steps[0].type == STEP_FIND
    assert partial.message_key == "automation.draft_need_act"


def test_list_new_edit_rename_delete_and_run(tmp_path):
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    page = window._automation_page
    labels = {button.text() for button in page.findChildren(QPushButton)}
    assert t("automation.new") in labels
    assert t("automation.empty") in page._empty.text()
    assert page._table.isVisible()
    assert page._table.rowCount() == 0
    page._new_workflow()
    app.processEvents()
    assert page._stack.currentWidget() is page._editor
    assert page._editor.isVisible()
    assert not page._list_page.isVisible()
    editor = page._editor
    assert editor.visual_blocks()[0].block_id == START_BLOCK_ID
    assert editor._selected == 0
    assert editor._folder_pick.isVisible()
    assert editor._kind_label.text() == t("automation.category_select")
    assert editor._block_title.text() == t("automation.trigger_folder")
    editor.add_block(make_find_step("dog"))
    editor.add_block(make_act_step("add_tag", {"tag": "work"}))
    editor._name.setText("Tag dogs")
    editor._description.setText("Find then tag")
    assert editor._save_document() is True
    editor.back_requested.emit()
    app.processEvents()
    assert page._stack.currentWidget() is page._list_page
    run_buttons = [
        button
        for button in page.findChildren(QPushButton)
        if button.objectName() == "automationListRunButton"
    ]
    assert run_buttons
    assert run_buttons[0].toolTip() == t("automation.run")
    tips = {button.toolTip() for button in page.findChildren(QToolButton)}
    assert t("automation.edit") in tips
    assert t("automation.rename") in tips
    assert t("automation.delete") in tips
    table = page.findChild(QTableWidget, "automationWorkflowTable")
    assert table is not None
    assert table.isVisible()
    list_card = page.findChild(QFrame, "automationListCard")
    assert list_card is not None
    assert table.parentWidget() is list_card
    corners = list_card.findChildren(QWidget, "automationListCorner")
    assert len(corners) == 4
    assert table.rowCount() == 1
    assert table.columnCount() == 7
    assert table.cellWidget(0, 0) is not None
    assert table.cellWidget(0, 6) is not None
    saved = window._automation_service.list_workflows()[0]
    page._edit_workflow(saved.id)
    app.processEvents()
    assert [step.type for step in page._editor.current_steps()] == [STEP_FIND, STEP_ACTION]
    page._show_list()
    window._automation_service.rename(saved.id, "Dogs work", description="updated")
    page._reload_cards()
    assert window._automation_service.get(saved.id).name == "Dogs work"
    assert window._automation_service.delete(saved.id) is True
    page._reload_cards()
    assert page._empty.isVisible()
    assert page._table.isVisible()
    assert page._table.rowCount() == 0
    window.close()


def test_automation_nav_from_board_returns_to_list():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    page = window._automation_page
    page._new_workflow()
    app.processEvents()
    assert page._stack.currentWidget() is page._editor
    assert not page._list_page.isVisible()
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    assert page._stack.currentWidget() is page._list_page
    page._new_workflow()
    app.processEvents()
    window._side_nav._nav_buttons[PAGE_AUTOMATION].click()
    app.processEvents()
    assert page._stack.currentWidget() is page._list_page
    window.close()


def test_left_to_right_add_remove_and_param_edit(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.add_block(make_find_step("dog"))
    editor.add_block(make_act_step("move", {"destination_name": "Dogs"}))
    xs = [editor._canvas.block_scene_x(i) for i in range(editor._canvas.block_count())]
    assert xs == sorted(xs)
    assert [step.type for step in editor.current_steps()] == [STEP_FIND, STEP_ACTION]
    editor._canvas.select_index(1)
    editor._param.setText("puppy")
    app.processEvents()
    assert editor.current_steps()[0].query == "puppy"
    editor._canvas.select_index(2)
    app.processEvents()
    assert editor._folder_pick.isVisible()
    assert editor._param.isVisible() is False
    assert editor._folder_label.text() == t("automation.param_destination")
    assert editor._folder_pick._browse.text() == ""
    assert not editor._folder_pick._browse.icon().isNull()
    assert editor._folder_pick._browse.toolButtonStyle() == Qt.ToolButtonIconOnly
    assert editor._delete_block.isVisible()
    assert editor._delete_block.text() == ""
    assert editor._delete_block.objectName() == "workflowDeleteBlockButton"
    assert not editor._delete_block.icon().isNull()
    title_left = editor._block_title.mapTo(editor._inspector, editor._block_title.rect().topLeft()).x()
    trash_left = editor._delete_block.mapTo(editor._inspector, editor._delete_block.rect().topLeft()).x()
    assert trash_left > title_left
    editor.remove_block(2)
    assert [step.type for step in editor.current_steps()] == [STEP_FIND]
    editor.add_block(make_act_step("add_tag", {"tag": "work"}))
    assert [step.type for step in editor.current_steps()] == [STEP_FIND, STEP_ACTION]
    editor.close()


def test_move_folder_field_empty_until_chosen(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.add_block(make_act_step("move"))
    editor._canvas.select_index(editor._canvas.block_count() - 1)
    app.processEvents()
    assert editor._folder_pick.isVisible()
    assert editor._folder_pick._value.text() == ""
    assert editor._folder_pick._browse.text() == ""
    assert not editor._folder_pick._browse.icon().isNull()
    editor.close()


def test_block_drag_updates_connections_and_group_move(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.add_block(make_act_step("add_tag", {"tag": "dog"}))
    app.processEvents()
    canvas = editor._canvas
    assert canvas.block_count() >= 3
    first = canvas._blocks[0]
    start = QPointF(first.pos())
    first.setPos(start.x() + 48, start.y() + 36)
    app.processEvents()
    assert first.pos() != start
    assert canvas._connectors
    path = canvas._connectors[0].path()
    assert path.elementCount() >= 2
    assert canvas.connector_is_straight(0)
    before = [QPointF(item.pos()) for item in canvas._blocks]
    canvas._begin_group_drag(QPointF(10, 10))
    canvas._continue_group_drag(QPointF(50, 30))
    canvas._end_group_drag()
    after = [item.pos() for item in canvas._blocks]
    assert any(a != b for a, b in zip(after, before))
    editor.close()


def test_zoom_pan_fit_reset_and_resize(tmp_path):
    app = _ensure_app()
    canvas = WorkflowCanvas()
    canvas.resize(640, 360)
    canvas.show()
    app.processEvents()
    canvas.set_blocks(
        visual_blocks_for(
            folder=str(tmp_path),
            origin=ORIGIN_MEANING,
            steps=(
                make_find_step("dog"),
                make_act_step("move", {"destination_name": "Dogs"}),
            ),
        )
    )
    canvas.set_zoom(0.05)
    assert canvas.zoom == MIN_ZOOM
    canvas.set_zoom(9)
    assert canvas.zoom == MAX_ZOOM
    canvas.reset_zoom()
    assert canvas.zoom == canvas.DEFAULT_ZOOM
    canvas.set_zoom(1.6)
    canvas.fit_to_workflow()
    assert MIN_ZOOM <= canvas.zoom <= MAX_ZOOM
    canvas.horizontalScrollBar().setValue(0)
    canvas._panning = True
    canvas._pan_start = QPointF(80, 40)
    canvas.horizontalScrollBar().setMaximum(400)
    canvas.horizontalScrollBar().setValue(120)
    before = canvas.horizontalScrollBar().value()
    canvas.horizontalScrollBar().setValue(int(before - 40))
    assert canvas.horizontalScrollBar().value() != before
    canvas.resize(420, 280)
    app.processEvents()
    assert canvas.block_count() == 3
    before_zoom = canvas.zoom
    canvas.zoom_in()
    assert canvas.zoom >= before_zoom
    assert MIN_ZOOM <= canvas.zoom <= MAX_ZOOM
    canvas.close()


def test_workflow_editor_resize_fills_board_not_black(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(900, 560)
    editor.show()
    app.processEvents()
    editor.resize(1280, 860)
    app.processEvents()
    assert editor._workspace._inner.mask().isEmpty()
    rail = editor.findChild(QFrame, "workflowSideRail")
    assert rail is not None
    assert rail.inner.mask().isEmpty()
    image = editor.grab().toImage()
    assert not image.isNull()
    samples = (
        (8, 8),
        (8, image.height() - 8),
        (image.width() - 8, 8),
        (image.width() - 8, image.height() - 8),
        (8, image.height() // 2),
        (image.width() - 8, image.height() // 2),
    )
    for x, y in samples:
        color = image.pixelColor(x, y)
        assert color.alpha() == 255, (x, y, color.name())
        assert color.lightness() > 80, (x, y, color.name())
    editor.close()


def test_workflow_editor_uses_images_card_surfaces(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1280, 860)
    editor.show()
    app.processEvents()
    board = QColor(WORKFLOW_BOARD_BG)
    card = QColor(COLORS.card_bg)
    page = QColor(COLORS.app_bg)
    assert board != card
    assert board.lightness() < card.lightness()
    assert board != page
    workspace = editor._workspace
    rail = editor.findChild(QFrame, "workflowSideRail")
    assert rail is not None
    assert workspace.mask().isEmpty()
    assert rail.mask().isEmpty()
    assert workspace._inner.mask().isEmpty()
    assert rail.inner.mask().isEmpty()
    assert workspace.findChild(QWidget, "workflowCardClip") is not None
    assert rail.findChild(QWidget, "workflowCardClip") is not None
    callout = editor.findChild(QFrame, "workflowInspectorCallout")
    assert callout is not None
    board_image = workspace.grab().toImage()
    rail_image = rail.grab().toImage()
    board_sample = board_image.pixelColor(28, 28)
    rail_sample = rail_image.pixelColor(rail.width() // 2, 48)
    rail_corner = rail_image.pixelColor(1, 1)
    assert abs(board_sample.lightness() - board.lightness()) < 36, board_sample.name()
    assert abs(rail_sample.lightness() - card.lightness()) < 24, rail_sample.name()
    assert board_sample.lightness() < rail_sample.lightness(), (
        board_sample.name(),
        rail_sample.name(),
    )
    assert abs(rail_corner.lightness() - page.lightness()) < 48, rail_corner.name()
    editor.close()


def test_editor_information_architecture(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1100, 720)
    editor.show()
    app.processEvents()
    assert editor.findChild(QFrame, "workflowEditorHeader") is not None
    assert editor._back.objectName() == "workflowBackButton"
    assert editor._back.text() == t("automation.back")
    assert editor._back.icon() is not None and not editor._back.icon().isNull()
    assert editor.findChild(QFrame, "workflowHeaderDivider") is not None
    assert editor._name.objectName() == "workflowIdentityName"
    assert editor._description.objectName() == "workflowIdentityDescription"
    assert editor._save.objectName() == "workflowSaveButton"
    assert editor._save.icon() is not None and not editor._save.icon().isNull()
    assert editor._run.objectName() == "automationRunButton"
    assert editor._run.text() == t("automation.run")
    assert editor._run.icon() is not None and not editor._run.icon().isNull()
    assert editor._unsaved.isVisible() is True
    assert editor._run_status.property("status") == "blocked"
    identity = editor.findChild(QFrame, "workflowIdentity")
    assert identity is not None
    assert editor._save.parent() is not identity
    assert editor._run.parent() is not identity
    status_right = editor._run_status.mapTo(editor, editor._run_status.rect().topRight()).x()
    save_left = editor._save.mapTo(editor, QPoint(0, 0)).x()
    run_right = editor._run.mapTo(editor, editor._run.rect().topRight()).x()
    assert 0 <= save_left - status_right <= 48
    assert editor.width() - run_right > 160
    assert editor._name.minimumHeight() >= 32
    assert editor._description.minimumHeight() >= 24
    toolbar = editor.findChild(QFrame, "workflowCanvasToolbar")
    assert toolbar.parent() is editor._workspace
    assert editor.layout().indexOf(toolbar) == -1
    assert editor._add_block.text() == t("automation.add_block")
    assert editor._add_block.icon() is not None and not editor._add_block.icon().isNull()
    assert editor.findChild(QFrame, "workflowZoomCluster") is not None
    tabs = editor.findChild(InspectorTabs, "workflowInspectorTabs")
    assert tabs is not None
    assert tabs.count() == 2
    assert t("automation.inspector_settings") in tabs.tabText(0)
    assert t("automation.inspector_ai") in tabs.tabText(1)
    start = editor._canvas._blocks[0]
    assert start.can_delete() is False
    assert start.trash_visible() is False
    editor._canvas.select_index(0)
    app.processEvents()
    assert editor._inspector_tabs.currentIndex() == 0
    editor.add_block(make_act_step("add_tag", {"tag": "dog"}))
    app.processEvents()
    assert editor._inspector_tabs.currentIndex() == 0
    action = editor._canvas._blocks[-1]
    action._hover = True
    assert action.can_delete() is True
    assert action.trash_visible() is True
    editor._inspector_tabs.setCurrentIndex(1)
    app.processEvents()
    assert editor._inspector_tabs.currentIndex() == 1
    editor._inspector_tabs.setCurrentIndex(0)
    editor.remove_block(action.index)
    app.processEvents()
    assert STEP_ACTION not in [step.type for step in editor.current_steps()]
    assert editor._unsaved.isVisible() is True
    editor._name.setText("Ready later")
    editor.add_block(make_act_step("add_tag", {"tag": "keep"}))
    assert editor._save_document() is True
    app.processEvents()
    assert editor._unsaved.isVisible() is False
    editor.close()


def test_add_block_menu_categories_and_coming_later(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1280, 800)
    editor.show()
    app.processEvents()
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    assert popup.isVisible()
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    by_id = {item.property("itemId"): item for item in items}
    enabled_ids = {"folder", "all", "text", "meaning", "move", "add_tag", "remove_tag"}
    assert enabled_ids <= set(by_id)
    for item_id in enabled_ids:
        assert by_id[item_id].isEnabled() is True
        assert bool(by_id[item_id].property("catalogEnabled")) is True
        assert by_id[item_id].cursor().shape() == Qt.PointingHandCursor
    for item_id in ("add_tag", "remove_tag", "move"):
        assert by_id[item_id].isEnabled() is True
        assert bool(by_id[item_id].property("catalogEnabled")) is True
    assert by_id["manual_run"].isEnabled() is False
    assert by_id["rename"].isEnabled() is False
    assert by_id["delete"].isEnabled() is False
    assert by_id["favorites_add"].isEnabled() is False
    assert "copy" not in by_id
    assert "create_folder" not in by_id
    assert "event" not in by_id
    assert "time" not in by_id
    soon_labels = [label.text() for label in popup.findChildren(QLabel) if label.objectName() == "workflowAddBlockSoon"]
    assert soon_labels == []
    texts = " ".join(label.text() for label in popup.findChildren(QLabel))
    assert "Coming soon" not in texts
    assert "Coming later" not in texts
    assert t("automation.coming_later") not in texts
    files_added = by_id["files_added"].findChild(QLabel, "workflowAddBlockName")
    assert files_added is not None
    assert files_added.wordWrap() is True
    assert "When files" in files_added.text()
    assert "added" in files_added.text()
    assert by_id["files_added"].minimumHeight() >= AddBlockMenuItem._ICON + AddBlockMenuItem._H_MARGIN
    _assert_add_block_labels_fit(popup)
    headings = [label.text() for label in popup.findChildren(QLabel) if label.objectName() == "workflowAddBlockCategory"]
    assert headings == [
        t("automation.category_trigger"),
        t("automation.category_select"),
        t("automation.category_search"),
        t("automation.category_condition"),
        t("automation.category_action"),
    ]
    assert t("automation.category_future") not in headings
    glyphs = popup.findChildren(QLabel, "workflowAddBlockGlyph")
    assert len(glyphs) == len(items)
    assert all(label.pixmap() is not None and not label.pixmap().isNull() for label in glyphs)
    menu_icon = glyphs[0].width()
    assert menu_icon == 24
    assert all(label.width() == menu_icon and label.height() == menu_icon for label in glyphs)
    assert menu_icon < BLOCK_ICON_SIZE
    before = len(editor.visual_blocks())
    by_id["add_tag"].click()
    app.processEvents()
    assert popup.isVisible() is False
    assert len(editor.visual_blocks()) == before + 2
    assert editor.visual_blocks()[-1].title == t("automation.action_add_tag")
    assert editor._selected == len(editor.visual_blocks()) - 1
    assert editor._inspector_tabs.currentIndex() == 0
    assert editor._inspector.isVisible()
    editor.close()


def test_add_block_menu_tour_highlights_text_search(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.set_tour_catalog_allow(("text",))
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    visible = [item for item in items if item.isVisible()]
    by_id = {item.property("itemId"): item for item in visible}
    assert set(by_id) >= {"folder", "all", "text", "meaning", "move", "add_tag", "remove_tag"}
    assert "text" in by_id
    assert "add_tag" in by_id
    assert {item.property("itemId") for item in visible} != {"text"}
    assert bool(by_id["text"].property("tourTarget"))
    assert not bool(by_id["add_tag"].property("tourTarget"))
    by_id["add_tag"].click()
    app.processEvents()
    assert popup.isVisible() is True
    assert all(block.category != CATEGORY_ACTION for block in editor.visual_blocks())
    editor._apply_catalog(
        type("item", (), {"category": CATEGORY_ACTION, "item_id": "add_tag", "enabled": True, "coming_soon": False})()
    )
    assert all(block.category != CATEGORY_ACTION for block in editor.visual_blocks())
    by_id["text"].click()
    app.processEvents()
    assert editor._target_mode == TARGET_TEXT
    editor.close()


def test_add_block_menu_tour_highlights_text_search(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.set_tour_catalog_allow(("text",))
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    visible = [item for item in items if item.isVisible()]
    by_id = {item.property("itemId"): item for item in visible}
    assert set(by_id) >= {"folder", "all", "text", "meaning", "move", "add_tag", "remove_tag"}
    assert "text" in by_id
    assert "add_tag" in by_id
    assert {item.property("itemId") for item in visible} != {"text"}
    assert bool(by_id["text"].property("tourTarget"))
    assert not bool(by_id["add_tag"].property("tourTarget"))
    by_id["add_tag"].click()
    app.processEvents()
    assert popup.isVisible() is True
    assert all(block.category != CATEGORY_ACTION for block in editor.visual_blocks())
    editor._apply_catalog(
        type("item", (), {"category": CATEGORY_ACTION, "item_id": "add_tag", "enabled": True, "coming_soon": False})()
    )
    assert all(block.category != CATEGORY_ACTION for block in editor.visual_blocks())
    by_id["text"].click()
    app.processEvents()
    assert editor._target_mode == TARGET_TEXT
    editor.close()


def test_toolbar_popup_sort_and_straight_connectors(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    toolbar = editor.findChild(QFrame, "workflowCanvasToolbar")
    assert toolbar is not None
    assert editor._add_block.objectName() == "automationAddBlockButton"
    assert t("automation.sort") in editor._sort.text()
    canvas = editor._canvas
    editor._set_target(TARGET_ALL)
    app.processEvents()
    first = canvas._blocks[0]
    first.setPos(first.pos().x() + 80, first.pos().y() + 64)
    app.processEvents()
    assert canvas.connector_is_straight(0)
    editor._sort_blocks()
    app.processEvents()
    xs = [canvas.block_position(i).x() for i in range(canvas.block_count())]
    ys = [round(canvas.block_position(i).y(), 1) for i in range(canvas.block_count())]
    assert xs == sorted(xs)
    assert len(set(ys)) == 1
    assert canvas.connector_is_straight(0)
    before = len(editor.visual_blocks())
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    assert popup.isVisible()
    assert popup.objectName() == "workflowAddBlockPopup"
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    add_tag = next(item for item in items if item.property("itemId") == "add_tag")
    add_tag.click()
    app.processEvents()
    assert popup.isVisible() is False
    assert len(editor.visual_blocks()) == before + 1
    editor.close()


def test_malformed_and_unsupported_blocks_stay_visible(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.replace_steps(
        (
            make_find_step("dog"),
            PlanStep(step_id="bad", type="python", parameters={"code": "print(1)"}),
            make_act_step("add_tag", {"tag": "work"}),
        )
    )
    kinds = [block_kind(step) for step in editor.current_steps()]
    assert KIND_UNSUPPORTED in kinds
    assert editor._canvas.block_count() >= 3
    assert editor._canvas.block_scene_x(0) < editor._canvas.block_scene_x(2)
    draft = editor.build_workflow()
    try:
        editor._service.save_draft(draft)
        assert False, "unsafe draft should not save"
    except Exception as exc:
        assert "unknown" in str(exc).lower() or getattr(exc, "validation", None) is not None
    unsupported = next(index for index, step in enumerate(editor.current_steps()) if block_kind(step) == KIND_UNSUPPORTED)
    visual_index = next(index for index, block in enumerate(editor.visual_blocks()) if block.visual_kind == "unsupported")
    editor.remove_block(visual_index)
    assert KIND_UNSUPPORTED not in [block_kind(step) for step in editor.current_steps()]
    assert editor._save_document() is True
    del unsupported
    editor.close()


def test_automation_ai_reflects_on_canvas_not_ask_ai(tmp_path):
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()
    window._show_page(PAGE_AUTOMATION)
    page = window._automation_page
    page._new_workflow()
    app.processEvents()
    editor = page._editor
    editor._draft_input.setText("find dogs and add tag work")
    editor._apply_draft()
    types = [step.type for step in editor.current_steps()]
    assert STEP_FIND in types
    assert STEP_ACTION in types
    assert editor.visual_blocks()[0].block_id == START_BLOCK_ID
    assert editor._target_mode == TARGET_MEANING
    assert editor._draft_status.text()
    assert editor.findChild(QPlainTextEdit, "automationDraftInput") is not None
    assert editor.findChild(QWidget, "askAiChat") is None
    assert "Ask AI" not in editor._draft_status.text()
    search = next(block for block in editor.visual_blocks() if block.category == CATEGORY_TARGET)
    assert search.title == t("automation.block_meaning_search")
    action = next(block for block in editor.visual_blocks() if block.category == CATEGORY_ACTION)
    editor._canvas.select_index(editor.visual_blocks().index(action))
    app.processEvents()
    editor._param.setText("DOG")
    app.processEvents()
    tagged = next(step for step in editor.current_steps() if step.type == STEP_ACTION)
    assert tagged.parameters.get("tag") == "DOG"
    window.close()


def test_automation_draft_input_grows_to_show_full_text(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1100, 720)
    editor.show()
    app.processEvents()
    editor._show_ai_tab()
    app.processEvents()
    field = editor._draft_input
    field.setText("find dogs")
    app.processEvents()
    short_h = field.height()
    long_text = (
        "このフォルダの犬の画像をすべて探してDOGタグを付け、"
        "Animalフォルダへ移動したうえで、お気に入りにも追加したい。"
        "さらに同じ条件で再実行できるようにワークフローとして保存したい。"
        "条件に合う画像がなければスキップし、実行後は件数を残したい。" * 6
    )
    field.setText(long_text)
    app.processEvents()
    long_h = field.height()
    assert field.toPlainText() == long_text
    assert editor.findChild(QPlainTextEdit, "automationDraftInput") is field
    assert long_h > short_h
    assert long_h >= field.fontMetrics().lineSpacing() * 8
    assert long_h > 360
    assert field.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert field.verticalScrollBar().maximum() == 0
    editor.close()


def test_dog_instruction_lands_on_builder_and_stays_editable(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor._show_ai_tab()
    app.processEvents()
    editor._draft_input.setText(
        "Find all dog images in this folder, tag them DOG, and move them to the Animal folder."
    )
    editor._apply_draft()
    app.processEvents()
    steps = editor.current_steps()
    assert [step.type for step in steps] == [STEP_FIND, STEP_ACTION, STEP_ACTION]
    assert editor._target_mode == TARGET_MEANING
    assert steps[1].action_id == "add_tag"
    assert steps[1].parameters.get("tag") == "DOG"
    assert steps[2].action_id == "move"
    assert steps[2].parameters.get("destination_name") == "Animal"
    titles = [block.title for block in editor.visual_blocks()]
    assert t("automation.trigger_folder") in titles
    assert t("automation.block_meaning_search") in titles
    assert t("automation.action_add_tag") in titles
    assert t("automation.action_move") in titles
    editor._canvas.select_index(2)
    app.processEvents()
    editor._param.setText("PET")
    app.processEvents()
    assert editor.current_steps()[1].parameters.get("tag") == "PET"
    editor._draft_complete_json = lambda *_args, **_kwargs: {"status": "explode"}
    before = [(step.type, step.action_id, dict(step.parameters)) for step in editor.current_steps()]
    editor._draft_input.setText("please assemble a reusable canine workflow xyzzy")
    editor._apply_draft()
    editor._draft_pool.waitForDone(3000)
    app.processEvents()
    after = [(step.type, step.action_id, dict(step.parameters)) for step in editor.current_steps()]
    assert after == before
    assert t("automation.draft_invalid") in editor._draft_status.text()
    editor.close()


def test_required_create_folder_only_does_not_change_the_board(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor._show_ai_tab()
    app.processEvents()
    before = [(step.type, step.action_id, dict(step.parameters)) for step in editor.current_steps()]
    titles_before = [block.title for block in editor.visual_blocks()]
    editor._draft_input.setText("Create an Animal folder.")
    editor._apply_draft()
    app.processEvents()
    after = [(step.type, step.action_id, dict(step.parameters)) for step in editor.current_steps()]
    assert after == before
    assert [block.title for block in editor.visual_blocks()] == titles_before
    assert not any(step.action_id == "create_folder" for step in editor.current_steps())
    status = editor._draft_status.text()
    assert t("automation.action_create_folder") in status
    editor.close()


def test_create_folder_and_move_builds_meaning_search_and_move(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor._show_ai_tab()
    app.processEvents()
    editor._draft_input.setText("Create an Animal folder and move all dog images into it.")
    editor._apply_draft()
    app.processEvents()
    steps = editor.current_steps()
    assert [step.type for step in steps] == [STEP_FIND, STEP_ACTION]
    assert editor._target_mode == TARGET_MEANING
    assert "dog" in steps[0].query.lower()
    assert steps[1].action_id == "move"
    assert steps[1].parameters.get("destination_name") == "Animal"
    assert not any(step.action_id == "create_folder" for step in steps)
    titles = [block.title for block in editor.visual_blocks()]
    assert t("automation.block_meaning_search") in titles
    assert t("automation.action_move") in titles
    editor.close()


def test_run_still_uses_v0_confirm_and_does_not_change_before_confirm():
    app = _ensure_app()
    window = _make_window()
    folder = Path(window._config["screenshot_dir"]) / "Default"
    (folder / "dog-a.png").write_bytes(b"png")
    workflow = workflow_from_session(
        name="Tag dogs",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
        action_id="add_tag",
        parameters={"tag": "work"},
    )
    window._automation_service.save(workflow)
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()

    def _cancel_run_dialog() -> None:
        for widget in app.topLevelWidgets():
            if isinstance(widget, AutomationRunDialog) and widget.isVisible():
                widget.reject()
                return

    QTimer.singleShot(0, _cancel_run_dialog)
    window._run_automation_workflow(workflow.id)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_AUTOMATION
    assert window._images_page._ai_panel_expanded is False
    assert (folder / "dog-a.png").exists()
    assert "work" not in window._images_page._metadata_service.get_image_tags(folder, "dog-a.png")
    window.close()


def test_save_draft_allows_incomplete_but_run_still_validates(tmp_path):
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    draft = Workflow(id="draft-1", name="WIP", scope_folder=str(tmp_path), steps=(make_find_step("dog"),))
    saved = service.save_draft(draft)
    assert saved.name == "WIP"
    validation = validate_workflow(saved)
    assert validation.ok is False
    assert "no_action" in validation.reasons


def test_all_images_origin_and_existing_workflow_edit(tmp_path):
    app = _ensure_app()
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    editor = WorkflowEditor(service)
    editor.load(None, scope_folder=str(tmp_path))
    editor._set_target(TARGET_ALL)
    editor.add_block(make_act_step("add_tag", {"tag": "keep"}))
    editor._name.setText("All tag")
    assert editor._origin == ORIGIN_BROWSE
    assert [step.type for step in editor.current_steps()] == [STEP_ACTION]
    assert editor._save_document() is True
    loaded = service.get(editor._workflow_id)
    editor.load(loaded)
    assert editor._target_mode == TARGET_ALL
    assert editor.visual_blocks()[0].locked is True
    editor.close()


def test_puzzle_shape_connectors_and_default_zoom(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1280, 800)
    editor.show()
    app.processEvents()
    editor.add_block(make_act_step("add_tag", {"tag": "dog"}))
    app.processEvents()
    canvas = editor._canvas
    assert canvas.zoom == canvas.DEFAULT_ZOOM
    assert canvas.block_count() == 3
    trigger, target, action = canvas._blocks
    assert trigger.has_left_connector() is False
    assert trigger.has_right_connector() is True
    assert target.has_left_connector() is True
    assert target.has_right_connector() is True
    assert action.has_left_connector() is True
    assert action.has_right_connector() is False
    body = puzzle_path(False, True)
    assert body.contains(QPointF(BLOCK_WIDTH + CONNECTOR_R * 0.65, BLOCK_HEIGHT / 2))
    assert body.contains(QPointF(8, BLOCK_HEIGHT / 2))
    notch = puzzle_path(True, True)
    assert notch.contains(QPointF(BLOCK_WIDTH + CONNECTOR_R * 0.65, BLOCK_HEIGHT / 2))
    assert notch.contains(QPointF(CONNECTOR_R + 16, BLOCK_HEIGHT / 2))
    assert notch.contains(QPointF(2, BLOCK_HEIGHT / 2)) is False
    assert trigger.shape().contains(QPointF(BLOCK_WIDTH + CONNECTOR_R * 0.5, BLOCK_HEIGHT / 2))
    assert target.shape().contains(QPointF(2, BLOCK_HEIGHT / 2)) is False
    assert BLOCK_WIDTH >= 260
    assert 115 <= BLOCK_HEIGHT <= 135
    assert 40 <= BLOCK_GAP <= 70
    assert BLOCK_ICON_SIZE == 32
    assert BLOCK_TITLE_PX == 14
    assert BLOCK_ICON_SIZE / BLOCK_TITLE_PX >= 2.0
    assert canvas.connector_is_straight(0)
    start = trigger.connector_out_scene()
    end = target.connector_in_scene()
    assert start.x() < end.x()
    assert abs((end.x() - start.x()) - BLOCK_GAP) <= CONNECTOR_R + 2
    assert WorkflowGroupItem.shows_label is False
    assert canvas._group.shows_label is False
    for zoom in (0.4, 0.8, 1.0, 1.5, 2.0):
        canvas.set_zoom(zoom)
        app.processEvents()
        assert trigger.puzzle_path().elementCount() >= 8
        assert canvas.connector_is_straight(0)
    canvas.reset_zoom()
    assert canvas.zoom == 1.0
    editor.close()


def test_add_block_popover_future_and_escape(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1280, 800)
    editor.show()
    app.processEvents()
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    assert popup.isVisible()
    headings = [label.text() for label in popup.findChildren(QLabel) if label.objectName() == "workflowAddBlockCategory"]
    assert t("automation.category_future") not in headings
    assert t("automation.category_trigger") in headings
    assert t("automation.category_condition") in headings
    assert popup.width() <= QApplication.primaryScreen().availableGeometry().width()
    escape = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    popup.keyPressEvent(escape)
    app.processEvents()
    assert popup.isVisible() is False
    editor._canvas.select_index(0)
    app.processEvents()
    assert t("automation.help_select_folder") in editor._help_label.text()
    assert editor._kind_label.text() == t("automation.category_select")
    assert editor._block_title.text() == t("automation.trigger_folder")
    assert editor._folder_pick.isVisible()
    editor.close()


def test_add_block_disabled_items_cannot_enter_workflow(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1280, 800)
    editor.show()
    app.processEvents()
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    by_id = {item.property("itemId"): item for item in items}
    before_blocks = editor.visual_blocks()
    before_steps = editor.current_steps()
    disabled = next(item for item in add_block_catalog() if item.item_id == "rename")
    assert catalog_item_is_builder_ready(disabled) is False
    by_id["rename"].click()
    app.processEvents()
    assert editor.visual_blocks() == before_blocks
    assert editor.current_steps() == before_steps
    editor._apply_catalog(disabled)
    app.processEvents()
    assert editor.current_steps() == before_steps
    popup._kb_button = by_id["rename"]
    enter = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    popup.keyPressEvent(enter)
    app.processEvents()
    assert editor.current_steps() == before_steps
    down = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    popup.keyPressEvent(down)
    app.processEvents()
    assert popup._kb_button is not None
    assert popup._kb_button.item.enabled is True
    assert popup._kb_button.property("itemId") != "rename"
    payload = workflow_to_payload(editor.build_workflow())
    serialized = str(payload)
    assert "rename" not in serialized
    assert "manual_run" not in serialized
    assert "tag_exists" not in serialized
    editor.close()


def test_add_block_catalog_keeps_enabled_ids_stable():
    items = add_block_catalog()
    by_category: dict[str, list[str]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item.item_id)
    assert tuple(by_category) == CATALOG_CATEGORY_ORDER
    assert by_category[CATEGORY_TRIGGER] == ["manual_run", "files_added", "daily", "specific_time"]
    assert by_category[CATEGORY_SELECT] == ["folder", "multiple_folders", "favorites", "tagged_images"]
    assert by_category[CATEGORY_TARGET] == ["all", "text", "meaning", "similar", "duplicates"]
    assert by_category[CATEGORY_CONDITION] == ["tag_exists", "filename_contains", "is_favorite", "duplicate_found"]
    assert by_category[CATEGORY_ACTION] == ["move", "add_tag", "remove_tag", "rename", "favorites_add", "delete"]
    enabled = [item.item_id for item in items if item.enabled]
    assert enabled == ["folder", "all", "text", "meaning", "move", "add_tag", "remove_tag"]
    for category in CATALOG_CATEGORY_ORDER:
        flags = [item.enabled for item in items if item.category == category]
        assert flags == sorted(flags, reverse=True)
    assert all(item.icon_key for item in items)
    assert all(catalog_item_is_builder_ready(item) is item.enabled for item in items)
    assert category_style(CATEGORY_CONDITION).label_key == "automation.category_condition"
    assert category_style(CATEGORY_TRIGGER).label_key == "automation.category_trigger"


def test_add_block_menu_enabled_disabled_contrast_and_order(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1400, 860)
    editor.show()
    app.processEvents()
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    items = popup.findChildren(QPushButton, "workflowAddBlockItem")
    by_id = {item.property("itemId"): item for item in items}
    assert set(by_id) == {
        "manual_run",
        "files_added",
        "daily",
        "specific_time",
        "folder",
        "multiple_folders",
        "favorites",
        "tagged_images",
        "all",
        "text",
        "meaning",
        "similar",
        "duplicates",
        "tag_exists",
        "filename_contains",
        "is_favorite",
        "duplicate_found",
        "move",
        "add_tag",
        "remove_tag",
        "rename",
        "favorites_add",
        "delete",
    }
    for section in popup._sections:
        flags = [button.item.enabled for button in section[3]]
        assert flags == sorted(flags, reverse=True)
        assert section[2].verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    enabled_name = by_id["add_tag"].findChild(QLabel, "workflowAddBlockName")
    disabled_name = by_id["rename"].findChild(QLabel, "workflowAddBlockName")
    assert COLORS.text in enabled_name.styleSheet()
    assert "font-weight: 600" in enabled_name.styleSheet()
    assert COLORS.text_faint in disabled_name.styleSheet()
    assert category_style(CATEGORY_ACTION).ink == by_id["add_tag"].findChild(QLabel, "workflowAddBlockGlyph").property("iconInk")
    assert by_id["rename"].findChild(QLabel, "workflowAddBlockGlyph").property("iconInk") == COLORS.text_faint
    assert by_id["move"].cursor().shape() == Qt.PointingHandCursor
    assert by_id["rename"].cursor().shape() == Qt.ArrowCursor
    before = len(editor.visual_blocks())
    by_id["move"].click()
    app.processEvents()
    assert len(editor.visual_blocks()) == before + 2
    assert editor.visual_blocks()[-1].title == t("automation.action_move")
    editor._open_add_popup()
    app.processEvents()
    remove = next(
        item for item in editor._add_popup.findChildren(QPushButton, "workflowAddBlockItem") if item.property("itemId") == "remove_tag"
    )
    after_move = len(editor.visual_blocks())
    remove.click()
    app.processEvents()
    assert len(editor.visual_blocks()) == after_move + 1
    assert editor.visual_blocks()[-1].title == t("automation.action_remove_tag")
    editor.close()


def test_add_block_menu_card_placement_and_theme(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1400, 860)
    editor.show()
    app.processEvents()
    editor._open_add_popup()
    app.processEvents()
    popup = editor._add_popup
    toolbar = editor.findChild(QFrame, "workflowCanvasToolbar")
    assert toolbar is not None
    assert popup.testAttribute(Qt.WA_TranslucentBackground)
    assert popup.RADIUS == RADIUS_CARD
    card = QRect(popup.mapToGlobal(popup.card_rect().topLeft()), popup.card_rect().size())
    bar = QRect(toolbar.mapToGlobal(toolbar.rect().topLeft()), toolbar.size())
    assert card.intersects(bar) is False
    assert card.bottom() <= bar.top() - 4
    area = popup._available_rect(editor._add_block)
    popup_global = QRect(popup.mapToGlobal(popup.rect().topLeft()), popup.size())
    assert area.contains(popup_global.adjusted(1, 1, -1, -1))
    assert abs(popup_global.center().x() - area.center().x()) <= 8
    workspace = QRect(
        editor._workspace.mapToGlobal(editor._workspace.rect().topLeft()),
        editor._workspace.size(),
    )
    assert workspace.adjusted(8, 8, -8, -8).intersects(popup_global)
    image = popup.grab().toImage()
    corner = image.pixelColor(1, 1)
    assert corner.alpha() < 40
    card_image = popup._card.grab().toImage()
    mid = card_image.pixelColor(20, 16)
    surface = QColor(COLORS.surface)
    assert abs(mid.red() - surface.red()) < 28
    assert abs(mid.green() - surface.green()) < 28
    assert abs(mid.blue() - surface.blue()) < 28
    names = [
        label
        for label in popup.findChildren(QLabel)
        if label.objectName() == "workflowAddBlockName" and not label.parent().isEnabled()
    ]
    assert names
    assert COLORS.text_faint in names[0].styleSheet()
    editor.resize(980, 620)
    app.processEvents()
    if not popup.isVisible():
        editor._open_add_popup()
        app.processEvents()
    popup_after = QRect(popup.mapToGlobal(popup.rect().topLeft()), popup.size())
    area_after = popup._available_rect(editor._add_block)
    assert area_after.contains(popup_after.adjusted(1, 1, -1, -1))
    assert abs(popup_after.center().x() - area_after.center().x()) <= 8
    bar_after = QRect(toolbar.mapToGlobal(toolbar.rect().topLeft()), toolbar.size())
    card_after = QRect(popup.mapToGlobal(popup.card_rect().topLeft()), popup.card_rect().size())
    assert card_after.intersects(bar_after) is False
    editor.close()


def _assert_group_follows_blocks(canvas: WorkflowCanvas) -> None:
    union = canvas.connected_blocks_rect()
    group = canvas.flow_group_rect()
    assert not union.isEmpty()
    assert not group.isEmpty()
    expected = union.adjusted(-GROUP_PAD_X, -GROUP_PAD_Y, GROUP_PAD_X, GROUP_PAD_Y)
    assert abs(group.left() - expected.left()) <= 1.5
    assert abs(group.top() - expected.top()) <= 1.5
    assert abs(group.right() - expected.right()) <= 1.5
    assert abs(group.bottom() - expected.bottom()) <= 1.5
    for item in canvas._blocks:
        body = canvas._block_scene_bounds(item)
        assert group.contains(body) or group.intersects(body)
        assert body.center().y() > group.top() + 8
        assert body.center().y() < group.bottom() - 8


def test_flow_group_bounds_follow_add_remove_drag_align(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.resize(1200, 760)
    editor.show()
    app.processEvents()
    canvas = editor._canvas
    _assert_group_follows_blocks(canvas)
    before = canvas.flow_group_rect()
    editor.add_block(make_act_step("add_tag", {"tag": "dog"}))
    app.processEvents()
    after_add = canvas.flow_group_rect()
    assert after_add.width() > before.width()
    _assert_group_follows_blocks(canvas)
    first = canvas._blocks[0]
    first.setPos(first.pos().x() + 36, first.pos().y() + 48)
    app.processEvents()
    _assert_group_follows_blocks(canvas)
    editor._sort_blocks()
    app.processEvents()
    _assert_group_follows_blocks(canvas)
    action_index = len(editor.visual_blocks()) - 1
    editor.remove_block(action_index)
    app.processEvents()
    _assert_group_follows_blocks(canvas)
    assert canvas.flow_group_rect().width() < after_add.width()
    editor.close()


def test_select_search_action_labels_and_inspector(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor.add_block(make_find_step("Capixe"))
    editor.add_block(make_act_step("add_tag", {"tag": "Capixe"}))
    app.processEvents()
    blocks = editor.visual_blocks()
    assert blocks[0].category == CATEGORY_SELECT
    assert category_style(blocks[0].category).label_key == "automation.category_select"
    assert category_style(blocks[1].category).label_key == "automation.category_search"
    assert category_style(blocks[2].category).label_key == "automation.category_action"
    editor._canvas.select_index(0)
    app.processEvents()
    assert editor._kind_label.text() == t("automation.category_select")
    folder_title_x = editor._block_title.mapTo(editor._inspector, editor._block_title.rect().topLeft()).x()
    folder_kind_x = editor._kind_icon.mapTo(editor._inspector, editor._kind_icon.rect().topLeft()).x()
    folder_field_x = editor._folder_label.mapTo(editor._inspector, editor._folder_label.rect().topLeft()).x()
    assert folder_title_x == folder_kind_x
    assert folder_field_x == folder_kind_x
    editor._canvas.select_index(1)
    app.processEvents()
    assert editor._kind_label.text() == t("automation.category_search")
    search_title_x = editor._block_title.mapTo(editor._inspector, editor._block_title.rect().topLeft()).x()
    search_kind_x = editor._kind_icon.mapTo(editor._inspector, editor._kind_icon.rect().topLeft()).x()
    search_param_x = editor._param_label.mapTo(editor._inspector, editor._param_label.rect().topLeft()).x()
    assert search_title_x == folder_title_x
    assert search_kind_x == folder_kind_x
    assert search_param_x == folder_field_x
    editor._canvas.select_index(2)
    app.processEvents()
    assert editor._kind_label.text() == t("automation.category_action")
    action_title_x = editor._block_title.mapTo(editor._inspector, editor._block_title.rect().topLeft()).x()
    assert action_title_x == folder_title_x
    editor.close()


def test_inspector_tabs_and_folder_browse(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    tabs = editor._inspector_tabs
    assert tabs.currentIndex() == 0
    assert tabs.tabText(0) == t("automation.inspector_settings")
    assert tabs.tabText(1) == t("automation.inspector_ai")
    tabs.setCurrentIndex(1)
    app.processEvents()
    assert tabs.currentIndex() == 1
    assert tabs._buttons[1].isEnabled() is True
    assert bool(tabs._buttons[1].property("catalogEnabled")) is True
    assert tabs._buttons[1].cursor().shape() == Qt.PointingHandCursor
    assert editor._draft_input.isVisible() is True
    assert editor.findChild(QWidget, "askAiChat") is None
    assert editor._draft_button.text() == t("automation.draft_action")
    tabs.setCurrentIndex(0)
    editor._canvas.select_index(0)
    app.processEvents()
    assert editor._folder_pick.isVisible()
    assert editor._folder_group.isVisible()
    assert editor._inspector.objectName() == "workflowInspectorPane"
    assert editor._inspector.layout().contentsMargins().left() >= 16
    assert editor._folder_group.layout().contentsMargins().left() == 0
    assert editor._block_title.minimumHeight() == 32
    assert editor._path.isReadOnly()
    assert editor._path.isVisible() is False
    assert editor._info_callout.isVisible()
    assert t("automation.inspector_callout_folder") in editor._info_text.text()
    assert editor._folder_pick._browse.objectName() == "workflowFolderBrowse"
    assert editor._folder_pick._browse.text() == ""
    assert not editor._folder_pick._browse.icon().isNull()
    card = editor.findChild(QFrame, "workflowAiCard")
    assert card is not None
    assert card.isEnabled() is True
    assert bool(card.property("catalogEnabled")) is True
    assert editor._open_ai.text() == t("automation.open_ai")
    assert editor._open_ai.isEnabled() is True
    assert editor._open_ai.cursor().shape() == Qt.PointingHandCursor
    editor._open_ai.click()
    app.processEvents()
    assert tabs.currentIndex() == 1
    editor.close()


def test_workflow_identity_pencil_apply_cancel_and_empty_name(tmp_path):
    app = _ensure_app()
    editor = _editor(tmp_path)
    editor.show()
    app.processEvents()
    editor._name.setText("test")
    editor._description.setText("Description")
    editor._refresh_chrome()
    assert editor._name_label.text() == "test"
    assert editor._description_label.text() == "Description"
    assert editor._pencil.objectName() == "workflowIdentityPencil"
    assert editor._name.isReadOnly() is True
    header = editor.findChild(QFrame, "workflowEditorHeader")
    assert header is not None
    before_h = header.height()
    editor._begin_identity_edit()
    app.processEvents()
    assert editor._name.isReadOnly() is False
    assert editor._identity_cancel.isVisible() is True
    assert editor._run.isEnabled() is False
    assert header.height() == before_h
    editor._name.setText("Renamed")
    editor._description.setText("Updated")
    editor._cancel_identity_edit()
    app.processEvents()
    assert editor._name.text() == "test"
    assert editor._description.text() == "Description"
    assert editor._name.isReadOnly() is True
    editor._begin_identity_edit()
    editor._name.clear()
    editor._apply_identity_edit()
    assert editor._name.isReadOnly() is False
    assert editor._status.text() == t("automation.name_required")
    editor._name.setText("Applied")
    editor._description.setText("Ready notes")
    editor._apply_identity_edit()
    app.processEvents()
    assert editor._name.isReadOnly() is True
    assert editor._name.text() == "Applied"
    assert editor._name_label.text() == "Applied"
    assert editor._run.isEnabled() is True
    editor.add_block(make_act_step("add_tag", {"tag": "keep"}))
    assert editor._save_document() is True
    editor.close()
