import logging
import sys

import pytest

from homedock import masking
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


def make_record(msg, args=(), exc_info=None):
    return logging.LogRecord("homedock", logging.ERROR, __file__, 1, msg, args, exc_info)


def test_redacting_filter_masks_any_ipv4_address():
    # IPs found by a LAN scan are not known in advance.
    record = make_record("found %s and %s", ("192.0.2.33", "198.51.100.7"))
    RedactingFilter().filter(record)
    assert record.getMessage() == "found 19…33 and 19….7"


def test_redacting_filter_keeps_version_numbers():
    record = make_record("protocol %s, app %s", ("3.4", "0.1.0"))
    RedactingFilter().filter(record)
    assert record.getMessage() == "protocol 3.4, app 0.1.0"


def test_redacting_filter_masks_the_exception_text():
    try:
        raise RuntimeError("bad key a1b2c3d4e5f6a7b8 from 192.0.2.10")
    except RuntimeError:
        record = make_record("failed", exc_info=sys.exc_info())
    log_filter = RedactingFilter()
    log_filter.add("a1b2c3d4e5f6a7b8")

    log_filter.filter(record)
    text = logging.Formatter().format(record)

    assert "RuntimeError: bad key a1…b8 from 19…10" in text
    assert "a1b2c3d4e5f6a7b8" not in text
    assert "192.0.2.10" not in text


def test_redacting_filter_masks_the_stack_info():
    record = make_record("here")
    record.stack_info = "Stack (most recent call last):\n  key a1b2c3d4e5f6a7b8"
    log_filter = RedactingFilter()
    log_filter.add("a1b2c3d4e5f6a7b8")
    log_filter.filter(record)
    assert "a1b2c3d4e5f6a7b8" not in record.stack_info


@pytest.mark.parametrize("suffix", [".", "...", ":6668", ",", ")"])
def test_redacting_filter_masks_ipv4_followed_by_punctuation(suffix):
    assert RedactingFilter().redact(f"timeout at 192.0.2.10{suffix}") == f"timeout at 19…10{suffix}"


def test_redacting_filter_ignores_longer_dotted_numbers():
    assert RedactingFilter().redact("build 1.2.3.4.5") == "build 1.2.3.4.5"


def test_redact_is_case_insensitive():
    assert redact("mac 00:00:00:AA:BB:20", ["00:00:00:aa:bb:20"]) == "mac 00…20"
    assert redact("id BF0000AA", ["bf0000aa"]) == "id BF…AA"


def test_secrets_added_while_a_record_is_redacted_do_not_break_it(monkeypatch):
    # The reload thread adds secrets while I/O workers log: simulate that interleaving.
    log_filter = RedactingFilter()
    log_filter.add("a1b2c3d4e5f6a7b8")
    real_redact = masking.redact

    def redact_while_adding(text, secrets):
        for _ in secrets:
            log_filter.add("bf0000000000000000aa")
        return real_redact(text, secrets)

    monkeypatch.setattr(masking, "redact", redact_while_adding)
    record = make_record("key %s", ("a1b2c3d4e5f6a7b8",))

    assert log_filter.filter(record) is True
    assert record.getMessage() == "key a1…b8"
    assert log_filter.redact("id bf0000000000000000aa") == "id bf…aa"
