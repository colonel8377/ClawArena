import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DEFAULT_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_root_logger = logging.getLogger()
if not _root_logger.handlers:
    logging.basicConfig(level=_DEFAULT_LEVEL, format=_DEFAULT_FORMAT)
else:
    _root_logger.setLevel(_DEFAULT_LEVEL)

logger = logging.getLogger("clawarena")


def debug(msg, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)


def info(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)


def warning(msg, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)


def error(msg, *args, **kwargs):
    logger.error(msg, *args, **kwargs)


def exception(msg, *args, **kwargs):
    logger.exception(msg, *args, **kwargs)
