"""Single-instance guard: a named Windows mutex, so a second launch opens no second tray.

The mutex is a kernel object: Windows releases it when the process exits, even after a
crash, so a stale lock can never block the next start.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import TracebackType

DEFAULT_NAME = "Local\\HomeDock.SingleInstance"  # "Local\": per user session
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183


def _kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class SingleInstance:
    """Holds the named mutex until :meth:`release` (or the end of a ``with`` block)."""

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle

    @classmethod
    def acquire(cls, name: str = DEFAULT_NAME) -> SingleInstance | None:
        """The lock, or ``None`` when another instance holds it. Raises ``OSError``."""
        kernel32 = _kernel32()
        handle = kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle and error == ERROR_ACCESS_DENIED:
            return None  # held by an instance running with other rights (e.g. elevated)
        if not handle:
            raise ctypes.WinError(error)
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return cls(handle)

    def release(self) -> None:
        if self._handle is not None:
            _kernel32().CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()
