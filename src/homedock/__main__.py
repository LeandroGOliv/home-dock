"""Entry point for ``python -m homedock`` and the ``homedock`` script."""

import sys

from homedock.storage import open_app_data


def main() -> int:
    data = open_app_data()
    print(f"HomeDock: data in {data.paths.root}; the UI is not implemented yet.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
