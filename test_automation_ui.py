"""Automation page and Ask AI save affordance stay on the existing shell."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QHeaderView, QLabel, QPushButton, QSizePolicy, QToolButton

from app.i18n import t
from app.ui.ask_ai_chat import AskAiConfirmMessage
from app.ui.automation_run_dialog import AutomationRunDialog
from app.ui.main_window import PAGE_AUTOMATION, MainWindow
from app.ui.search_busy import SearchBusySpinner


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
            "window_width": 1000,
            "window_height": 700,
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
            "developer_ask_ai_preview": True,
        }
    )


def test_automation_nav_and_empty_page():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()
    nav = window._side_nav
    assert PAGE_AUTOMATION in nav._nav_buttons
    assert nav._nav_buttons[PAGE_AUTOMATION].property("navLabel") == t("nav.automation")
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_AUTOMATION
    assert window._automation_page._stack.currentWidget() is window._automation_page._list_page
    assert window._automation_page._empty.isVisible()
    assert t("automation.empty") in window._automation_page._empty.text()
    assert window._automation_page._table.isVisible()
    assert window._automation_page._table.rowCount() == 0
    subtitle = next(
        label
        for label in window._automation_page.findChildren(QLabel)
        if label.objectName() == "pageSubtitle"
    )
    title = next(
        label
        for label in window._automation_page.findChildren(QLabel)
        if label.objectName() == "pageTitle"
    )
    assert subtitle.x() == title.x()
    assert subtitle.y() >= title.y() + title.height()
    labels = {button.text() for button in window._automation_page.findChildren(QPushButton)}
    assert t("automation.new") in labels
    window.close()


def test_saved_workflow_lists_run_rename_delete():
    app = _ensure_app()
    window = _make_window()
    from app.automation import format_list_date, workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

    folder = Path(tempfile.mkdtemp())
    workflow = workflow_from_session(
        name="Tag dogs",
        description="Find then tag",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
        action_id="add_tag",
        parameters={"tag": "work"},
    )
    window._automation_service.save(workflow)
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    page = window._automation_page
    table = page._table
    assert not table.isHidden()
    assert page._empty.isHidden()
    assert table.columnCount() == 7
    assert table.horizontalHeaderItem(0).text() == t("automation.run")
    assert table.horizontalHeaderItem(4).text() == t("automation.list_created")
    assert table.item(0, 1).text() == "Tag dogs"
    assert table.item(0, 4).text() == format_list_date(workflow.created_at, with_time=True)
    assert " " in table.item(0, 4).text()
    assert table.item(0, 5).text() == t("automation.last_run_none")
    header = table.horizontalHeader()
    assert header.sectionResizeMode(1) == QHeaderView.Interactive
    assert header.sectionResizeMode(2) == QHeaderView.Stretch
    assert table.columnWidth(1) == 176
    action_buttons = [
        button
        for button in page.findChildren(QToolButton)
        if button.objectName() in {"automationRowIconButton", "automationRowDeleteButton"}
    ]
    assert action_buttons
    assert all(button.iconSize().width() >= 18 for button in action_buttons)
    run_buttons = [
        button
        for button in page.findChildren(QPushButton)
        if button.objectName() == "automationListRunButton"
    ]
    assert run_buttons
    assert run_buttons[0].text() == ""
    assert run_buttons[0].toolTip() == t("automation.run")
    assert run_buttons[0].accessibleName() == t("automation.run")
    assert run_buttons[0].isEnabled()
    tips = {button.toolTip() for button in page.findChildren(QToolButton)}
    assert t("automation.edit") in tips
    assert t("automation.rename") in tips
    assert t("automation.delete") in tips
    badges = [
        label
        for label in page.findChildren(QLabel)
        if label.objectName() == "automationStatusBadge"
    ]
    assert badges
    assert badges[0].text() == t("automation.status_ready")
    assert badges[0].property("status") == "ready"
    assert badges[0].toolTip() == t("automation.status_ready_hint")
    window.show()
    app.processEvents()
    page._align_icon_columns_to_headers()
    app.processEvents()
    run_host = table.cellWidget(0, 0)
    action_host = table.cellWidget(0, 6)
    first_action = action_host.layout().itemAt(0).widget()
    assert first_action is not None
    assert first_action.objectName() == "automationRowIconButton"
    run_button = run_host.findChild(QPushButton, "automationListRunButton")
    assert run_button is not None
    run_left = run_button.mapTo(table, QPoint(0, 0)).x()
    action_left = first_action.mapTo(table, QPoint(0, 0)).x()
    badge_left = badges[0].mapTo(table, QPoint(0, 0)).x()
    assert abs(run_left - page._header_label_left(0)) <= 1
    assert abs(badge_left - page._header_label_left(3)) <= 1
    assert abs(action_left - page._header_label_left(6)) <= 1
    window.close()


def _finish_run_dialog(app: QApplication, *, accept: bool) -> None:
    def _click() -> None:
        for widget in app.topLevelWidgets():
            if isinstance(widget, AutomationRunDialog) and widget.isVisible():
                if accept and widget.can_run:
                    widget.accept()
                else:
                    widget.reject()
                return

    QTimer.singleShot(0, _click)


def test_run_dialog_shows_behavior_and_can_cancel():
    app = _ensure_app()
    from app.automation import workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

    folder = Path(tempfile.mkdtemp())
    workflow = workflow_from_session(
        name="Tag dogs",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
        action_id="add_tag",
        parameters={"tag": "work"},
    )
    dialog = AutomationRunDialog(None, workflow=workflow)
    assert dialog.can_run is True
    assert dialog.windowTitle() == t("automation.run_title")
    assert "Tag dogs" in dialog.findChild(QLabel, "automationRunHeading").text()
    assert "work" in dialog.behavior_text
    assert folder.name in dialog.behavior_text
    assert dialog._confirm.text() == t("automation.run_execute")
    assert dialog._confirm.isEnabled()
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_run_opens_review_popup_and_cancel_stays_on_automation():
    app = _ensure_app()
    window = _make_window()
    from app.automation import workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

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
    _finish_run_dialog(app, accept=False)
    window._run_automation_workflow(workflow.id)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_AUTOMATION
    assert window._images_page._ai_panel_expanded is False
    assert (folder / "dog-a.png").exists()
    assert "work" not in window._images_page._metadata_service.get_image_tags(folder, "dog-a.png")
    message = AskAiConfirmMessage()
    message.set_preview("2 images will get the work tag.", "", t("images.ai.confirm_tag"))
    assert message._save_btn.text() == t("images.ai.save_automation")
    window.close()


def test_run_execute_from_popup_does_not_use_ask_ai_confirm():
    app = _ensure_app()
    window = _make_window()
    from app.automation import format_list_date, workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

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
    confirms_before = len(window._images_page._ai_history._confirm_messages)
    _finish_run_dialog(app, accept=True)
    window._run_automation_workflow(workflow.id)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_AUTOMATION
    assert window._automation_page._stack.currentWidget() is window._automation_page._list_page
    assert workflow.id not in window._automation_page._running_ids
    assert len(window._images_page._ai_history._confirm_messages) == confirms_before
    assert "work" in window._images_page._metadata_service.get_image_tags(folder, "dog-a.png")
    toast = window._toast_host._toast
    assert toast.isVisible()
    assert toast._title_label.text() == t("automation.toast_done_title")
    stored = window._automation_service.get(workflow.id)
    assert stored is not None
    assert stored.last_run_at
    last_run = window._automation_page._table.item(0, 5)
    assert last_run is not None
    assert last_run.text() == format_list_date(stored.last_run_at, with_time=True)
    assert " " in last_run.text()
    window.close()


def test_running_workflow_shows_status_and_spinner():
    app = _ensure_app()
    window = _make_window()
    from app.automation import workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

    folder = Path(tempfile.mkdtemp())
    workflow = workflow_from_session(
        name="Tag dogs",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
        action_id="add_tag",
        parameters={"tag": "work"},
    )
    window._automation_service.save(workflow)
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    page = window._automation_page
    page.set_running(workflow.id, True)
    app.processEvents()
    assert page._stack.currentWidget() is page._list_page
    table = page._table
    run_host = table.cellWidget(0, 0)
    status_host = table.cellWidget(0, 3)
    run_button = run_host.findChild(QPushButton, "automationListRunButton")
    badge = status_host.findChild(QLabel, "automationStatusBadge")
    spinner = status_host.findChild(SearchBusySpinner, "automationStatusSpinner")
    assert run_button is not None
    assert not run_button.isEnabled()
    assert badge is not None
    assert badge.text() == t("automation.status_running")
    assert badge.property("status") == "running"
    assert badge.toolTip() == t("automation.status_running_hint")
    assert spinner is not None
    window.show()
    app.processEvents()
    page._align_icon_columns_to_headers()
    app.processEvents()
    badge_left = badge.mapTo(table, QPoint(0, 0)).x()
    assert abs(badge_left - page._header_label_left(3)) <= 1
    page.set_running(workflow.id, False)
    app.processEvents()
    status_host = table.cellWidget(0, 3)
    badge = status_host.findChild(QLabel, "automationStatusBadge")
    assert badge is not None
    assert badge.text() == t("automation.status_ready")
    assert status_host.findChild(SearchBusySpinner, "automationStatusSpinner") is None
    window.close()


def test_incomplete_workflow_shows_needs_action_badge():
    app = _ensure_app()
    window = _make_window()
    from app.automation import workflow_from_session
    from app.workspace import ORIGIN_MEANING, SearchResultContext

    folder = Path(tempfile.mkdtemp())
    workflow = workflow_from_session(
        name="Draft",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
    )
    window._automation_service.save_draft(workflow)
    window._show_page(PAGE_AUTOMATION)
    app.processEvents()
    page = window._automation_page
    run_buttons = [
        button
        for button in page.findChildren(QPushButton)
        if button.objectName() == "automationListRunButton"
    ]
    assert run_buttons
    assert not run_buttons[0].isEnabled()
    badges = [
        label
        for label in page.findChildren(QLabel)
        if label.objectName() == "automationStatusBadge"
    ]
    assert badges
    assert badges[0].text() == t("automation.status_need_action")
    assert badges[0].property("status") == "needs_action"
    assert badges[0].toolTip() == t("automation.status_need_action_hint")
    assert badges[0].sizePolicy().horizontalPolicy() == QSizePolicy.Maximum
    assert page._table.columnWidth(3) >= badges[0].sizeHint().width()
    window.close()
