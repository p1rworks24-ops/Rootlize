from dataclasses import dataclass
from datetime import datetime

from PySide6.QtGui import QImage


@dataclass
class DetectedImage:
    """検知した画像の情報（将来の保存機能で使用）"""

    image: QImage
    width: int
    height: int
    detected_at: datetime
