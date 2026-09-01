"""Stable local installation identity. Logout does not rotate this id.

The UUID in device.json is the Prototype installation identity. It is random
and opaque: not a hardware serial, MAC, or Windows username fingerprint.
"""

from __future__ import annotations

import json
import socket
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.paths import ensure_dir, get_local_app_data_dir
from app.utils.logger import setup_logger

logger = setup_logger()
DEVICE_FILE = "device.json"


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    device_name: str
    platform: str

    def registration_payload(self, user_id: str) -> dict[str, str]:
        """Shape for a future backend register call. Not sent unless asked."""
        return {
            "device_id": self.device_id,
            "user_id": user_id,
            "device_name": self.device_name,
            "platform": self.platform,
        }


class DeviceService:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_local_app_data_dir() / DEVICE_FILE)

    def get_or_create(self) -> DeviceRecord:
        existing = self._read()
        if existing is not None:
            return existing
        record = DeviceRecord(
            device_id=str(uuid.uuid4()),
            device_name=socket.gethostname() or "Capixe PC",
            platform=sys.platform,
        )
        self._write(record)
        logger.info("Created local device id.")
        return record

    def current(self) -> DeviceRecord | None:
        return self._read()

    def _read(self) -> DeviceRecord | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        device_id = str(data.get("device_id") or "").strip()
        if not device_id:
            return None
        return DeviceRecord(
            device_id=device_id,
            device_name=str(data.get("device_name") or socket.gethostname() or "Capixe PC"),
            platform=str(data.get("platform") or sys.platform),
        )

    def _write(self, record: DeviceRecord) -> None:
        ensure_dir(self._path.parent)
        payload = {
            "device_id": record.device_id,
            "device_name": record.device_name,
            "platform": record.platform,
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
