import sys
from pathlib import Path

from loguru import logger

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure loguru sinks based on environment. Idempotent."""
    settings = get_settings()

    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    is_production = settings.APP_ENV == "production"

    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        colorize=not is_production,
        serialize=is_production,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
    )

    logger.add(
        log_dir / "app.log",
        level=settings.LOG_LEVEL,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
    )


__all__ = ["logger", "configure_logging"]
