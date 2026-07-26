import sys
from pathlib import Path

from loguru import logger

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure loguru sinks based on environment. Idempotent."""
    settings = get_settings()

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

    # Skip file logging in serverless environments (Vercel has a read-only
    # filesystem). Only write to disk when LOG_DIR is writable.
    log_dir = Path(settings.LOG_DIR)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app.log",
            level=settings.LOG_LEVEL,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
        )
    except OSError:
        pass  # Read-only filesystem (e.g. Vercel serverless) — stdout only


__all__ = ["logger", "configure_logging"]
