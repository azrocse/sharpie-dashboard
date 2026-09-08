"""Escritura atómica de los archivos del estado actual."""

import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, content: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination


def atomic_write_json(path: str | Path, payload: object, *, compact: bool = False) -> Path:
    separators = (",", ":") if compact else None
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=None if compact else 2,
        separators=separators,
    )
    return atomic_write_text(path, content + ("" if compact else "\n"))
