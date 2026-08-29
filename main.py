import os
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートを import パスに追加
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


def _startup_trace(stage: str, **fields) -> None:
    """Append a secret-free startup line to %LOCALAPPDATA%\\Capixe\\logs\\startup.log."""
    try:
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if not local:
            return
        log_dir = Path(local) / "Capixe" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        extras = " ".join(
            f"{key}={value}" for key, value in fields.items() if value is not None
        )
        line = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + f" {stage}"
        if extras:
            line += f" {extras}"
        with (log_dir / "startup.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


_startup_trace(
    "entrypoint reached",
    frozen=bool(getattr(sys, "frozen", False)),
    name=__name__,
    ocr_worker=("--ocr-worker" in sys.argv[1:]),
    semantic_worker=("--semantic-worker" in sys.argv[1:]),
)


def _run_version_if_requested() -> bool:
    if "--version" not in sys.argv[1:]:
        return False
    from app.build_info import format_version_text, load_build_info

    info = load_build_info()
    text = format_version_text(info, executable=sys.executable)
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass
    _startup_trace(
        "version",
        executable=sys.executable,
        build_id=info.build_id or "none",
        source_revision=info.source_revision_display or "none",
        official="true" if info.official else "false",
        build_time=info.build_time or "none",
    )
    raise SystemExit(0)


_run_version_if_requested()


def _run_ocr_worker_if_requested() -> bool:
    """Run the bundled OCR worker without initializing the GUI."""
    if "--ocr-worker" not in sys.argv[1:]:
        return False
    _startup_trace("early-return reason", reason="ocr_worker")
    from app.ocr.worker_entry import main as worker_main

    worker_args = [arg for arg in sys.argv[1:] if arg != "--ocr-worker"]
    raise SystemExit(worker_main(worker_args))


_run_ocr_worker_if_requested()


def _run_semantic_worker_if_requested() -> bool:
    """Run the bundled Semantic worker without initializing the GUI."""
    if "--semantic-worker" not in sys.argv[1:]:
        return False
    _startup_trace("early-return reason", reason="semantic_worker")
    from app.semantic.worker import main as worker_main

    worker_args = [arg for arg in sys.argv[1:] if arg != "--semantic-worker"]
    raise SystemExit(worker_main(worker_args))


_run_semantic_worker_if_requested()

try:
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtWidgets import QApplication, QStyleFactory

    from app.branding import APP_NAME, APP_LOGGER_NAME, APP_VERSION
    from app.config import ensure_runtime_directories, load_config
    from app.paths import get_app_data_dir, get_legacy_install_root, get_resource_root
    from app.ui.app_icon import app_ico_path, load_app_icon
    from app.ui.main_window import MainWindow
    from app.ui.fonts import install_ui_font
    from app.ui.splash_screen import SplashScreen
    from app.ui.windows_shell import (
        apply_windows_app_user_model_id,
        apply_windows_window_icons,
        current_windows_app_user_model_id,
    )
    from app.utils.logger import setup_logger
except Exception as exc:
    _startup_trace("startup exception", phase="import", error_type=type(exc).__name__)
    raise


def _attach_startup_file_log(logger) -> None:
    import logging

    from app.paths import ensure_dir, get_logs_dir

    log_dir = get_logs_dir()
    ensure_dir(log_dir, label="logs")
    path = log_dir / "startup.log"
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == path.resolve():
            return
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)


def main():
    _startup_trace("process start")
    logger = setup_logger()
    _attach_startup_file_log(logger)
    logger.info("%s を起動します。", APP_NAME)
    logger.info("Resource root: %s", get_resource_root())
    logger.info("Legacy install root: %s", get_legacy_install_root())
    logger.info("App data dir: %s", get_app_data_dir())
    logger.info("executable path=%s", sys.executable)
    try:
        from app.build_info import load_build_info

        build = load_build_info()
        logger.info(
            "build_id=%s source_revision=%s official=%s build_time=%s dirty=%s",
            build.build_id or "none",
            build.source_revision_display or "none",
            "true" if build.official else "false",
            build.build_time or "none",
            "true" if build.dirty else "false",
        )
        _startup_trace(
            "build identity",
            executable=sys.executable,
            build_id=build.build_id or "none",
            source_revision=build.source_revision_display or "none",
            official="true" if build.official else "false",
            build_time=build.build_time or "none",
        )
    except Exception as exc:
        logger.info("build identity unavailable error_type=%s", type(exc).__name__)
        _startup_trace("build identity", error_type=type(exc).__name__)
    try:
        from app.auth.config import describe_auth_config

        status = describe_auth_config()
        logger.info(
            "Auth configured=%s url_source=%s key_source=%s url_kind=%s key_kind=%s",
            status.configured,
            status.url_source,
            status.key_source,
            status.url_kind,
            status.key_kind,
        )
        logger.info(
            "AI proxy public settings readable=%s",
            status.proxy_functions_readable,
        )
        _startup_trace(
            "auth config",
            configured=status.configured,
            url_source=status.url_source,
            key_source=status.key_source,
            url_kind=status.url_kind,
            key_kind=status.key_kind,
            proxy_readable=status.proxy_functions_readable,
        )
    except Exception as exc:
        logger.info("Auth configured=False reason=status_error error_type=%s", type(exc).__name__)
        _startup_trace("auth config", configured=False, error_type=type(exc).__name__)
    try:
        import app.prototype_tour  # noqa: F401

        logger.info("Prototype tour present=True")
        _startup_trace("prototype tour", present=True)
    except Exception as exc:
        logger.info("Prototype tour present=False error_type=%s", type(exc).__name__)
        _startup_trace("prototype tour", present=False, error_type=type(exc).__name__)

    try:
        # load_config migrates legacy settings, normalizes Root Folder,
        # and creates AppData / screenshot / Capture directories.
        config = load_config()
        ensure_runtime_directories(config)

        aumid = apply_windows_app_user_model_id()
        _startup_trace("AUMID", aumid=aumid)
        QCoreApplication.setApplicationName(APP_NAME)
        QCoreApplication.setOrganizationName(APP_LOGGER_NAME)
        QCoreApplication.setApplicationVersion(APP_VERSION)
        app = QApplication(sys.argv)
        _startup_trace(
            "QApplication created",
            aumid=aumid,
            aumid_actual=current_windows_app_user_model_id() or "none",
        )
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setOrganizationName(APP_LOGGER_NAME)
        install_ui_font(app)
        app_icon = load_app_icon()
        ico = app_ico_path()
        logger.info(
            "app icon ico=%s exists=%s null=%s",
            ico,
            ico.is_file(),
            app_icon.isNull(),
        )
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        # Keep running while MainWindow is hidden during screenshot capture
        app.setQuitOnLastWindowClosed(False)

        # One native window: show main first, splash overlays the client area
        _startup_trace("MainWindow init")
        window = MainWindow(config)
        _startup_trace("MainWindow created")
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
            apply_windows_window_icons(window)
        window.show()
        if not app_icon.isNull():
            apply_windows_window_icons(window)
            QTimer.singleShot(0, lambda: apply_windows_window_icons(window))
            QTimer.singleShot(250, lambda: apply_windows_window_icons(window))
        _startup_trace("MainWindow shown")
        app.processEvents()

        host = window.centralWidget() or window
        splash = SplashScreen(host)
        _startup_trace("Splash")
        app.processEvents()

        def _on_finished() -> None:
            splash.close()
            if not app_icon.isNull():
                apply_windows_window_icons(window)
            window.raise_()
            window.activateWindow()
            # Hotkeys register during MainWindow init but stay disarmed until
            # splash ends — prevents startup / relaunch auto-Capture.
            window.arm_capture_hotkeys()
            # Defer the modal until the splash signal handler has returned and
            # Qt has fully removed the overlay from the main window.
            QTimer.singleShot(0, window.show_welcome_if_needed)
            logger.info("GUI を表示しました。")

        splash.finished.connect(_on_finished)
        splash.notify_ready()

        _startup_trace("event loop entered")
        sys.exit(app.exec())

    except Exception as e:
        _startup_trace("startup exception", phase="main", error_type=type(e).__name__)
        logger.exception("起動中にエラーが発生しました: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
