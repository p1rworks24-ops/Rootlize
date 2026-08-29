"""Ask AI first-use consent is one screen; Agree is the send-start boundary."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app.config import (
    ASK_AI_CONSENT_NOTICE_VERSION,
    ASK_AI_CONSENT_NOTICE_VERSION_KEY,
    ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY,
    DEFAULT_CONFIG,
    has_ask_ai_external_processing_consent,
    needs_ask_ai_consent_notice,
)
from app.i18n import en as en_messages
from app.i18n import ja as ja_messages
from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.ask_ai_consent_dialog import AskAiConsentDialog
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from test_ask_ai_meaning_search import (
    RecordingMeaningProvider,
    _open_and_send,
    _wait_ask_ai,
)
from conftest import install_ask_ai_test_planner


_FORBIDDEN_UI_TERMS = (
    "Semantic Index",
    "embedding",
    "Vision Judge",
    "OpenCLIP",
    "OCR",
    "vision-usefulness",
    "gpt-",
    "OpenAI",
    "ActionRequest",
)


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


class RecordingIndexer:
    def __init__(self) -> None:
        self.starts: list[tuple] = []

    def start(self, folder, consented=False):
        self.starts.append((folder, bool(consented)))
        return True

    def snapshot(self, folder=None):
        del folder
        return {
            "ready": 0,
            "total": 1,
            "running": True,
            "needed": 1,
            "error": False,
        }


def _page(tmp_path: Path, provider, *, consented: bool | None = False, indexer=None):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    _png(folder / "notes.png")
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "developer_search_mode": "text",
    }
    if consented is not None:
        config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] = consented
        if consented:
            config[ASK_AI_CONSENT_NOTICE_VERSION_KEY] = ASK_AI_CONSENT_NOTICE_VERSION
    page = ImagesPage(
        config,
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=lambda *_args: (),
        semantic_search_provider=lambda *_args: (),
        vision_search_provider=provider,
        semantic_index_indexer=indexer,
    )
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    install_ask_ai_test_planner(page)
    return page, folder


class _ScriptedConsentDialog:
    def __init__(self, result, opened):
        self._result = result
        self._opened = opened

    def __call__(self, parent=None):
        self._opened.append(parent)
        return self

    def exec(self):
        return self._result


def test_default_config_does_not_grant_ask_ai_consent():
    assert DEFAULT_CONFIG[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is False
    assert has_ask_ai_external_processing_consent({}) is False
    assert has_ask_ai_external_processing_consent(
        {ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY: True}
    ) is True


def test_consent_dialog_explains_capabilities_and_external_ai_without_internal_terms():
    _app()
    dialog = AskAiConsentDialog()
    assert dialog.windowTitle() == t("images.ai.consent.title")
    title = dialog.findChild(QLabel, "askAiConsentTitle")
    subtitle = dialog.findChild(QLabel, "askAiConsentSubtitle")
    footnote = dialog.findChild(QLabel, "askAiConsentFootnote")
    section = dialog.findChild(QLabel, "askAiConsentSectionTitle")
    assert title is not None and title.text() == t("images.ai.consent.title")
    assert section is not None
    assert "Ask AI" in section.text() or "できること" in section.text()
    bodies = [
        label.text()
        for label in dialog.findChildren(QLabel, "askAiConsentFactBody")
    ]
    examples = [
        label.text()
        for label in dialog.findChildren(QLabel, "askAiConsentExample")
    ]
    combined = " ".join(
        [
            title.text(),
            subtitle.text(),
            footnote.text(),
            section.text(),
            *bodies,
            *examples,
        ]
    )
    assert t("images.ai.consent.meaning.example1") in combined
    assert t("images.ai.consent.meaning.example2") in combined
    assert t("images.ai.consent.action.example1") in combined
    assert t("images.ai.consent.action.example2") in combined
    assert "Show me screenshots containing Google Chrome" in en_messages.MESSAGES[
        "images.ai.consent.meaning.example2"
    ]
    assert "Find dog images and tag them Test" in en_messages.MESSAGES[
        "images.ai.consent.action.example2"
    ]
    en_examples = " ".join(
        en_messages.MESSAGES[key]
        for key in (
            "images.ai.consent.meaning.example1",
            "images.ai.consent.meaning.example2",
            "images.ai.consent.action.example1",
            "images.ai.consent.action.example2",
        )
    )
    assert "青い画面" not in en_examples
    assert "この画像を" not in en_examples
    assert "filename" in combined.lower() or "ファイル名" in combined
    assert "external AI" in combined
    assert "sent" in combined.lower() or "送信" in combined
    assert "reused" in combined.lower() or "再利用" in combined
    titles = [
        label.text()
        for label in dialog.findChildren(QLabel, "askAiConsentFactTitle")
    ]
    combined = " ".join([combined, *titles])
    assert t("images.ai.consent.folder_size.title") in combined
    assert "50–200" in combined or "50-200" in combined
    assert "1,000+" in combined
    assert "may take longer" in combined.lower()
    for term in _FORBIDDEN_UI_TERMS:
        assert term not in combined
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
    assert t("images.ai.consent.agree") in buttons
    assert t("images.ai.consent.cancel") in buttons
    buttons[t("images.ai.consent.cancel")].click()
    assert dialog.result() == QDialog.Rejected
    dialog.deleteLater()


def test_consent_copy_omits_internal_implementation_terms():
    keys = [key for key in en_messages.MESSAGES if key.startswith("images.ai.consent.")]
    assert keys
    for catalog in (en_messages.MESSAGES, ja_messages.MESSAGES):
        combined = " ".join(catalog[key] for key in keys if key in catalog)
        for term in _FORBIDDEN_UI_TERMS:
            assert term not in combined


def test_consent_dialog_agree_accepts_without_side_effects():
    _app()
    dialog = AskAiConsentDialog()
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
    buttons[t("images.ai.consent.agree")].click()
    assert dialog.result() == QDialog.Accepted


def test_opening_ask_ai_requests_consent_and_does_not_search(
    tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, opened),
    )
    saved = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.save_config",
        lambda config: saved.append(dict(config)),
    )
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, folder = _page(tmp_path, provider, consented=False, indexer=indexer)

    assert page._right_stack.currentWidget() is page._preview_page
    page._show_ai_panel()

    assert opened
    assert page._right_stack.currentWidget() is page._ai_page
    assert page._config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is True
    assert saved[-1][ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is True
    assert provider.calls == []
    assert page._ai_history.user_texts == []
    assert page._ask_ai_search_tasks == {}
    assert indexer.starts
    assert indexer.starts[-1][1] is True
    assert indexer.starts[-1][0] == folder
    page.close()


def test_declining_consent_keeps_preview_and_does_not_persist(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Rejected, []),
    )
    saved = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.save_config",
        lambda config: saved.append(dict(config)),
    )
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, provider, consented=False, indexer=indexer)
    page._ask_ai_btn.click()

    assert page._right_stack.currentWidget() is page._preview_page
    assert has_ask_ai_external_processing_consent(page._config) is False
    assert saved == []
    assert provider.calls == []
    assert indexer.starts == []
    page.close()


def test_cancel_then_ask_ai_shows_consent_again(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Rejected, opened),
    )
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider, consented=False)
    page._ask_ai_btn.click()
    assert len(opened) == 1
    page._ask_ai_btn.click()
    assert len(opened) == 2
    assert has_ask_ai_external_processing_consent(page._config) is False
    page.close()


def test_consented_open_skips_dialog_and_send_starts_search(
    tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, opened),
    )
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, consented=True)
    provider.batches = [(folder / "notes.png",)]

    page._show_ai_panel()
    assert opened == []
    assert page._right_stack.currentWidget() is page._ai_page
    assert provider.calls == []

    _open_and_send(page, "Find images with dogs in them")
    assert opened == []
    assert provider.calls == ["images with dogs in them"]
    page.close()


def test_first_send_after_inline_consent_is_processing_start(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, []),
    )
    saved = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.save_config",
        lambda config: saved.append(dict(config)),
    )
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, consented=False)
    provider.batches = [(folder / "notes.png",)]
    page._ai_panel_expanded = True
    page._right_stack.setCurrentWidget(page._ai_page)
    page._action_input.setText("Find windows settings")
    page._on_ask_ai_send()
    _wait_ask_ai(page)

    assert page._config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is True
    assert saved[-1][ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is True
    assert provider.calls == ["windows settings"]
    assert page._ai_history.user_texts == ["Find windows settings"]
    page.close()


def test_send_declined_consent_does_not_clear_query_or_search(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Rejected, []),
    )
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider, consented=False)
    page._ai_panel_expanded = True
    page._right_stack.setCurrentWidget(page._ai_page)
    page._action_input.setText("keep this")
    page._on_ask_ai_send()

    assert page._action_input.text() == "keep this"
    assert provider.calls == []
    assert page._ai_history.user_texts == []
    assert has_ask_ai_external_processing_consent(page._config) is False
    page.close()


def test_legacy_consent_without_notice_version_shows_explanation(
    tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, opened),
    )
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, consented=None)
    page._config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] = True
    assert needs_ask_ai_consent_notice(page._config) is True
    page._show_ai_panel()
    assert opened
    assert page._config[ASK_AI_CONSENT_NOTICE_VERSION_KEY] == ASK_AI_CONSENT_NOTICE_VERSION
    assert page._right_stack.currentWidget() is page._ai_page
    assert folder is not None
    page.close()
