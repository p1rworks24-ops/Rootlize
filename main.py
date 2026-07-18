import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# プロジェクトルートを import パスに追加
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from app.config import load_config
from app.ui.main_window import MainWindow
from app.utils.logger import setup_logger


def ensure_directories():
    """必要なフォルダが無ければ作成する"""
    root = Path(__file__).resolve().parent
    for folder_name in ("assets", "screenshots"):
        folder = root / folder_name
        folder.mkdir(exist_ok=True)


def main():
    logger = setup_logger()
    logger.info("Screenshot Manager を起動します。")

    try:
        ensure_directories()
        config = load_config()

        app = QApplication(sys.argv)
        # Keep running while MainWindow is hidden during screenshot capture
        app.setQuitOnLastWindowClosed(False)
        window = MainWindow(config)
        window.show()

        logger.info("GUI を表示しました。")
        sys.exit(app.exec())

    except Exception as e:
        logger.exception("起動中にエラーが発生しました: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
