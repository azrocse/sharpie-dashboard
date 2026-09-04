"""Carga y valida el catálogo de ligas habilitadas."""

from __future__ import annotations

import json
from pathlib import Path


CONFIG_FILE = Path(__file__).with_name("leagues.json")


def load_leagues(config_file=CONFIG_FILE):
    path = Path(config_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"No existe la configuración de ligas: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"La configuración de ligas contiene JSON inválido: {path} "
            f"(línea {exc.lineno}, columna {exc.colno})"
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError(f"La raíz de {path} debe ser un objeto JSON")
    return payload

