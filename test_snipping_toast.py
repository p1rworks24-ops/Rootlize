"""Snipping Tool toast suppressor — reference counting + restore."""

from __future__ import annotations

import sys

import pytest

from app.utils.snipping_toast import SnippingToastSuppressor


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")
def test_suppressor_restores_previous_enabled_value(monkeypatch):
    """enter/exit should write Enabled=0 then restore the prior value."""
    import winreg

    store: dict[str, int | None] = {}

    class FakeKey:
        def __init__(self, path: str):
            self.path = path

    def fake_create(root, path, reserved, access):
        assert root == winreg.HKEY_CURRENT_USER
        return FakeKey(path)

    def fake_query(key, name):
        if name != "Enabled":
            raise FileNotFoundError
        sender = key.path.rsplit("\\", 1)[-1]
        if sender not in store or store[sender] is None:
            raise FileNotFoundError
        return store[sender], winreg.REG_DWORD

    def fake_set(key, name, reserved, typ, value):
        assert name == "Enabled"
        sender = key.path.rsplit("\\", 1)[-1]
        store[sender] = int(value)

    def fake_delete(key, name):
        sender = key.path.rsplit("\\", 1)[-1]
        store.pop(sender, None)

    def fake_close(_key):
        return None

    monkeypatch.setattr(winreg, "CreateKeyEx", fake_create)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query)
    monkeypatch.setattr(winreg, "SetValueEx", fake_set)
    monkeypatch.setattr(winreg, "DeleteValue", fake_delete)
    monkeypatch.setattr(winreg, "CloseKey", fake_close)
    monkeypatch.setattr(
        "app.utils.snipping_toast.SnippingToastSuppressor._discover_screen_sketch_senders",
        staticmethod(lambda _winreg: set()),
    )

    sender = "Microsoft.ScreenSketch_8wekyb3d8bbwe!App"
    store[sender] = 1
    suppressor = SnippingToastSuppressor()
    suppressor.enter()
    assert store[sender] == 0
    suppressor.exit()
    assert store[sender] == 1


def test_suppressor_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    suppressor = SnippingToastSuppressor()
    suppressor.enter()
    suppressor.exit()
    assert suppressor._depth == 0
