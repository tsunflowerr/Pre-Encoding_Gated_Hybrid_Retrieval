from __future__ import annotations

from pathlib import Path

from pegh.dense.artifacts import file_hash, object_hash


def source_root(root: str | Path | None = None) -> Path:
    directory = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[3]
    if not (
        (directory / "pyproject.toml").is_file()
        and (directory / "src/pegh").is_dir()
        and (directory / "contracts/types.py").is_file()
    ):
        raise ValueError("benchmark provenance requires a valid source checkout")
    return directory


def source_snapshot(root: str | Path | None = None) -> dict:
    """Hash executable project sources/configuration, independently of Git cleanliness."""
    root = source_root(root)
    files = []
    for directory in ("src", "contracts", "configs", "scripts_b"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".yaml", ".yml", ".json", ".toml"):
                files.append({"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)})
    for filename in ("pyproject.toml", "uv.lock"):
        path = root / filename
        if path.exists():
            files.append({"path": filename, "sha256": file_hash(path)})
    return {"files": files, "combined_sha256": object_hash(files)}
