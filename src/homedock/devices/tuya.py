"""Transport to Tuya devices over the LAN (tinytuya), independent of any DPS mapping."""

from __future__ import annotations

import logging
import select
import time
from collections.abc import Callable
from typing import Any, Protocol

import tinytuya

from homedock.devices.base import DeviceError
from homedock.devices.spec import DeviceSpec, is_lan_address

DEFAULT_PROTOCOL_VERSION = "3.4"
# 3.2 is left out: tinytuya's constructor goes to the network to probe it.
SUPPORTED_VERSIONS = {"3.1": 3.1, "3.3": 3.3, "3.4": 3.4, "3.5": 3.5}
# A bulb on the LAN answers well within a second: an unplugged one should not keep a command
# (and the device's lane) waiting long. tinytuya uses the timeout for the TCP connect and for
# each answer. A failed connect is not retried, so the timeout must outlast Windows' own
# resends of a lost connection request (after 1 s and 3 s). A request timing out on an open
# socket is retried once on a new one; more retries would add tinytuya's 5 s pause between
# connect attempts (``set_socketRetryDelay``).
TIMEOUT = 3.5
RETRIES = 1
# Tuya devices drop idle connections; reopen instead of waiting for a dead socket to time out.
IDLE_TIMEOUT = 20.0
# Reading what the device sent unasked: the data is already there, so a short wait is plenty.
UNREAD_TIMEOUT = 0.5
MAX_UNREAD = 20  # messages read before a call, at most

# tinytuya DEBUG logs include the local key: never call tinytuya.set_debug().
logging.getLogger("tinytuya").setLevel(logging.INFO)


class TuyaLink(Protocol):
    """Raw DPS access to one device. Methods raise :class:`DeviceError` on failure."""

    def status(self) -> dict[str, Any]:
        """Return the reported DPS. May be a partial push of recently changed DPS."""
        ...

    def set_values(self, values: dict[str, Any]) -> dict[str, Any]:
        """Write several DPS at once; return whatever DPS the device echoed (maybe none)."""
        ...

    def close(self) -> None: ...


LinkFactory = Callable[[DeviceSpec], TuyaLink]


class TinyTuyaLink:
    """tinytuya-backed link with a lazily opened persistent socket.

    Protocol 3.4 negotiates a session key per TCP connection, so keeping the socket open
    cuts the latency of every command. After any error the socket is dropped and reopened
    on the next call, as it is after ``idle_timeout`` seconds without use. Never log the
    tinytuya device object: its repr includes the local key.

    tinytuya reads one message per call and does not match it to the request, while a write
    is answered by one status push per changed DPS: the extra pushes stay on the socket. So
    each call first reads, in order, every message waiting there and returns their DPS under
    its own answer; otherwise the next call would take an old message as its answer.
    """

    def __init__(
        self,
        spec: DeviceSpec,
        timeout: float = TIMEOUT,
        retries: int = RETRIES,
        idle_timeout: float = IDLE_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spec = spec
        self._timeout = timeout
        self._retries = retries
        self._idle_timeout = idle_timeout
        self._clock = clock
        self._device: Any = None
        self._last_used = 0.0

    def status(self) -> dict[str, Any]:
        return self._call(lambda device: device.status())

    def set_values(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._call(lambda device: self._set_multiple(device, values))

    @staticmethod
    def _set_multiple(device: Any, values: dict[str, Any]) -> object:
        response = device.set_multiple_values(values)
        # After one failed multi-DPS write tinytuya falls back to one DPS per command, 1 s
        # apart, for good. Our bulbs accept multi-DPS writes: undo that fallback.
        device.max_simultaneous_dps = 0
        return response

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None

    def _connect(self) -> Any:
        if self._device is not None and self._clock() - self._last_used > self._idle_timeout:
            self.close()
        if self._device is None:
            if not self._spec.ip:
                raise DeviceError("device has no IP address; a network scan is needed")
            if not is_lan_address(self._spec.ip):
                raise DeviceError("device IP is not a LAN address; a network scan is needed")
            version = SUPPORTED_VERSIONS.get(self._spec.version or DEFAULT_PROTOCOL_VERSION)
            if version is None:
                raise DeviceError(f"unsupported protocol version {self._spec.version!r}")
            try:
                device = tinytuya.Device(
                    self._spec.id, self._spec.ip, self._spec.local_key, version=version
                )
                device.set_socketTimeout(self._timeout)
                device.set_socketRetryLimit(self._retries)
                device.set_socketPersistent(True)
            except Exception as exc:  # library boundary: e.g. a key tinytuya cannot encode
                # The message may quote part of the local key: report only the type.
                raise DeviceError(f"cannot open the connection ({type(exc).__name__})") from None
            self._device = device
        return self._device

    def _call(self, operation: Callable[[Any], object]) -> dict[str, Any]:
        device = self._connect()
        try:
            unread = self._read_unread(device)
            if self._device is None:  # reading found the socket dead: open a new one
                device = self._connect()
            response = operation(device)
        except Exception as exc:  # library boundary: tinytuya may raise anything
            self.close()
            # The message may embed the IP or other local data: report only the type.
            raise DeviceError(f"communication failed ({type(exc).__name__})") from None
        self._last_used = self._clock()
        if isinstance(response, dict) and "Err" in response:
            self.close()
            raise DeviceError(f"Err {response.get('Err')}: {response.get('Error')}")
        return {**unread, **_dps(response)}

    def _read_unread(self, device: Any) -> dict[str, Any]:
        """The DPS of the messages waiting on the socket, oldest first (later ones win)."""
        unread: dict[str, Any] = {}
        device.set_socketTimeout(UNREAD_TIMEOUT)
        try:
            for _ in range(MAX_UNREAD):
                if not _has_unread(device):
                    break
                message = device.receive()
                if isinstance(message, dict) and "Err" in message:
                    self.close()  # e.g. the device closed the connection
                    break
                unread.update(_dps(message))
        except Exception:  # library boundary: a broken socket; the call gets a new one
            self.close()
        finally:
            device.set_socketTimeout(self._timeout)
        return unread


def connect_tinytuya(spec: DeviceSpec) -> TuyaLink:
    return TinyTuyaLink(spec)


def _dps(response: object) -> dict[str, Any]:
    if isinstance(response, dict) and isinstance(response.get("dps"), dict):
        return {str(k): v for k, v in response["dps"].items()}
    return {}


def _has_unread(device: Any) -> bool:
    """Whether the device's socket holds data nobody read yet (never waits)."""
    sock = getattr(device, "socket", None)
    if sock is None:
        return False
    try:
        readable, _, _ = select.select([sock], [], [], 0)
    except (OSError, ValueError):  # closed meanwhile
        return False
    return bool(readable)
