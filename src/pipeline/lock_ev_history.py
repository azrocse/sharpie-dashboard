import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CDMX = ZoneInfo("America/Mexico_City")

# src/pipeline/lock_ev_history.py -> repo root is two levels up
BASE_DIR = Path(__file__).resolve().parents[2]
PICKS_JSON = BASE_DIR / "picks.json"
LOCKED_DIR = BASE_DIR / "data" / "locked_picks"
STAGING_FILE = LOCKED_DIR / "_staging.json"


def _atomic_write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _event_dt(pick):
    raw = pick.get("iso")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CDMX)
    else:
        dt = dt.astimezone(CDMX)
    return dt


def _pick_key(pick):
    raw = "||".join(str(pick.get(k, "")) for k in (
        "league", "game", "market", "pick", "iso"
    ))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _ev_value(pick):
    try:
        return float(pick.get("ev"))
    except (TypeError, ValueError):
        return None


def _locked_record(pick, key, locked_at):
    # Copia íntegra de la última versión que realmente apareció en picks.json.
    record = dict(pick)
    record["lockedPickId"] = key
    record["capturedAt"] = pick.get("capturedAt")
    record["lockedAt"] = locked_at
    record["result"] = None
    record["unitsResult"] = None
    record["profit"] = None
    return record


def _append_locked(record, event_dt):
    day_dir = LOCKED_DIR / event_dt.strftime("%Y-%m-%d")
    path = day_dir / "sharpie.json"
    payload = _read_json(path, {"date": event_dt.strftime("%Y-%m-%d"), "picks": []})
    picks = payload.get("picks") if isinstance(payload, dict) else []
    if not isinstance(picks, list):
        picks = []

    key = record["lockedPickId"]
    if any(p.get("lockedPickId") == key for p in picks if isinstance(p, dict)):
        return False

    picks.append(record)
    payload = {
        "date": event_dt.strftime("%Y-%m-%d"),
        "updatedAt": datetime.now(CDMX).isoformat(timespec="seconds"),
        "picks": picks,
    }
    _atomic_write_json(path, payload)
    return True


def sync_locked_ev_history():
    """Mantiene una sábana EV+ sin intervenir en el dashboard ni su template.

    1) Congela desde staging los eventos que ya iniciaron, usando la última
       versión observada antes del inicio.
    2) Sólo entra a la sábana definitiva si esa última versión tiene EV > 0.
    3) Después actualiza staging leyendo el picks.json que acaba de producir
       el dashboard. Por tanto staging representa exactamente lo mostrado.
    """
    now = datetime.now(CDMX)
    now_iso = now.isoformat(timespec="seconds")
    LOCKED_DIR.mkdir(parents=True, exist_ok=True)

    staging = _read_json(STAGING_FILE, {"picks": {}})
    staged = staging.get("picks", {}) if isinstance(staging, dict) else {}
    if not isinstance(staged, dict):
        staged = {}

    # A. Congelar primero lo que ya inició usando la última versión previa.
    remaining = {}
    locked_count = 0
    discarded_ev = 0

    for key, pick in staged.items():
        if not isinstance(pick, dict):
            continue
        event_dt = _event_dt(pick)
        if event_dt is None or now < event_dt:
            remaining[key] = pick
            continue

        ev = _ev_value(pick)
        if ev is not None and ev > 0:
            record = _locked_record(pick, key, now_iso)
            if _append_locked(record, event_dt):
                locked_count += 1
        else:
            discarded_ev += 1

    # B. Leer únicamente la salida real del dashboard recién generado.
    current = _read_json(PICKS_JSON, [])
    if not isinstance(current, list):
        current = []

    observed_count = 0
    for pick in current:
        if not isinstance(pick, dict):
            continue
        event_dt = _event_dt(pick)
        if event_dt is None or now >= event_dt:
            continue

        key = _pick_key(pick)
        snapshot = dict(pick)
        snapshot["capturedAt"] = now_iso
        snapshot["lockedPickId"] = key
        remaining[key] = snapshot  # upsert = siempre la última versión
        observed_count += 1

    _atomic_write_json(STAGING_FILE, {
        "updatedAt": now_iso,
        "picks": remaining,
    })

    print(
        f"[SABANA EV+] observados={observed_count} · "
        f"congelados={locked_count} · descartados_ev_no_positivo={discarded_ev} · "
        f"staging={len(remaining)}"
    )
    return {
        "observed": observed_count,
        "locked": locked_count,
        "discardedEvNonPositive": discarded_ev,
        "staging": len(remaining),
    }
