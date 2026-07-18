"""クリップボード監視の動作確認用スクリプト"""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from app.models.detected_image import DetectedImage
from app.services.clipboard_watcher import ClipboardWatcher


def create_test_image(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    return image


def main():
    app = QApplication(sys.argv)
    clipboard = app.clipboard()

    # テキストをセットして画像をクリア
    clipboard.setText("")

    detections: list[DetectedImage] = []

    def on_detected(detected: DetectedImage):
        detections.append(detected)
        print(
            f"[TEST] 検知: {detected.width}x{detected.height} "
            f"at {detected.detected_at.strftime('%H:%M:%S')}"
        )

    watcher = ClipboardWatcher(interval_ms=200, on_image_detected=on_detected)
    watcher.start()

    def step1_put_first_image():
        print("[TEST] 1枚目の画像をクリップボードにセット")
        clipboard.setImage(create_test_image(320, 180, "red"))

    def step2_same_image_again():
        print("[TEST] 同じ画像を再度セット（重複検知されないはず）")
        clipboard.setImage(create_test_image(320, 180, "red"))

    def step3_different_image():
        print("[TEST] 別サイズの画像をセット")
        clipboard.setImage(create_test_image(640, 480, "blue"))

    def step4_text_only():
        print("[TEST] テキストのみセット（無視されるはず）")
        clipboard.setText("hello")

    def finish():
        watcher.stop()
        count = len(detections)
        print(f"[TEST] 検知回数: {count}")

        if count == 2 and detections[0].width == 320 and detections[1].width == 640:
            print("[TEST] 成功: 新規画像2回のみ検知、サイズも正しい")
            app.quit()
        else:
            print(f"[TEST] 失敗: 期待値は2回（320px, 640px）")
            app.exit(1)

    # 監視開始後にテストを実行
    QTimer.singleShot(500, step1_put_first_image)
    QTimer.singleShot(1200, step2_same_image_again)
    QTimer.singleShot(2000, step3_different_image)
    QTimer.singleShot(2800, step4_text_only)
    QTimer.singleShot(3600, finish)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
