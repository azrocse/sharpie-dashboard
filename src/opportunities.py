"""Conserva las oportunidades con sus valores finales, sin recalcular el modelo."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unicodedata
from zoneinfo import ZoneInfo

from storage import atomic_write_json


CDMX = ZoneInfo("America/Mexico_City")


def _event_time(pick):
    try:
        value = datetime.fromisoformat(str(pick.get("iso") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=CDMX) if value.tzinfo is None else value.astimezone(CDMX)


def _identity(pick, kickoff):
    # La fuente puede mejorar de SPORTS a una liga exacta sin crear otro pick.
    parts = [
        kickoff.date().isoformat(), pick.get("game"), pick.get("market"), pick.get("pick"),
    ]
    parts = [" ".join(unicodedata.normalize("NFKC", str(part or "")).replace("\u2212", "-").casefold().split()) for part in parts]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def save_opportunities(picks, path, now=None):
    """Actualiza una fila por oportunidad hasta el inicio; luego la congela.

    Usa el mismo criterio de oportunidades del dashboard: FREE/PREMIUM/WHALE y
    actionKey=bet. Una oportunidad que deja de calificar conserva su última
    versión elegible. No importa archivos anteriores ni registra seguimiento.
    """
    path = Path(path)
    now = now or datetime.now(CDMX)
    now = now.replace(tzinfo=CDMX) if now.tzinfo is None else now.astimezone(CDMX)
    timestamp = now.isoformat(timespec="seconds")
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("picks"), list):
            raise ValueError(f"Archivo de oportunidades inválido: {path}")
    else:
        payload = {"schemaVersion": 1, "startedAt": timestamp, "picks": []}
    records = {}
    for record in payload["picks"]:
        if not isinstance(record, dict) or not record.get("opportunityId"):
            raise ValueError(f"Registro de oportunidad inválido: {path}")
        kickoff = _event_time(record)
        key = _identity(record, kickoff) if kickoff is not None else record["opportunityId"]
        record["opportunityId"] = key
        current = records.get(key)
        record_rank = (record.get("league") != "SPORTS", str(record.get("lastUpdatedAt") or ""))
        current_rank = (current.get("league") != "SPORTS", str(current.get("lastUpdatedAt") or "")) if current else None
        if current is None:
            winner = record
        else:
            winner, other = (record, current) if record_rank > current_rank else (current, record)
            captured = [str(item.get("firstCapturedAt")) for item in (winner, other) if item.get("firstCapturedAt")]
            if captured:
                winner["firstCapturedAt"] = min(captured)
            transitions = winner.get("transitions", []) + other.get("transitions", [])
            winner["transitions"] = sorted(
                {(str(item.get("at") or ""), item.get("state"), item.get("category")): item for item in transitions}.values(),
                key=lambda item: str(item.get("at") or ""),
            )
        winner.setdefault("ruleVersion", "legacy-v1")
        records[key] = winner

    for record in records.values():
        kickoff = _event_time(record)
        if not record.get("frozenAt") and kickoff is not None and kickoff <= now:
            record["frozenAt"] = kickoff.isoformat(timespec="seconds")
            record["opportunityState"] = "CLOSED"

    for pick in picks:
        kickoff = _event_time(pick)
        if kickoff is None or kickoff <= now or pick.get("status") not in {None, "", "UPCOMING", "PENDING", "SCHEDULED"}:
            continue
        key = _identity(pick, kickoff)
        previous = records.get(key)
        if previous and previous.get("frozenAt"):
            continue
        actionable = pick.get("actionKey") == "bet" and pick.get("pickCategory") in {"FREE", "PREMIUM", "WHALE"}
        if not actionable and previous is None:
            continue
        previous_category = previous.get("pickCategory") if previous else None
        transitions = deepcopy(previous.get("transitions", [])) if previous else []
        state = "ACTIVE" if actionable else "NO_LONGER_VALUE"
        previous_state = previous.get("opportunityState") if previous else None
        if previous is None or previous_category != pick.get("pickCategory") or previous_state != state:
            transitions.append({"at": timestamp, "state": state, "category": pick.get("pickCategory")})
        records[key] = {
            **deepcopy(pick),
            "opportunityId": key,
            "firstCapturedAt": previous["firstCapturedAt"] if previous else timestamp,
            "lastUpdatedAt": timestamp,
            "frozenAt": None,
            "ruleVersion": "sharpie-v2",
            "opportunityState": state,
            "transitions": transitions,
        }

    payload["picks"] = sorted(records.values(), key=lambda item: (item.get("date") or "", item.get("iso") or "", item["opportunityId"]))
    payload["updatedAt"] = timestamp
    payload["count"] = len(payload["picks"])
    atomic_write_json(path, payload, compact=True)
    return payload
