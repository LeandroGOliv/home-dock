import logging

import pytest

from homedock.storage.logs import LOG_FILE, setup_logging

FAKE_LOCAL = "a1b2c3d4e5f6a7b8"
DEVICE_ID = "bf0000000000000000aa"


@pytest.fixture
def logger():
    logger = logging.getLogger("homedock.test-logs")
    logger.propagate = False
    yield logger
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def read_logs(logs_dir):
    return "".join(p.read_text(encoding="utf-8") for p in sorted(logs_dir.iterdir()))


def test_logs_go_to_the_logs_folder(tmp_path, logger):
    logs_dir = tmp_path / "HomeDock" / "logs"
    setup_logging(logs_dir, logger=logger)
    logger.info("Lâmpada ligada")
    assert [p.name for p in logs_dir.iterdir()] == [LOG_FILE]
    line = read_logs(logs_dir)
    assert "INFO" in line
    assert "homedock.test-logs" in line
    assert "Lâmpada ligada" in line


def test_the_logs_never_contain_the_local_key_in_plain_text(tmp_path, logger):
    log_filter = setup_logging(tmp_path, logger=logger)
    log_filter.add(FAKE_LOCAL, DEVICE_ID)

    logger.info("connecting %s with key %s", DEVICE_ID, FAKE_LOCAL)
    logger.warning(f"inline key {FAKE_LOCAL}")
    try:
        raise ValueError(f"handshake failed for key {FAKE_LOCAL} at 192.0.2.10")
    except ValueError:
        logger.exception("device error")

    text = read_logs(tmp_path)
    assert FAKE_LOCAL not in text
    assert DEVICE_ID not in text
    assert "192.0.2.10" not in text
    assert "a1…b8" in text
    assert "ValueError" in text


def test_records_below_the_level_are_dropped(tmp_path, logger):
    setup_logging(tmp_path, logger=logger, level=logging.WARNING)
    logger.info("chatty")
    logger.warning("important")
    text = read_logs(tmp_path)
    assert "chatty" not in text
    assert "important" in text


def test_the_log_file_rotates(tmp_path, logger):
    setup_logging(tmp_path, logger=logger, max_bytes=200, backup_count=2)
    for n in range(50):
        logger.info("line %d %s", n, "x" * 40)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        LOG_FILE,
        f"{LOG_FILE}.1",
        f"{LOG_FILE}.2",
    ]
