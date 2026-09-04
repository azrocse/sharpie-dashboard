"""Mantenimiento acotado de artefactos temporales de Sharpie.

Nunca elimina historial de picks ni archivos de calibración. Los RAW se usan
solo dentro de la ejecución que los descargó; los snapshots se retienen hasta
que todos sus eventos hayan quedado suficientemente atrás.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
SNAPSHOTS_DIR = BASE_DIR / "data" / "snapshots"
RESULTS_DIR = BASE_DIR / "data" / "results"
MAINTENANCE_MARKER = RESULTS_DIR / ".maintenance_date"
CDMX_TZ = ZoneInfo("America/Mexico_City")

SNAPSHOT_GRACE_DAYS = 2
UNKNOWN_SNAPSHOT_RETENTION_DAYS = 7


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _unlink_file(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        print(f"[MANTENIMIENTO] No se pudo eliminar {path}: {exc}")
        return False


def cleanup_downloaded_raw(downloaded) -> int:
    """Elimina exclusivamente los RAW devueltos por la corrida actual."""
    removed = 0
    for league in downloaded or []:
        if not isinstance(league, dict):
            continue
        for raw_path in league.get("files") or []:
            candidate = Path(str(raw_path))
            if candidate.is_file() and _is_inside(candidate, RAW_DIR):
                removed += int(_unlink_file(candidate))
    return removed


def prune_stale_raw(max_age_hours: int = 6) -> int:
    """Recoge RAW huérfanos dejados por una ejecución interrumpida."""
    if not RAW_DIR.exists():
        return 0
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    removed = 0
    for candidate in RAW_DIR.rglob("*"):
        try:
            stale = candidate.is_file() and candidate.stat().st_mtime < cutoff
        except OSError:
            continue
        if stale and candidate.suffix.lower() in {".html", ".tmp"}:
            removed += int(_unlink_file(candidate))
    return removed


def _parse_event_date(raw, fallback_year: int) -> date | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        month_day = text.split(",", 1)[0].strip()
        return datetime.strptime(f"{month_day}/{fallback_year}", "%m/%d/%Y").date()
    except ValueError:
        return None


def _latest_event_date(snapshot: Path) -> date | None:
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        fallback_year = datetime.strptime(snapshot.stem[:8], "%Y%m%d").year
    except ValueError:
        fallback_year = datetime.now(CDMX_TZ).year
    dates = []
    for game in payload.get("games", []) if isinstance(payload, dict) else []:
        if not isinstance(game, dict):
            continue
        raw = game.get("time_raw") or game.get("time") or game.get("startIso") or game.get("date")
        parsed = _parse_event_date(raw, fallback_year)
        if parsed:
            dates.append(parsed)
    return max(dates) if dates else None


def prune_finished_snapshots(today: date | None = None) -> int:
    """Elimina snapshots cuyo evento más reciente ya quedó atrás.

    Los archivos sin una fecha interpretable se conservan siete días. Nunca
    se inspecciona ni modifica ``data/history``.
    """
    if not SNAPSHOTS_DIR.exists():
        return 0
    today = today or datetime.now(CDMX_TZ).date()
    event_cutoff = today - timedelta(days=SNAPSHOT_GRACE_DAYS)
    unknown_cutoff = datetime.now().timestamp() - UNKNOWN_SNAPSHOT_RETENTION_DAYS * 86400
    removed = 0
    for snapshot in SNAPSHOTS_DIR.rglob("*.json"):
        latest = _latest_event_date(snapshot)
        if latest is not None:
            should_remove = latest < event_cutoff
        else:
            try:
                should_remove = snapshot.stat().st_mtime < unknown_cutoff
            except OSError:
                should_remove = False
        if should_remove:
            removed += int(_unlink_file(snapshot))
    return removed


def _atomic_marker(value: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = MAINTENANCE_MARKER.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, MAINTENANCE_MARKER)


def run_maintenance() -> dict[str, int]:
    """Limpia RAW huérfanos siempre y snapshots terminados una vez al día."""
    today = datetime.now(CDMX_TZ).date()
    summary = {"raw": prune_stale_raw(), "snapshots": 0}
    try:
        already_run = MAINTENANCE_MARKER.read_text(encoding="utf-8").strip() == today.isoformat()
    except OSError:
        already_run = False
    if not already_run:
        summary["snapshots"] = prune_finished_snapshots(today)
        _atomic_marker(today.isoformat())
    if any(summary.values()):
        print(
            "   🧹 Limpieza preventiva · "
            f"RAW antiguos: {summary['raw']} · snapshots cerrados: {summary['snapshots']}"
        )
    return summary
