"""Performance probe of HomeDock (issue #35): start-up, idle cost, flyout, painting, drags.

Four measurements, each a sub-command; none prints a key, a device ID or an IP:

- ``exe`` starts ``dist\\HomeDock\\HomeDock.exe`` (no HomeDock may be running: a second one
  exits at once) and times it until its tray icon exists, a few times; the last run then sits idle
  in the tray, flyout closed, while its memory, CPU, threads and sockets are sampled. It is
  the real app with your ``%APPDATA%\\HomeDock``: at start-up it reads the state of the real
  devices (no command is sent). The probe kills it at the end (its tray icon may linger
  until the pointer passes over it).
- ``flyout`` opens and closes the flyout in this process over fake bulbs and times each
  opening until it is painted; ``--profile`` prints a cProfile of the openings.
- ``paint`` times the ``paintEvent`` of the custom QPainter widgets (``--profile`` too).
- ``drag`` drags the temperature arc, the hue ring and the brightness slider at 60 Hz over
  fake bulbs answering after ``--latency`` seconds, like a real bulb, and counts the
  commands each bulb gets: the control service must keep only the latest value.

Usage::

    uv run pyinstaller packaging/HomeDock.spec            # build the exe first
    uv run python scripts/perf_probe.py exe --minutes 2
    uv run python scripts/perf_probe.py flyout --profile
    uv run python scripts/perf_probe.py paint
    uv run python scripts/perf_probe.py drag --latency 0.1
"""

from __future__ import annotations

import argparse
import cProfile
import ctypes
import io
import pstats
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = ROOT / "dist" / "HomeDock" / "HomeDock.exe"
TRAY_WINDOW = "QTrayIconMessageWindow"  # the hidden window Qt creates for a tray icon
START_TIMEOUT = 60.0  # seconds
FRAME = 1 / 60  # seconds between the pointer moves of a drag


class ProbeError(RuntimeError):
    pass


# --- helpers ------------------------------------------------------------------------------


def percentile(values: Sequence[float], fraction: float) -> float:
    """The value below which ``fraction`` of ``values`` lie (nearest rank)."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, round(fraction * len(ordered) + 0.5 - 1e-9))
    return ordered[min(rank, len(ordered)) - 1]


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def mb(size: float) -> str:
    return f"{size / 2**20:.1f} MB"


def timings(values: Sequence[float]) -> str:
    """Median, 95th percentile and maximum of durations in seconds."""
    return (
        f"median {ms(statistics.median(values))} · p95 {ms(percentile(values, 0.95))}"
        f" · max {ms(max(values))}"
    )


def profile_report(profile: cProfile.Profile, lines: int) -> str:
    """The ``lines`` costliest functions, by cumulative time, without the folders."""
    out = io.StringIO()
    stats = pstats.Stats(profile, stream=out)
    stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE).print_stats(lines)
    return out.getvalue().strip()


# --- exe: start-up and idle cost ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sample:
    """One look at the exe's processes: the app (and a one-file build's launcher above it)."""

    elapsed: float  # seconds since the idle period started
    cpu: float  # CPU seconds used by every process of the exe so far
    working_set: int  # bytes, every process
    app_working_set: int
    private: int  # private bytes, every process
    threads: int  # every process
    sockets: Counter[str]


@dataclass(frozen=True, slots=True)
class IdleReport:
    seconds: float
    cpu_seconds: float
    cpu_percent: float  # of the whole machine, like Task Manager
    peak_cpu_percent: float  # in the busiest interval between two samples
    working_set: int  # last sample
    app_working_set: int
    peak_working_set: int
    private: int
    threads: int
    sockets: Counter[str]


def socket_kinds(connections: Iterable[Any]) -> Counter[str]:
    """How many sockets of each kind (``TCP ESTABLISHED``, ``UDP``…): counts only, never
    the addresses."""
    kinds: Counter[str] = Counter()
    for connection in connections:
        if connection.type == 1:  # socket.SOCK_STREAM
            kinds[f"TCP {connection.status}"] += 1
        else:
            kinds["UDP"] += 1
    return kinds


def summarize(samples: Sequence[Sample], cpu_count: int) -> IdleReport:
    """The idle cost over ``samples`` (at least two, in time order)."""
    if len(samples) < 2:
        raise ValueError("at least two samples are needed")
    first, last = samples[0], samples[-1]
    seconds = last.elapsed - first.elapsed
    cpu_seconds = last.cpu - first.cpu
    peaks = [
        (b.cpu - a.cpu) / (b.elapsed - a.elapsed)
        for a, b in pairwise(samples)
        if b.elapsed > a.elapsed
    ]
    return IdleReport(
        seconds=seconds,
        cpu_seconds=cpu_seconds,
        cpu_percent=100 * cpu_seconds / seconds / cpu_count,
        peak_cpu_percent=100 * max(peaks, default=0.0) / cpu_count,
        working_set=last.working_set,
        app_working_set=last.app_working_set,
        peak_working_set=max(s.working_set for s in samples),
        private=last.private,
        threads=last.threads,
        sockets=last.sockets,
    )


def tray_window_pids() -> set[int]:
    """The processes owning a Qt tray icon window."""
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    pids: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd: int, _param: int) -> bool:
        title = ctypes.create_unicode_buffer(len(TRAY_WINDOW) + 2)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == TRAY_WINDOW:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(pid.value)
        return True

    user32.EnumWindows(visit, 0)
    return pids


def running_homedocks(exe_name: str) -> list[int]:
    import psutil

    return [p.pid for p in psutil.process_iter(["name"]) if p.info["name"] == exe_name]


class ExeRun:
    """One launch of the exe: the app (a one-file build starts it from a launcher)."""

    def __init__(self, exe: Path) -> None:
        import psutil

        self.started = time.perf_counter()
        popen = subprocess.Popen(
            [str(exe)], cwd=exe.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.root = psutil.Process(popen.pid)
        self._popen = popen

    def processes(self) -> list[Any]:
        import psutil

        try:
            return [self.root, *self.root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return []

    def wait_for_tray(self, timeout: float = START_TIMEOUT) -> float:
        """Seconds from the launch until the tray icon window exists."""
        while time.perf_counter() - self.started < timeout:
            pids = {p.pid for p in self.processes()}
            if pids & tray_window_pids():
                return time.perf_counter() - self.started
            if self._popen.poll() is not None:
                raise ProbeError("HomeDock exited at once: is another HomeDock running?")
            time.sleep(0.01)
        raise ProbeError(f"no tray icon after {timeout:.0f} s")

    def sample(self, elapsed: float) -> Sample:
        import psutil

        cpu = working_set = app_working_set = private = threads = 0
        sockets: Counter[str] = Counter()
        processes = self.processes()
        app = processes[-1].pid if processes else None  # a launcher's child, if any
        for process in processes:
            try:
                with process.oneshot():
                    times = process.cpu_times()
                    memory = process.memory_info()
                    cpu += times.user + times.system
                    working_set += memory.rss
                    private += memory.private
                    threads += process.num_threads()
                    sockets += socket_kinds(process.net_connections(kind="inet"))
                    if process.pid == app:
                        app_working_set = memory.rss
            except psutil.NoSuchProcess:
                continue
        return Sample(elapsed, cpu, working_set, app_working_set, private, threads, sockets)

    def stop(self) -> None:
        """Kill the app first: a one-file launcher then removes the folder it unpacked into."""
        import psutil

        children = self.root.children(recursive=True) if self.root.is_running() else []
        for child in children:
            child.kill()
        psutil.wait_procs(children, timeout=10)
        try:
            self.root.wait(10)
        except psutil.TimeoutExpired:
            self.root.kill()
            self.root.wait(10)


def probe_exe(exe: Path, runs: int, minutes: float, interval: float, warmup: float) -> None:
    import psutil

    if not exe.is_file():
        raise ProbeError(f"{exe.name} not found: build it first (packaging/HomeDock.spec)")
    if running_homedocks(exe.name):
        raise ProbeError(f"{exe.name} is running: quit it first (tray menu → Sair)")
    print(f"{exe.name}  {mb(exe.stat().st_size)}")
    starts: list[float] = []
    for number in range(1, runs + 1):
        run = ExeRun(exe)
        try:
            starts.append(run.wait_for_tray())
            print(f"run {number}: tray icon after {starts[-1]:.2f} s", flush=True)
            if number == runs:
                report = _idle(run, minutes * 60, interval, warmup, psutil.cpu_count() or 1)
        finally:
            run.stop()
    print(f"start-up (launch → tray icon): median {statistics.median(starts):.2f} s")
    _print_idle(report)


def _idle(run: ExeRun, seconds: float, interval: float, warmup: float, cpus: int) -> IdleReport:
    print(f"warming up for {warmup:.0f} s (start-up reads), then idle for {seconds:.0f} s…")
    time.sleep(warmup)
    begin = time.perf_counter()
    samples = [run.sample(0.0)]
    while samples[-1].elapsed < seconds:
        time.sleep(min(interval, seconds - samples[-1].elapsed))
        samples.append(run.sample(time.perf_counter() - begin))
    return summarize(samples, cpus)


def _print_idle(report: IdleReport) -> None:
    sockets = " · ".join(f"{kind} {n}" for kind, n in sorted(report.sockets.items())) or "none"
    print(f"idle in the tray for {report.seconds:.0f} s, flyout closed:")
    print(
        f"  CPU            {report.cpu_seconds:.2f} s used = {report.cpu_percent:.2f} % of the"
        f" machine (busiest sample {report.peak_cpu_percent:.2f} %)"
    )
    print(
        f"  working set    app {mb(report.app_working_set)} · all processes"
        f" {mb(report.working_set)} (peak {mb(report.peak_working_set)})"
    )
    print(f"  private bytes  all processes {mb(report.private)}")
    print(f"  threads        {report.threads}")
    print(f"  sockets        {sockets}")


# --- in-process measurements over fake bulbs ----------------------------------------------


def _fake_bulb_class() -> type:
    from homedock.devices.fake import FakeDevice

    @dataclass
    class SlowBulb(FakeDevice):
        """A fake bulb answering after ``latency`` seconds; ``applied`` lists its writes."""

        latency: float = 0.0
        written: list[float] = field(default_factory=list)  # when each write ended

        def read_state(self):  # type: ignore[no-untyped-def]
            time.sleep(self.latency)
            return super().read_state()

        def apply(self, changes):  # type: ignore[no-untyped-def]
            time.sleep(self.latency)
            state = super().apply(changes)
            self.written.append(time.perf_counter())
            return state

    return SlowBulb


def fake_bulbs(count: int, latency: float) -> list[Any]:
    from homedock.devices import Capability, DeviceState, DeviceType, WorkMode

    slow_bulb = _fake_bulb_class()
    state = DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80, color_temperature=40)
    capabilities = frozenset(Capability)
    return [
        slow_bulb(
            f"bulb-{n}", f"Bulb {n}", DeviceType.RGB_BULB, capabilities, state, latency=latency
        )
        for n in range(1, count + 1)
    ]


@dataclass
class Bench:
    """A flyout over fake bulbs, with one group and a few scenes, persisting nothing."""

    app: Any
    service: Any
    flyout: Any
    bulbs: list[Any]

    @classmethod
    def build(cls, bulbs: int, latency: float, scenes: int = 4) -> Bench:
        from PySide6.QtWidgets import QApplication

        from homedock.core import ControlService, Group, GroupBook, Scene
        from homedock.ui.flyout import Flyout

        app = QApplication.instance() or QApplication(sys.argv[:1])
        devices = fake_bulbs(bulbs, latency)
        group = Group("group-1", "Sala", tuple(d.id for d in devices[:2]))
        service = ControlService(devices, GroupBook([group]))
        saved = [
            Scene(f"scene-{n}", f"Cena {n}", {d.id: d.state for d in devices})
            for n in range(1, scenes + 1)
        ]
        flyout = Flyout(
            service,
            names=dict,
            last_target=lambda: None,
            set_last_target=lambda _target: None,
            scenes=lambda: saved,
            save_scenes=lambda _scenes: None,
            save_names=lambda _names: None,
            save_groups=lambda _groups: None,
            reload_devices=Future,
        )
        return cls(app, service, flyout, devices)

    def close(self) -> None:
        self.flyout.shutdown()
        self.flyout.close()
        self.service.shutdown()

    def wait(self, seconds: float) -> None:
        """Run the event loop for ``seconds`` (device answers reach the UI)."""
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.app.processEvents()
            time.sleep(0.002)

    def settle(self, timeout: float = 10.0) -> None:
        """Run the event loop until the service has no I/O running or queued (also a write
        waiting for its throttle) and the answers reached the UI."""
        end = time.perf_counter() + timeout
        self.wait(0.05)
        lanes = self.service._lanes  # a dev probe may look inside: no public "idle" query
        while any(lane.busy for lane in lanes.values()) and time.perf_counter() < end:
            self.wait(0.01)
        self.wait(0.05)


def time_open(bench: Bench) -> tuple[float, float]:
    """Seconds spent in ``Flyout.open()`` and from the call until the flyout is painted."""
    from PySide6.QtCore import QEvent, QObject

    flyout = bench.flyout
    painted: list[float] = []

    class PaintWatch(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint and watched is flyout:
                painted.append(time.perf_counter())
            return False

    watch = PaintWatch()
    flyout.installEventFilter(watch)
    try:
        start = time.perf_counter()
        flyout.open()
        opened = time.perf_counter()
        while not painted and time.perf_counter() - start < 5:
            bench.app.processEvents()  # a window paints its children with itself
        shown = time.perf_counter()
    finally:
        flyout.removeEventFilter(watch)
    if not painted:
        raise ProbeError("the flyout was never painted")
    return opened - start, shown - start


def probe_flyout(opens: int, bulbs: int, latency: float, profile: int) -> None:
    bench = Bench.build(bulbs, latency)
    try:
        bench.settle()
        calls: list[float] = []
        shown: list[float] = []
        profiler = cProfile.Profile()
        for number in range(opens + 1):
            if number > 0 and profile:
                profiler.enable()
            call, paint = time_open(bench)
            if number > 0 and profile:
                profiler.disable()
            if number == 0:
                print(f"first opening: open() {ms(call)} · painted after {ms(paint)}")
            else:
                calls.append(call)
                shown.append(paint)
            bench.settle()  # the reads of the opening answer
            bench.flyout.hide()
            bench.wait(0.02)
        print(f"next {opens} openings, {bulbs} bulbs answering in {ms(latency)}:")
        print(f"  open()           {timings(calls)}")
        print(f"  until painted    {timings(shown)}")
        if profile:
            print(profile_report(profiler, profile))
    finally:
        bench.close()


def probe_paint(frames: int, profile: int) -> None:
    from homedock.devices import WorkMode

    bench = Bench.build(2, 0.0)
    try:
        bench.flyout.open()
        bench.settle()
        panel = bench.flyout.main.panel
        widgets: list[tuple[str, Any, Callable[[], None]]] = [
            ("temperature arc", panel.arc, lambda: None),
            ("hue ring", panel.ring, lambda: panel._show_mode(WorkMode.COLOR)),
            ("brightness slider", panel.brightness.slider, lambda: None),
            ("power button", bench.flyout.main.power_button, lambda: None),
            ("whole flyout", bench.flyout, lambda: None),
        ]
        print(f"paintEvent, {frames} repaints each (a frame at 60 fps has 16.7 ms):")
        for name, widget, prepare in widgets:
            prepare()
            bench.wait(0.05)
            durations: list[float] = []
            profiler = cProfile.Profile()
            for _ in range(frames):
                if profile:
                    profiler.enable()
                start = time.perf_counter()
                widget.repaint()
                durations.append(time.perf_counter() - start)
                if profile:
                    profiler.disable()
            print(f"  {name:<18} {timings(durations)}")
            if profile:
                print(profile_report(profiler, profile))
    finally:
        bench.close()


@dataclass(frozen=True, slots=True)
class DragReport:
    control: str
    moves: int  # values the control emitted
    frames: list[float]  # seconds the UI thread spent on each pointer move, paint included
    writes: list[int]  # per bulb
    settled: float  # seconds from the release until every bulb ended its last write
    reached: bool  # every bulb ends with the last value


def drag(
    bench: Bench,
    control: str,
    widget: Any,
    points: Sequence[Any],
    value: Callable[[Any], int | None],
) -> DragReport:
    """Press on ``points[0]``, move through the rest one per frame, release on the last."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    left = Qt.MouseButton.LeftButton

    def send(kind: QEvent.Type, point: Any, button: Qt.MouseButton) -> None:
        local = QPointF(point)
        event = QMouseEvent(
            kind, local, widget.mapToGlobal(local), button, left, Qt.KeyboardModifier.NoModifier
        )
        bench.app.sendEvent(widget, event)

    moves = Counter[str]()
    widget.moved.connect(lambda _value: moves.update(["moved"]))
    before = [len(b.applied) for b in bench.bulbs]
    frames: list[float] = []
    send(QEvent.Type.MouseButtonPress, points[0], left)
    tick = time.perf_counter()
    for point in points[1:]:
        tick += FRAME
        start = time.perf_counter()
        send(QEvent.Type.MouseMove, point, Qt.MouseButton.NoButton)
        bench.app.processEvents()  # the repaint and the answers to earlier steps
        frames.append(time.perf_counter() - start)
        while time.perf_counter() < tick:
            bench.app.processEvents()
            time.sleep(0.001)
    send(QEvent.Type.MouseButtonRelease, points[-1], left)
    released = time.perf_counter()
    bench.settle()
    last_write = max((b.written[-1] for b in bench.bulbs if b.written), default=released)
    final = widget.value()
    return DragReport(
        control=control,
        moves=moves["moved"],
        frames=frames,
        writes=[len(b.applied) - n for b, n in zip(bench.bulbs, before, strict=True)],
        settled=max(last_write - released, 0.0),
        reached=all(value(b.state) == final for b in bench.bulbs),
    )


def probe_drag(seconds: float, bulbs: int, latency: float) -> list[DragReport]:
    from PySide6.QtCore import QPoint

    from homedock.devices import DeviceState, WorkMode
    from homedock.ui import theme
    from homedock.ui.dial_math import polar, temperature_to_angle

    bench = Bench.build(bulbs, latency)
    steps = max(round(seconds / FRAME), 2)
    reports: list[DragReport] = []
    try:
        bench.flyout.open()
        bench.settle()
        panel = bench.flyout.main.panel
        radius = (theme.DIAL_SIZE - theme.DIAL_BAND) / 2

        def around(dial: Any, start: float, end: float) -> list[QPoint]:
            centre = dial.width() / 2
            return [
                QPoint(*(round(c) for c in polar(centre, centre, radius, angle)))
                for angle in (start + (end - start) * i / steps for i in range(steps + 1))
            ]

        def across(slider: Any) -> list[QPoint]:
            y = slider.height() // 2
            return [QPoint(round(slider.width() * i / steps), y) for i in range(steps + 1)]

        warm, cold = temperature_to_angle(0), temperature_to_angle(100)
        arc = around(panel.arc, warm, cold + 360 if cold < warm else cold)  # not the opening
        reports.append(drag(bench, "temperature arc", panel.arc, arc, _get("color_temperature")))
        colour = DeviceState(work_mode=WorkMode.COLOR)
        bench.service.send(bench.flyout.main.target, colour).result()
        bench.settle()
        ring = around(panel.ring, 0, 359)
        reports.append(drag(bench, "hue ring", panel.ring, ring, _get("color_hsv", "hue")))
        slider = panel.brightness.slider
        reports.append(drag(bench, "brightness slider", slider, across(slider), _get("brightness")))
    finally:
        bench.close()
    print(f"drags of {seconds:.1f} s at 60 Hz over {bulbs} bulbs answering in {ms(latency)}:")
    for report in reports:
        writes = " / ".join(str(n) for n in report.writes)
        print(
            f"  {report.control:<18} {report.moves} values → writes per bulb {writes}"
            f" · last value {'reached' if report.reached else 'NOT reached'}"
            f" {ms(report.settled)} after the release"
        )
        print(f"  {'':<18} UI per move: {timings(report.frames)}")
    return reports


def _get(capability: str, part: str | None = None) -> Callable[[Any], int | None]:
    def value(state: Any) -> int | None:
        found = getattr(state, capability)
        return getattr(found, part) if part and found is not None else found

    return value


# --- command line -------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    exe = commands.add_parser("exe", help="start-up time and idle cost of HomeDock.exe")
    exe.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    exe.add_argument("--runs", type=int, default=3, help="launches timed (default 3)")
    exe.add_argument("--minutes", type=float, default=2.0, help="idle period (default 2)")
    exe.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    exe.add_argument("--warmup", type=float, default=15.0, help="seconds before sampling")

    flyout = commands.add_parser("flyout", help="opening time of the flyout (fake bulbs)")
    flyout.add_argument("--opens", type=int, default=30)
    flyout.add_argument("--bulbs", type=int, default=2)
    flyout.add_argument("--latency", type=float, default=0.1, help="seconds per bulb answer")
    flyout.add_argument("--profile", type=int, nargs="?", const=25, default=0, metavar="LINES")

    paint = commands.add_parser("paint", help="paintEvent cost of the custom widgets")
    paint.add_argument("--frames", type=int, default=200)
    paint.add_argument("--profile", type=int, nargs="?", const=15, default=0, metavar="LINES")

    drags = commands.add_parser("drag", help="commands sent while dragging (fake bulbs)")
    drags.add_argument("--seconds", type=float, default=2.0, help="length of each drag")
    drags.add_argument("--bulbs", type=int, default=2)
    drags.add_argument("--latency", type=float, default=0.1, help="seconds per bulb answer")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.command == "exe":
            probe_exe(args.exe, args.runs, args.minutes, args.interval, args.warmup)
        elif args.command == "flyout":
            probe_flyout(args.opens, args.bulbs, args.latency, args.profile)
        elif args.command == "paint":
            probe_paint(args.frames, args.profile)
        else:
            probe_drag(args.seconds, args.bulbs, args.latency)
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
