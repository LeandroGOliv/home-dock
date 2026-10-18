"""Executors and timers for deterministic tests of code that runs work on workers."""

from collections import deque
from concurrent.futures import Executor, Future


class ManualExecutor(Executor):
    """Queues tasks until ``run_all()``: lets a test decide when "worker" code runs."""

    def __init__(self) -> None:
        self.tasks: deque = deque()

    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        self.tasks.append((future, fn, args, kwargs))
        return future

    def run_all(self) -> None:
        while self.tasks:
            future, fn, args, kwargs = self.tasks.popleft()
            future.set_running_or_notify_cancel()
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeTimers:
    """Collects the scheduled callbacks; ``fire()`` runs the ones still pending."""

    def __init__(self) -> None:
        self.started: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.started.append(timer)
        return timer

    @property
    def pending(self) -> list[FakeTimer]:
        return [t for t in self.started if not t.cancelled]

    @property
    def delays(self) -> list[float]:
        return [t.delay for t in self.pending]

    def fire(self) -> None:
        due = self.pending
        for timer in due:
            timer.cancelled = True  # a timer fires once
        for timer in due:
            timer.callback()
