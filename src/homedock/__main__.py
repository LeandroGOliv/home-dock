"""Entry point for ``python -m homedock`` and the ``homedock`` script."""

from homedock.ui.app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
