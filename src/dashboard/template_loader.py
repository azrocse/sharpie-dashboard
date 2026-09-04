"""Carga, valida y ensambla los recursos HTML del dashboard."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping


TOKEN_PATTERN = re.compile(r"__[A-Z][A-Z0-9_]*__")


def read_utf8(path: str | Path) -> str:
    source = Path(path)
    try:
        return source.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"No se pudo leer el recurso requerido: {source}") from exc


def render_template(template_path: str | Path, replacements: Mapping[str, str]) -> str:
    """Reemplaza tokens exactos y falla si el HTML queda incompleto."""
    rendered = read_utf8(template_path)
    for token, value in replacements.items():
        placeholder = token if token.startswith("__") else f"__{token}__"
        if placeholder not in rendered:
            raise ValueError(f"El template no contiene el token requerido {placeholder}")
        rendered = rendered.replace(placeholder, value)

    unresolved = sorted(set(TOKEN_PATTERN.findall(rendered)))
    if unresolved:
        raise ValueError(f"Tokens sin resolver en {template_path}: {', '.join(unresolved)}")
    return rendered


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
