"""Helpers for UI tests that drive the control service through a manual executor."""

from PySide6.QtWidgets import QApplication

from executors import ManualExecutor


def settle(executor: ManualExecutor) -> None:
    """Run the queued device I/O, then deliver what it queued for the UI thread."""
    executor.run_all()
    QApplication.processEvents()
