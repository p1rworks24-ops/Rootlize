import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# プロジェクトルートを import パスに追加
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from app.branding import APP_NAME, APP_LOGGER_NAME
from app.config import ensure_runtime_directories, load_config
from app.paths import get_app_data_dir, get_legacy_install_root, get_resource_root
from app.ui.app_icon import load_app_icon
from app.ui.main_window import MainWindow
from app.ui.splash_screen import SplashScreen
from app.utils.logger import setup_logger


def main():
    logger = setup_logger()
    logger.info("%s を起動します。", APP_NAME)
    logger.info("Resource root: %s", get_resource_root())
    logger.info("Legacy install root: %s", get_legacy_install_root())
    logger.info("App data dir: %s", get_app_data_dir())

    try:
        # load_config migrates legacy settings, normalizes Root Folder,
        # and creates AppData / screenshot / Capture directories.
        config = load_config()
        ensure_runtime_directories(config)

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setOrganizationName(APP_LOGGER_NAME)
        app_icon = load_app_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        # Keep running while MainWindow is hidden during screenshot capture
        app.setQuitOnLastWindowClosed(False)

        # One native window: show main first, splash overlays the client area
        window = MainWindow(config)
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
        window.show()
        app.processEvents()

        host = window.centralWidget() or window
        splash = SplashScreen(host)
        app.processEvents()

        def _on_finished() -> None:
            splash.close()
            window.raise_()
            window.activateWindow()
            # Hotkeys register during MainWindow init but stay disarmed until
            # splash ends — prevents startup / relaunch auto-Capture.
            window.arm_capture_hotkeys()
            logger.info("GUI を表示しました。")

        splash.finished.connect(_on_finished)
        splash.notify_ready()

        sys.exit(app.exec())

    except Exception as e:
        logger.exception("起動中にエラーが発生しました: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
