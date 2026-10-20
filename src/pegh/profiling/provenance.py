from __future__ import annotations

from pathlib import Path

from pegh.dense.artifacts import file_hash, object_hash


def source_snapshot(root: str | Path = ".") -> dict:
    """Hash executable project sources/configuration, independently of Git cleanliness."""
    root = Path(root).resolve()
    files = []
    for directory in ("src", "contracts", "configs", "scripts_b"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".yaml", ".json", ".toml"):
                files.append({"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)})
    for filename in ("pyproject.toml", "uv.lock"):
        path = root / filename
        if path.exists():
            files.append({"path": filename, "sha256": file_hash(path)})
    return {"files": files, "combined_sha256": object_hash(files)}
