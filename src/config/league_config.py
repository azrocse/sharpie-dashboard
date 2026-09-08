"""Carga y valida el catálogo de ligas habilitadas."""

from __future__ import annotations

import json
import re
import unicodedata
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


def league_slug(name):
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def enabled_leagues(config_file=CONFIG_FILE):
    """Catálogo compartido por la descarga y el análisis independiente."""
    leagues = []
    seen = set()
    for name, config in load_leagues(config_file).items():
        if not isinstance(config, dict):
            raise ValueError(f"Configuración inválida para {name}")
        if config.get("enabled") is not True:
            continue
        slug = str(config.get("slug") or "").strip()
        filename = league_slug(name)
        if not slug or not filename or filename in seen:
            raise ValueError(f"Nombre o slug inválido/duplicado para {name}")
        seen.add(filename)
        leagues.append({
            "league": name,
            "slug": slug,
            "date_range": str(config.get("date_range") or "today").strip(),
        })
    if not leagues:
        raise ValueError("No hay ligas habilitadas en la configuración")
    return leagues
