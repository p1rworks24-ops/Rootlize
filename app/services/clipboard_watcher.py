import hashlib
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QBuffer, QIODevice, QTimer
from PySide6.QtGui import QClipboard, QGuiApplication, QImage

from app.models.detected_image import DetectedImage
from app.utils.logger import setup_logger

logger = setup_logger()


class ClipboardWatcher:
    """クリップボードの画像を定期的に監視する"""

    def __init__(
        self,
        interval_ms: int = 500,
        on_image_detected: Callable[[DetectedImage], None] | None = None,
    ):
        self._clipboard: QClipboard = QGuiApplication.clipboard()
        self._interval_ms = interval_ms
        self._last_hash: str | None = None
        self._on_image_detected = on_image_detected

        # QTimer で一定間隔ごとにクリップボードを確認する
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check_clipboard)

    def start(self) -> None:
        """監視を開始する"""
        self._timer.start()
        logger.info(
            "クリップボード監視を開始しました（間隔: %d ms）",
            self._interval_ms,
        )

    def stop(self) -> None:
        """監視を停止する"""
        self._timer.stop()
        logger.info("クリップボード監視を停止しました。")

    def _check_clipboard(self) -> None:
        """クリップボードに画像があるか確認する"""
        image = self._clipboard.image()

        # 画像以外（テキストなど）は無視する
        if image.isNull():
            return

        image_hash = self._calc_image_hash(image)

        # 同じ画像の重複検知を防ぐ
        if image_hash == self._last_hash:
            return

        self._last_hash = image_hash
        detected_at = datetime.now()

        logger.info("Image detected")
        logger.info("  横幅: %d", image.width())
        logger.info("  縦幅: %d", image.height())
        logger.info("  検知時刻: %s", detected_at.strftime("%Y-%m-%d %H:%M:%S"))

        # 将来の保存機能で使えるよう、検知情報をまとめて渡す
        if self._on_image_detected is not None:
            detected = DetectedImage(
                image=image,
                width=image.width(),
                height=image.height(),
                detected_at=detected_at,
            )
            self._on_image_detected(detected)

    def _calc_image_hash(self, image: QImage) -> str:
        """画像データのハッシュ値を計算する（重複判定用）"""
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return hashlib.md5(buffer.data().data()).hexdigest()
