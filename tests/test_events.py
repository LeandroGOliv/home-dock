import logging

from homedock.core.events import Event


def test_emit_calls_every_listener_in_connection_order():
    calls = []
    event: Event[str, int] = Event()
    event.connect(lambda name, value: calls.append(("first", name, value)))
    event.connect(lambda name, value: calls.append(("second", name, value)))
    event.emit("dev-a", 1)
    assert calls == [("first", "dev-a", 1), ("second", "dev-a", 1)]


def test_disconnected_listeners_are_not_called():
    calls = []
    event: Event[int] = Event()
    listener = calls.append
    event.connect(listener)
    event.disconnect(listener)
    event.emit(1)
    assert calls == []


def test_a_failing_listener_is_logged_and_does_not_stop_the_others(caplog):
    calls = []
    event: Event[int] = Event()

    def broken(_value: int) -> None:
        raise RuntimeError("boom")

    event.connect(broken)
    event.connect(calls.append)
    with caplog.at_level(logging.ERROR):
        event.emit(7)
    assert calls == [7]
    assert "listener failed" in caplog.text
