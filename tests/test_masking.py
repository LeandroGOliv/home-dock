import logging

import pytest

from homedock.masking import RedactingFilter, mask, redact


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bf1a2b3c4d5e6f7a8b9c", "bf…9c"),
        ("192.0.2.10", "19…10"),
        ("abcde", "ab…de"),
        ("abcd", "…"),
        ("", "(empty)"),
        (None, "(empty)"),
    ],
)
def test_mask_keeps_only_the_edges(value, expected):
    assert mask(value) == expected


def test_redact_masks_every_occurrence_of_each_secret():
    text = "dev 0123456789abcdef at 192.0.2.10 (again 0123456789abcdef)"
    assert redact(text, ["0123456789abcdef", "192.0.2.10"]) == "dev 01…ef at 19…10 (again 01…ef)"


def test_redact_masks_longer_secrets_first():
    # "192.0.2.1" is a prefix of "192.0.2.10": the longer one must win.
    assert redact("ip 192.0.2.10", ["192.0.2.1", "192.0.2.10"]) == "ip 19…10"


def test_redact_ignores_empty_secrets():
    assert redact("nothing to hide", ["", None]) == "nothing to hide"


def test_redacting_filter_masks_message_and_arguments():
    record = logging.LogRecord(
        "homedock", logging.INFO, __file__, 1, "key %s for %s", ("a1b2c3d4e5f6a7b8", "lamp"), None
    )
    log_filter = RedactingFilter()
    log_filter.add("a1b2c3d4e5f6a7b8")

    assert log_filter.filter(record) is True
    assert record.getMessage() == "key a1…b8 for lamp"
