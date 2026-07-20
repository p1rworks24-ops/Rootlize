import logging


def setup_logger(name: str | None = None) -> logging.Logger:
    """アプリ全体で使うロガーを設定する"""
    if name is None:
        from app.branding import APP_LOGGER_NAME

        name = APP_LOGGER_NAME

    logger = logging.getLogger(name)

    # 既に設定済みならそのまま返す（二重設定を防ぐ）
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # コンソール出力
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
