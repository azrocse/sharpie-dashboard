"""Normaliza físicamente el historial y mide la cobertura de liquidación."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .settle_history_espn import infer_primary_route
except ImportError:
    from settle_history_espn import infer_primary_route


BASE_DIR = Path(__file__).resolve().parents[2]
HISTORY_DIR = BASE_DIR / "data" / "history"
RESULTS_DIR = BASE_DIR / "data" / "results"
BACKUP_DIR = RESULTS_DIR / "backups"
AUDIT_FILE = RESULTS_DIR / "history_integrity.json"
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"}
CDMX_TZ = ZoneInfo("America/Mexico_City")
SCHEMA_VERSION = 3


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("\u2212", "-").replace("&", " and ").casefold()
    return " ".join(re.sub(r"[^a-z0-9.+@-]+", " ", text).split())


def _iso_date(value):
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


def effective_date(pick, source_path=None):
    lookup = pick.get("eventLookup") or {}
    for value in (pick.get("date"), pick.get("iso"), lookup.get("scheduledAt")):
        parsed = _iso_date(value)
        if parsed:
            return parsed

    folder_date = _iso_date(Path(source_path).parent.name if source_path else "")
    legacy = re.search(r"\b(\d{1,2})/(\d{1,2})\b", str(pick.get("time") or ""))
    if legacy:
        year = folder_date[:4] or str(datetime.now(CDMX_TZ).year)
        return f"{year}-{int(legacy.group(1)):02d}-{int(legacy.group(2)):02d}"
    return folder_date


def canonical_key(pick, source_path=None):
    return "||".join((
        _norm(effective_date(pick, source_path)),
        _norm(pick.get("game") or pick.get("event") or pick.get("matchup")),
        _norm(pick.get("pick")),
        _norm(pick.get("market")),
    ))


def canonical_id(pick, source_path=None):
    return hashlib.sha256(canonical_key(pick, source_path).encode("utf-8")).hexdigest()[:24]


def _result(pick):
    settlement = pick.get("settlement") or {}
    return str(settlement.get("status") or pick.get("result") or "PENDING").upper()


def _rank(pick):
    settlement = pick.get("settlement") or {}
    lookup = pick.get("eventLookup") or {}
    try:
        confidence = float(settlement.get("matchConfidence") or lookup.get("matchConfidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        _result(pick) in FINAL_RESULTS,
        bool(settlement.get("eventId") or lookup.get("eventId")),
        bool(_iso_date(pick.get("date"))),
        bool(pick.get("historyId")),
        str(pick.get("lastQualifiedAt") or pick.get("iso") or ""),
        confidence,
    )


def _merge_mapping(secondary, preferred):
    merged = dict(secondary or {})
    for key, value in (preferred or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _merge_records(left, right, source_path=None):
    preferred, secondary = (left, right) if _rank(left) >= _rank(right) else (right, left)
    merged = dict(preferred)

    snapshots, signatures = [], set()
    for record in (secondary, preferred):
        for snapshot in record.get("qualificationSnapshots") or []:
            if not isinstance(snapshot, dict):
                continue
            signature = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if signature not in signatures:
                signatures.add(signature)
                snapshots.append(snapshot)
    if snapshots:
        snapshots.sort(key=lambda item: str(item.get("observedAt") or ""))
        merged["qualificationSnapshots"] = snapshots
        merged["qualifiedObservations"] = len(snapshots)

    first_values = [str(value) for value in (left.get("firstQualifiedAt"), right.get("firstQualifiedAt")) if value]
    last_values = [str(value) for value in (left.get("lastQualifiedAt"), right.get("lastQualifiedAt")) if value]
    if first_values:
        merged["firstQualifiedAt"] = min(first_values)
    if last_values:
        merged["lastQualifiedAt"] = max(last_values)

    merged["eventLookup"] = _merge_mapping(secondary.get("eventLookup"), preferred.get("eventLookup"))
    merged["settlement"] = _merge_mapping(secondary.get("settlement"), preferred.get("settlement"))

    old_ids = {
        str(value) for value in (
            left.get("historyId"), right.get("historyId"),
            *(left.get("legacyHistoryIds") or []), *(right.get("legacyHistoryIds") or []),
        ) if value
    }
    new_id = canonical_id(merged, source_path)
    old_ids.discard(new_id)
    if old_ids:
        merged["legacyHistoryIds"] = sorted(old_ids)

    final_states = {_result(left), _result(right)} & FINAL_RESULTS
    if len(final_states) > 1:
        merged["historyIntegrityConflict"] = sorted(final_states)
    return merged


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _backup(files):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(CDMX_TZ).strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"history_before_canonical_{timestamp}.zip"
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(BASE_DIR).as_posix())
    return backup_path


def _audit(records, duplicates, moved, conflicts, backup_path=None):
    today = datetime.now(CDMX_TZ).date()
    status_counts = Counter()
    failure_counts = Counter()
    eligible_past = resolved_past = 0
    event_states = {}
    supported_past = resolved_supported = 0
    supported_event_states = {}

    for record in records:
        status = _result(record)
        status_counts[status] += 1
        settlement = record.get("settlement") or {}
        failure = settlement.get("failureCode") or settlement.get("notes") or "SIN_DETALLE"
        if status not in FINAL_RESULTS:
            failure_counts[str(failure)] += 1
        try:
            event_day = datetime.strptime(str(record.get("date") or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if event_day >= today:
            continue
        eligible_past += 1
        if status in FINAL_RESULTS:
            resolved_past += 1
        event_key = "||".join((_norm(record.get("date")), _norm(record.get("game"))))
        event_states.setdefault(event_key, []).append(status)
        market = _norm(record.get("market"))
        supported_market = any(token in market for token in (
            "moneyline", "money line", "spread", "run line", "puck line", "handicap", "total"
        ))
        if infer_primary_route(record) is not None and supported_market:
            supported_past += 1
            if status in FINAL_RESULTS:
                resolved_supported += 1
            supported_event_states.setdefault(event_key, []).append(status)

    eligible_events = len(event_states)
    resolved_events = sum(1 for states in event_states.values() if any(state in FINAL_RESULTS for state in states))
    pick_coverage = round(resolved_past / eligible_past * 100.0, 2) if eligible_past else 100.0
    event_coverage = round(resolved_events / eligible_events * 100.0, 2) if eligible_events else 100.0
    supported_events = len(supported_event_states)
    resolved_supported_events = sum(
        1 for states in supported_event_states.values()
        if any(state in FINAL_RESULTS for state in states)
    )
    supported_pick_coverage = round(resolved_supported / supported_past * 100.0, 2) if supported_past else 100.0
    supported_event_coverage = round(resolved_supported_events / supported_events * 100.0, 2) if supported_events else 100.0
    previous_cleanup = None
    try:
        previous_report = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
        previous_cleanup = previous_report.get("lastCleanup")
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    current_cleanup = None
    if backup_path:
        current_cleanup = {
            "completedAt": datetime.now(CDMX_TZ).isoformat(timespec="seconds"),
            "duplicatesRemoved": duplicates,
            "recordsMovedToEventDate": moved,
            "integrityConflicts": conflicts,
            "backup": str(backup_path),
        }

    report = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(CDMX_TZ).isoformat(timespec="seconds"),
        "uniquePicks": len(records),
        "duplicatesRemoved": duplicates,
        "recordsMovedToEventDate": moved,
        "integrityConflicts": conflicts,
        "statusCounts": dict(status_counts),
        "unresolvedReasons": dict(failure_counts),
        "eligiblePastPicks": eligible_past,
        "resolvedPastPicks": resolved_past,
        "pickCoveragePct": pick_coverage,
        "eligiblePastEvents": eligible_events,
        "resolvedPastEvents": resolved_events,
        "eventCoveragePct": event_coverage,
        "supportedPastPicks": supported_past,
        "resolvedSupportedPicks": resolved_supported,
        "supportedPickCoveragePct": supported_pick_coverage,
        "supportedPastEvents": supported_events,
        "resolvedSupportedEvents": resolved_supported_events,
        "supportedEventCoveragePct": supported_event_coverage,
        "outsideEspnCoveragePicks": eligible_past - supported_past,
        "coverageTargetPct": 90.0,
        "coverageTargetMet": supported_pick_coverage >= 90.0 and supported_event_coverage >= 90.0,
        "backup": str(backup_path) if backup_path else None,
        "lastCleanup": current_cleanup or previous_cleanup,
    }
    _atomic_json(AUDIT_FILE, report)
    return report


def normalize_history_storage(history_dir=HISTORY_DIR):
    """Consolida duplicados; crea ZIP antes de reescribir o retirar archivos."""
    root = Path(history_dir)
    files = sorted(root.glob("????-??-??/sharpie.json"))
    records, source_by_key = {}, {}
    loaded = moved = conflicts = 0

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"   ⚠️ Historial ilegible; no se modifica {path}: {exc}")
            return {"aborted": True, "error": str(exc)}
        picks = payload.get("picks", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for raw in picks:
            if not isinstance(raw, dict):
                continue
            loaded += 1
            record = dict(raw)
            event_date = effective_date(record, path)
            if not event_date:
                continue
            if path.parent.name != event_date:
                moved += 1
            record["date"] = event_date
            key = canonical_key(record, path)
            if key in records:
                records[key] = _merge_records(records[key], record, path)
            else:
                records[key] = record
                source_by_key[key] = path

    normalized = []
    for key, record in records.items():
        event_date = effective_date(record, source_by_key.get(key))
        record["date"] = event_date
        old_id = record.get("historyId")
        new_id = canonical_id(record, source_by_key.get(key))
        if old_id and str(old_id) != new_id:
            legacy_ids = {str(value) for value in record.get("legacyHistoryIds") or [] if value}
            legacy_ids.add(str(old_id))
            record["legacyHistoryIds"] = sorted(legacy_ids)
        record["historyId"] = new_id
        record["historySchemaVersion"] = SCHEMA_VERSION
        record["needsSettlement"] = not record.get("excludedFromResults") and _result(record) not in FINAL_RESULTS
        if record.get("historyIntegrityConflict"):
            conflicts += 1
        normalized.append(record)

    duplicates = max(0, loaded - len(normalized))
    target_groups = {}
    for record in normalized:
        target_groups.setdefault(record["date"], []).append(record)

    current_layout = {
        path: json.loads(path.read_text(encoding="utf-8")) for path in files
    }
    expected_paths = {root / date / "sharpie.json" for date in target_groups}
    layout_changed = bool(duplicates or moved or set(files) != expected_paths)
    if not layout_changed:
        for path, payload in current_layout.items():
            existing = payload.get("picks", []) if isinstance(payload, dict) else payload
            target = target_groups.get(path.parent.name, [])
            existing_ids = sorted(str(item.get("historyId") or "") for item in existing if isinstance(item, dict))
            target_ids = sorted(str(item.get("historyId") or "") for item in target)
            if existing_ids != target_ids:
                layout_changed = True
                break

    backup_path = None
    if layout_changed and files:
        backup_path = _backup(files)
        for date, items in target_groups.items():
            items.sort(key=lambda item: (str(item.get("iso") or ""), str(item.get("historyId") or "")))
            target = root / date / "sharpie.json"
            payload = {
                "schemaVersion": SCHEMA_VERSION,
                "eventDate": date,
                "updatedAt": datetime.now(CDMX_TZ).isoformat(timespec="seconds"),
                "count": len(items),
                "pendingSettlement": sum(1 for item in items if item.get("needsSettlement")),
                "settledCount": sum(1 for item in items if _result(item) in FINAL_RESULTS),
                "picks": items,
            }
            _atomic_json(target, payload)
        for obsolete in set(files) - expected_paths:
            obsolete.unlink(missing_ok=True)
            try:
                obsolete.parent.rmdir()
            except OSError:
                pass

    report = _audit(normalized, duplicates, moved, conflicts, backup_path)
    report["changed"] = layout_changed
    if layout_changed:
        print(
            f"   🧬 Historial saneado · {duplicates} duplicados fusionados · "
            f"{moved} registros reubicados"
        )
        print(f"   🛟 Respaldo recuperable · {backup_path.name}")
    coverage_icon = "✅" if report["coverageTargetMet"] else "⚠️"
    print(
        f"   {coverage_icon} Cobertura ESPN soportada · "
        f"picks {report['supportedPickCoveragePct']:.2f}% · "
        f"encuentros {report['supportedEventCoveragePct']:.2f}% · objetivo ≥90%"
    )
    if report["outsideEspnCoveragePicks"]:
        print(
            f"   ℹ️ Cobertura total · picks {report['pickCoveragePct']:.2f}% · "
            f"encuentros {report['eventCoveragePct']:.2f}% · "
            f"fuera de catálogo ESPN: {report['outsideEspnCoveragePicks']} picks"
        )
    return report
