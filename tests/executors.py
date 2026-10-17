"""Executors for deterministic tests of code that runs work on workers."""

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
