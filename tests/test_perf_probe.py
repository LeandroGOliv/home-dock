"""The performance probe: its maths, the socket counts it prints and short in-process runs
over fake bulbs."""

from collections import Counter
from types import SimpleNamespace

import pytest

import perf_probe
from perf_probe import Sample, percentile, socket_kinds, summarize


def sample(elapsed: float, cpu: float, working_set: int = 50 * 2**20) -> Sample:
    return Sample(elapsed, cpu, working_set, working_set, working_set // 2, 12, Counter())


@pytest.mark.parametrize(
    ("fraction", "expected"), [(0.0, 1), (0.5, 5), (0.95, 10), (0.9, 9), (1.0, 10)]
)
def test_percentile_is_the_nearest_rank(fraction, expected):
    assert percentile(list(range(10, 0, -1)), fraction) == expected


def test_percentile_needs_values():
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_sockets_are_counted_by_kind_without_addresses():
    connections = [
        SimpleNamespace(type=1, status="ESTABLISHED", laddr=("192.0.2.10", 50000)),
        SimpleNamespace(type=1, status="ESTABLISHED", laddr=("192.0.2.10", 50001)),
        SimpleNamespace(type=2, status="NONE", laddr=("0.0.0.0", 6667)),
    ]

    kinds = socket_kinds(connections)

    assert kinds == Counter({"TCP ESTABLISHED": 2, "UDP": 1})
    assert not any("192.0.2" in kind for kind in kinds)


def test_the_idle_cost_is_the_cpu_used_over_the_period_on_every_core():
    samples = [sample(0, 1.0), sample(10, 1.0), sample(20, 1.4, 60 * 2**20), sample(30, 1.6)]

    report = summarize(samples, cpu_count=4)

    assert report.seconds == 30
    assert report.cpu_seconds == pytest.approx(0.6)
    assert report.cpu_percent == pytest.approx(100 * 0.6 / 30 / 4)
    assert report.peak_cpu_percent == pytest.approx(100 * 0.4 / 10 / 4)
    assert report.peak_working_set == 60 * 2**20
    assert report.working_set == 50 * 2**20


def test_the_idle_cost_needs_two_samples():
    with pytest.raises(ValueError):
        summarize([sample(0, 0)], cpu_count=1)


def test_a_missing_exe_is_reported(tmp_path, capsys):
    code = perf_probe.main(["exe", "--exe", str(tmp_path / "HomeDock.exe")])

    assert code == 1
    assert "HomeDock.exe not found" in capsys.readouterr().err


def test_the_flyout_openings_are_timed(qapp, capsys):
    perf_probe.main(["flyout", "--opens", "2", "--latency", "0", "--profile", "5"])

    out = capsys.readouterr().out
    assert "first opening" in out
    assert "until painted" in out
    assert "cumulative" in out  # the profile


def test_the_paint_events_are_timed(qapp, capsys):
    perf_probe.main(["paint", "--frames", "2"])

    out = capsys.readouterr().out
    for widget in ("temperature arc", "hue ring", "brightness slider", "whole flyout"):
        assert widget in out


def test_a_drag_sends_the_bulbs_fewer_writes_than_values_and_ends_on_the_last(qapp):
    reports = perf_probe.probe_drag(seconds=0.3, bulbs=2, latency=0.02)

    assert [r.control for r in reports] == ["temperature arc", "hue ring", "brightness slider"]
    for report in reports:
        assert report.moves > 1
        assert all(0 < writes < report.moves for writes in report.writes)
        assert report.reached
