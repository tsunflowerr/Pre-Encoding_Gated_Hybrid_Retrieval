"""Smoke-import the built distribution outside the checkout, directly from its wheel."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def check(wheel: Path) -> None:
    code = """
import importlib
import importlib.resources
import sys
sys.path.insert(0, sys.argv[1])
for name in ('contracts', 'pegh.v3.rescore', 'pegh.v4.gate'):
    module = importlib.import_module(name)
    if not str(module.__file__).startswith(sys.argv[1]):
        raise RuntimeError(f'{name} was imported outside the wheel: {module.__file__}')
resource = importlib.resources.files('contracts').joinpath('resources/primary_model.json')
if not resource.is_file():
    raise RuntimeError('wheel is missing the registered model resource')
print('Wheel imports and contract resources verified')
"""
    with tempfile.TemporaryDirectory(prefix="pegh-wheel-") as directory:
        subprocess.run(
            [sys.executable, "-I", "-c", code, str(wheel.resolve())],
            cwd=directory,
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.directory.glob("pegh_research-*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one pegh_research wheel")
    check(wheels[0])
