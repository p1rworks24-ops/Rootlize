"""Main-window adapter: anchors, navigation, and overlay wiring for the tour."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from app.prototype_tour.anchors import AnchorRegistry
from app.prototype_tour.controller import TourController
from app.prototype_tour.events import install_tour_bus
from app.prototype_tour.models import (
    STEP_AI_PREP,
    STEP_LOCAL_PREP,
    ANCHOR_ACCOUNT_NAV,
    ANCHOR_ACCOUNT_SIGN_IN,
    ANCHOR_ACT_PREVIEW,
    ANCHOR_ASK_AI_SAVE,
    ANCHOR_AUTOMATION_ADD_BLOCK,
    ANCHOR_AUTOMATION_BUILDER,
    ANCHOR_AUTOMATION_CHOICE,
    ANCHOR_AUTOMATION_FOLDER,
    ANCHOR_AUTOMATION_INSPECTOR,
    ANCHOR_AUTOMATION_PARAM,
    ANCHOR_AUTOMATION_LIST,
    ANCHOR_AUTOMATION_NAV,
    ANCHOR_AUTOMATION_NEW,
    ANCHOR_AUTOMATION_LIST_RUN,
    ANCHOR_AUTOMATION_RUN,
    ANCHOR_AUTOMATION_SAVE,
    ANCHOR_AUTOMATION_FIT,
    ANCHOR_IMAGES_ASK_AI,
    ANCHOR_IMAGES_ASK_AI_BUTTON,
    ANCHOR_IMAGES_FAVORITE,
    ANCHOR_IMAGES_FOLDER,
    ANCHOR_IMAGES_NAV,
    ANCHOR_IMAGES_ORGANIZE,
    ANCHOR_IMAGES_SEARCH,
    ANCHOR_IMAGES_TAGS,
    ANCHOR_SEARCH_RESULTS_GRID,
    TourView,
)
from app.ui.tour_overlay import TourOverlay
from app.ui.tour_welcome import TourChrome


class MainWindowTourHost:
    def __init__(self, window) -> None:
        self.window = window
        self.anchors = AnchorRegistry()
        self.controller = TourController(
            host=self,
            auth_provider=self._auth_identity,
        )
        app = QApplication.instance()
        if app is not None:
            self.controller.attach_bus(install_tour_bus(app))
        self.overlay = TourOverlay(window, self.anchors)
        self.overlay._refresh_anchors = self.refresh_anchors
        self.chrome = TourChrome(window)
        self.overlay.popover.back_clicked.connect(self.controller.back)
        self.overlay.popover.next_clicked.connect(self.controller.next_fallback)
        self.overlay.popover.skip_clicked.connect(self.controller.skip)
        self.overlay.popover.close_clicked.connect(self.controller.dismiss)
        self.overlay.popover.action_clicked.connect(self.controller.handle_guide_action)
        self._prep_timer = QTimer(window)
        self._prep_timer.setInterval(400)
        self._prep_timer.timeout.connect(self._on_prep_tick)
        self.chrome.welcome.start_clicked.connect(self._on_welcome_primary)
        self.chrome.welcome.skip_clicked.connect(self.controller.skip)
        self.chrome.complete.continue_clicked.connect(self.controller.open_feedback)
        self.chrome.complete.close_clicked.connect(self.controller.stop)
        self.chrome.feedback.submitted.connect(self.controller.submit_feedback)
        self.chrome.feedback.skip_clicked.connect(self.controller.decline_feedback)
        self.chrome.thanks.continue_clicked.connect(self.controller.stop)
        self.controller.subscribe(self.apply_view)
        self.refresh_anchors()

    @property
    def tour(self) -> TourController:
        return self.controller

    def request_app_close(self) -> None:
        window = self.window
        if window is not None:
            window.close()

    def show_images(self) -> None:
        from app.ui.main_window import PAGE_IMAGES

        stack = getattr(self.window, "_stack", None)
        if stack is not None and stack.currentIndex() == PAGE_IMAGES:
            return
        self.window._show_page(PAGE_IMAGES)

    def show_account(self) -> None:
        from app.ui.main_window import PAGE_ACCOUNT

        self.window._show_page(PAGE_ACCOUNT)

    def show_automation(self) -> None:
        from app.ui.main_window import PAGE_AUTOMATION

        self.window._show_page(PAGE_AUTOMATION)

    def show_automation_list(self) -> None:
        from app.ui.main_window import PAGE_AUTOMATION

        self.window._show_page(PAGE_AUTOMATION)
        page = getattr(self.window, "_automation_page", None)
        if page is None:
            return
        shower = getattr(page, "_show_list", None)
        if callable(shower):
            shower()

    def _on_welcome_primary(self) -> None:
        self.controller.start()

    def open_ask_ai(self) -> None:
        page = getattr(self.window, "_images_page", None)
        if page is None:
            return
        show = getattr(page, "_show_ai_panel", None)
        if callable(show):
            show()

    def show_ask_ai_explanation(self) -> bool:
        page = getattr(self.window, "_images_page", None)
        shower = getattr(page, "show_ask_ai_explanation", None) if page is not None else None
        if not callable(shower):
            return True
        return bool(shower())

    def close_ask_ai(self) -> None:
        page = getattr(self.window, "_images_page", None)
        if page is None:
            return
        hide = getattr(page, "_show_preview_panel", None)
        if callable(hide):
            hide()

    def selected_are_favorite(self) -> bool:
        images = getattr(self.window, "_images_page", None)
        checker = getattr(images, "_selected_images_are_favorite", None)
        return bool(callable(checker) and checker())

    def sync_favorite_anchor(self) -> None:
        images = getattr(self.window, "_images_page", None)
        sync = getattr(images, "_sync_tour_favorite_anchor", None)
        if callable(sync):
            sync()
        self.refresh_anchors()

    def open_automation_draft(self) -> None:
        from app.ui.main_window import PAGE_AUTOMATION

        self.window._show_page(PAGE_AUTOMATION)
        page = getattr(self.window, "_automation_page", None)
        if page is None:
            return
        opener = getattr(page, "open_draft", None)
        if callable(opener):
            opener(None)

    def automation_builder_snapshot(self) -> dict:
        page = getattr(self.window, "_automation_page", None)
        editor = getattr(page, "_editor", None) if page is not None else None
        reader = getattr(editor, "tour_snapshot", None) if editor is not None else None
        data = reader() if callable(reader) else {}
        return data if isinstance(data, dict) else {}

    def focus_automation_inspector(self, kind: str) -> None:
        page = getattr(self.window, "_automation_page", None)
        editor = getattr(page, "_editor", None) if page is not None else None
        focus = getattr(editor, "focus_tour_inspector", None) if editor is not None else None
        if callable(focus):
            focus(kind)

    def fit_automation_canvas(self) -> None:
        page = getattr(self.window, "_automation_page", None)
        editor = getattr(page, "_editor", None) if page is not None else None
        fitter = getattr(editor, "_fit", None) if editor is not None else None
        if callable(fitter):
            fitter()

    def _set_tour_catalog(self, item_ids: tuple[str, ...] | list[str] | None) -> None:
        page = getattr(self.window, "_automation_page", None)
        editor = getattr(page, "_editor", None) if page is not None else None
        setter = getattr(editor, "set_tour_catalog_allow", None) if editor is not None else None
        if callable(setter):
            setter(item_ids)

    def refresh_anchors(self) -> None:
        window = self.window
        images = getattr(window, "_images_page", None)
        automation = getattr(window, "_automation_page", None)
        nav = getattr(window, "_side_nav", None)
        if images is not None:
            self.anchors.register(ANCHOR_IMAGES_FOLDER, getattr(images, "_folder_selector", None))
            self.anchors.register(ANCHOR_IMAGES_SEARCH, getattr(images, "_search_shell", None))
            sync = getattr(images, "_sync_tour_favorite_anchor", None)
            if callable(sync):
                sync()
            self.anchors.register(
                ANCHOR_IMAGES_ORGANIZE,
                getattr(images, "_sort_field", None) or getattr(images, "_header_tools", None),
            )
            self.anchors.register(ANCHOR_IMAGES_TAGS, getattr(images, "_actions_tags_btn", None))
            self.anchors.register(
                ANCHOR_IMAGES_FAVORITE, getattr(images, "_tour_favorite_anchor", None)
            )
            self.anchors.register(
                ANCHOR_IMAGES_ASK_AI,
                getattr(images, "_action_input_row", None)
                or getattr(images, "_ai_history", None)
                or getattr(images, "_ai_page", None),
            )
            self.anchors.register(ANCHOR_IMAGES_ASK_AI_BUTTON, getattr(images, "_ask_ai_btn", None))
            self.anchors.register(ANCHOR_SEARCH_RESULTS_GRID, getattr(images, "_list_widget", None))
            self.anchors.register(
                ANCHOR_ACT_PREVIEW, getattr(images, "_tour_act_preview_widget", None)
            )
            save_btn = images.findChild(QPushButton, "askAiSaveAutomation")
            self.anchors.register(
                ANCHOR_ASK_AI_SAVE,
                save_btn if save_btn is not None and save_btn.isVisible() else None,
            )
        if nav is not None:
            from app.ui.main_window import PAGE_AUTOMATION, PAGE_IMAGES

            buttons = getattr(nav, "_nav_buttons", {})
            self.anchors.register(ANCHOR_AUTOMATION_NAV, buttons.get(PAGE_AUTOMATION))
            self.anchors.register(ANCHOR_IMAGES_NAV, buttons.get(PAGE_IMAGES))
            self.anchors.register(ANCHOR_ACCOUNT_NAV, getattr(nav, "_account_control", None))
        account = getattr(window, "_account_page", None)
        if account is not None:
            self.anchors.register(ANCHOR_ACCOUNT_SIGN_IN, getattr(account, "_primary", None))
        if automation is not None:
            self.anchors.register(ANCHOR_AUTOMATION_LIST, getattr(automation, "_table", None))
            self.anchors.register(ANCHOR_AUTOMATION_NEW, getattr(automation, "_new_button", None))
            list_run = getattr(automation, "tour_list_run_button", None)
            self.anchors.register(
                ANCHOR_AUTOMATION_LIST_RUN,
                list_run() if callable(list_run) else None,
            )
            editor = getattr(automation, "_editor", None)
            if editor is not None:
                self.anchors.register(ANCHOR_AUTOMATION_BUILDER, getattr(editor, "_canvas", None))
                self.anchors.register(ANCHOR_AUTOMATION_ADD_BLOCK, getattr(editor, "_add_block", None))
                self.anchors.register(
                    ANCHOR_AUTOMATION_INSPECTOR, getattr(editor, "_inspector_tabs", None)
                )
                self.anchors.register(ANCHOR_AUTOMATION_CHOICE, getattr(editor, "_choice_group", None))
                self.anchors.register(ANCHOR_AUTOMATION_PARAM, getattr(editor, "_param_group", None))
                self.anchors.register(ANCHOR_AUTOMATION_FOLDER, getattr(editor, "_folder_pick", None))
                self.anchors.register(ANCHOR_AUTOMATION_SAVE, getattr(editor, "_save", None))
                self.anchors.register(ANCHOR_AUTOMATION_RUN, getattr(editor, "_run", None))
                self.anchors.register(ANCHOR_AUTOMATION_FIT, getattr(editor, "_fit_button", None))

    def apply_view(self, view: TourView) -> None:
        self.refresh_anchors()
        guide = view.guide
        if view.active and guide.step_id in {STEP_AI_PREP, STEP_LOCAL_PREP}:
            if not self._prep_timer.isActive():
                self._prep_timer.start()
                self._on_prep_tick()
        else:
            self._prep_timer.stop()
        if not view.active:
            self._set_tour_catalog(())
            self.overlay.apply(view)
            self.chrome.hide()
            return
        self._set_tour_catalog(guide.catalog_allow)
        if guide.mode == "guide":
            self.chrome.hide()
            self.overlay.apply(view)
            self.overlay.raise_()
            self.overlay.popover.raise_()
        else:
            self.overlay.apply(TourView(active=False))
            self.chrome.apply(guide)
            self.chrome.raise_()

    def record_ai_consent(self) -> None:
        images = getattr(self.window, "_images_page", None)
        writer = getattr(images, "record_tour_ai_consent", None) if images is not None else None
        if callable(writer):
            writer()

    def start_ai_preparation(self) -> str:
        images = getattr(self.window, "_images_page", None)
        starter = getattr(images, "start_tour_ai_preparation", None) if images is not None else None
        if not callable(starter):
            return "failed"
        result = starter()
        return str(result or "failed")

    def ai_preparation_snapshot(self) -> dict:
        images = getattr(self.window, "_images_page", None)
        reader = getattr(images, "tour_ai_preparation_snapshot", None) if images is not None else None
        if not callable(reader):
            return {}
        data = reader()
        return data if isinstance(data, dict) else {}

    def local_preparation_snapshot(self) -> dict:
        images = getattr(self.window, "_images_page", None)
        reader = getattr(images, "tour_local_preparation_snapshot", None) if images is not None else None
        if not callable(reader):
            return {}
        data = reader()
        return data if isinstance(data, dict) else {}

    def _on_prep_tick(self) -> None:
        self.controller.refresh_ai_prep_status()
        self.controller.refresh_local_prep_status()

    def _auth_identity(self) -> dict:
        controller = getattr(self.window, "_account_controller", None)
        if controller is None:
            return {}
        session = getattr(controller, "session", None)
        service = getattr(controller, "service", None)
        user_id = ""
        token = ""
        config = getattr(service, "client_config", None) if service is not None else None
        if session is not None and getattr(session, "is_authenticated", False):
            user_id = str(getattr(session, "user_id", "") or "")
            token = str(getattr(session, "access_token", "") or "")
        return {"user_id": user_id, "access_token": token, "config": config}
