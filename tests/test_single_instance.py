"""Single-instance guard: a second HomeDock must not open another tray icon."""

import subprocess
import sys
import uuid

import pytest

from homedock.ui.single_instance import SingleInstance


@pytest.fixture
def name() -> str:
    return f"Local\\HomeDock.Test.{uuid.uuid4().hex}"


def test_the_first_instance_acquires_the_lock(name):
    lock = SingleInstance.acquire(name)

    assert lock is not None
    lock.release()


def test_a_second_instance_is_refused_while_the_first_runs(name):
    first = SingleInstance.acquire(name)
    try:
        assert SingleInstance.acquire(name) is None
    finally:
        first.release()


def test_another_process_is_refused_while_the_first_runs(name):
    script = (
        "import sys; from homedock.ui.single_instance import SingleInstance; "
        "print(SingleInstance.acquire(sys.argv[1]) is None)"
    )
    with SingleInstance.acquire(name):
        second = subprocess.run(
            [sys.executable, "-c", script, name], capture_output=True, text=True, check=True
        )

    assert second.stdout.strip() == "True"


def test_the_lock_can_be_taken_again_after_release(name):
    SingleInstance.acquire(name).release()

    again = SingleInstance.acquire(name)

    assert again is not None
    again.release()


def test_release_is_idempotent(name):
    lock = SingleInstance.acquire(name)
    lock.release()
    lock.release()

    with SingleInstance.acquire(name) as again:
        assert again is not None


def test_different_names_do_not_conflict(name):
    with SingleInstance.acquire(name), SingleInstance.acquire(name + ".other") as other:
        assert other is not None
