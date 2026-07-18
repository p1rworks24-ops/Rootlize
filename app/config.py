import json
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger()

# デフォルト設定（config.json が無いときに使う）
DEFAULT_CONFIG = {
    "screenshot_dir": "screenshots",
    "current_folder": "Capture",
    # Capture destination (independent from Images viewing folder)
    "save_folder": "Capture",
    "window_width": 800,
    "window_height": 600,
    "window_title": "Screenshot Manager",
    "clipboard_check_interval_ms": 500,
    "images_folder_tree_expanded": True,
    "filename_template": "{date}_{time}",
    "capture_tags": [],
    "capture_mode": "region",
    "home_stats_mode": "folder",
}


def get_config_path() -> Path:
    """プロジェクトルートの config.json のパスを返す"""
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "config.json"


def load_config() -> dict:
    """
    config.json を読み込む。
    ファイルが無ければデフォルトを書き出して返す。
    """
    config_path = get_config_path()

    if not config_path.exists():
        logger.info("config.json が見つかりません。デフォルト設定を作成します。")
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # 既存の設定ファイルに新しいデフォルト設定項目がない場合は追加する
        updated = False
        for key, val in DEFAULT_CONFIG.items():
            if key not in config:
                # save_folder must mirror the user's viewing folder on first migrate,
                # not the generic DEFAULT_CONFIG value (which may differ).
                if key == "save_folder":
                    continue
                config[key] = val
                updated = True

        if not str(config.get("save_folder") or "").strip():
            legacy_view = (
                (config.get("current_folder") or "").strip()
                or (config.get("current_project") or "").strip()
                or DEFAULT_CONFIG["save_folder"]
            )
            config["save_folder"] = legacy_view
            updated = True

        if updated:
            logger.info("config.json に新しい設定項目を追加しました。")
            save_config(config)

        logger.info("config.json を読み込みました。")
        return config

    except json.JSONDecodeError as e:
        logger.error("config.json の形式が不正です: %s", e)
        logger.warning("デフォルト設定を使用します。")
        return DEFAULT_CONFIG.copy()

    except OSError as e:
        logger.error("config.json の読み込みに失敗しました: %s", e)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """設定を config.json に保存する"""
    config_path = get_config_path()

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("config.json を保存しました: %s", config_path)

    except OSError as e:
        logger.error("config.json の保存に失敗しました: %s", e)
        raise
