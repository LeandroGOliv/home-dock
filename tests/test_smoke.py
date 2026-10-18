import tomllib
from pathlib import Path

import homedock


def test_package_exposes_version():
    assert homedock.__version__


def test_the_version_matches_the_project_file():
    # HomeDock.exe shows this version in its properties (packaging/HomeDock.spec).
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    assert homedock.__version__ == project["project"]["version"]
