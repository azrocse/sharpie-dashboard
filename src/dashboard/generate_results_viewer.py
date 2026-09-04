"""Genera results.html a partir del historial persistente de Sharpie."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .template_loader import atomic_write_text, read_utf8, render_template
except ImportError:
    from template_loader import atomic_write_text, read_utf8, render_template


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent.parent
HISTORY_DIR = BASE_DIR / "data" / "history"
OUTPUT_FILE = BASE_DIR / "results.html"
TEMPLATES_DIR = CURRENT_DIR / "templates"
ASSETS_DIR = CURRENT_DIR / "assets"
CDMX_TZ = ZoneInfo("America/Mexico_City")
VALUE_CATEGORIES = {"VALUE", "PREMIUM", "WHALE", "FREE"}
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"}


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("−", "-").replace("&", " and ").casefold()
    return " ".join(re.sub(r"[^a-z0-9.+@-]+", " ", text).split())


def _american_profit(odds, stake, result):
    try:
        price = float(str(odds).replace("+", ""))
        units = float(stake)
    except (TypeError, ValueError):
        return None
    if result == "LOSS":
        return round(-units, 4)
    if result == "HALF_LOSS":
        return round(-units / 2, 4)
    if result in {"PUSH", "VOID"}:
        return 0.0
    if result not in {"WIN", "HALF_WIN"} or price == 0:
        return None
    multiplier = abs(price) - 1 if 1.01 <= abs(price) <= 50 else price / 100 if price > 0 else 100 / abs(price)
    profit = units * multiplier
    return round(profit / 2 if result == "HALF_WIN" else profit, 4)


def _result_of(pick):
    settlement = pick.get("settlement") or {}
    status = str(settlement.get("status") or "").upper()
    if status in FINAL_RESULTS | {"PENDING", "REVIEW"}:
        return status
    result = str(settlement.get("result") or pick.get("result") or "PENDING").upper()
    if result == "SETTLED": result = "REVIEW"
    return result if result in FINAL_RESULTS | {"PENDING", "REVIEW"} else "PENDING"


def _is_value_pick(pick):
    category = str(pick.get("pickCategory") or "").upper()
    if category not in VALUE_CATEGORIES and pick.get("actionKey") != "bet":
        return False
    try:
        return (
            float(pick.get("stake") or 0) >= 1.0
            and float(pick.get("ev") or 0) > 0
            and float(pick.get("modelEdge") or 0) > 0
        )
    except (TypeError, ValueError):
        return False


def _iso_date(value):
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


def _effective_date(pick, history_path=None):
    lookup = pick.get("eventLookup") or {}
    for value in (pick.get("date"), pick.get("iso"), lookup.get("scheduledAt")):
        parsed = _iso_date(value)
        if parsed:
            return parsed

    # Formato heredado de DraftKings: "9/3, 06:00PM".
    legacy = re.search(r"\b(\d{1,2})/(\d{1,2})\b", str(pick.get("time") or ""))
    folder_date = _iso_date(history_path.parent.name if history_path else "")
    if legacy:
        year = folder_date[:4] or str(datetime.now(CDMX_TZ).year)
        return f"{year}-{int(legacy.group(1)):02d}-{int(legacy.group(2)):02d}"
    return folder_date


def _dedupe_key(pick, history_path=None):
    """Identidad deportiva estable; no depende de IDs heredados."""
    return "||".join((
        _effective_date(pick, history_path),
        _norm(pick.get("game") or pick.get("event") or pick.get("matchup")),
        _norm(pick.get("market")),
        _norm(pick.get("pick")),
    ))


def _record_rank(pick):
    settlement = pick.get("settlement") or {}
    lookup = pick.get("eventLookup") or {}
    result = _result_of(pick)
    try:
        confidence = float(settlement.get("matchConfidence") or lookup.get("matchConfidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        result in FINAL_RESULTS,
        bool(_iso_date(pick.get("date"))),
        bool(settlement.get("eventId") or lookup.get("eventId")),
        bool(pick.get("historyId")),
        str(pick.get("lastQualifiedAt") or pick.get("iso") or ""),
        confidence,
    )


def _merge_duplicate(preferred, secondary):
    merged = dict(preferred)
    snapshots = []
    signatures = set()
    for source in (secondary, preferred):
        for snapshot in source.get("qualificationSnapshots") or []:
            if not isinstance(snapshot, dict):
                continue
            signature = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if signature not in signatures:
                signatures.add(signature)
                snapshots.append(snapshot)
    if snapshots:
        merged["qualificationSnapshots"] = sorted(snapshots, key=lambda item: str(item.get("observedAt") or ""))
        merged["qualifiedObservations"] = len(snapshots)
    first_values = [str(item) for item in (preferred.get("firstQualifiedAt"), secondary.get("firstQualifiedAt")) if item]
    last_values = [str(item) for item in (preferred.get("lastQualifiedAt"), secondary.get("lastQualifiedAt")) if item]
    if first_values:
        merged["firstQualifiedAt"] = min(first_values)
    if last_values:
        merged["lastQualifiedAt"] = max(last_values)
    return merged


def load_history(history_dir=HISTORY_DIR):
    records = {}
    accepted = 0
    root = Path(history_dir)
    for path in sorted(root.glob("????-??-??/sharpie.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        picks = payload.get("picks", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for raw in picks:
            if not isinstance(raw, dict):
                continue
            pick = dict(raw)
            try:
                positive_value = float(pick.get("ev") or 0) > 0 and float(pick.get("modelEdge") or 0) > 0
                old_stake = float(pick.get("stake") or 0)
            except (TypeError, ValueError):
                positive_value, old_stake = False, 0.0
            stake_normalized = positive_value and old_stake <= 0
            if stake_normalized:
                pick["originalStake"] = raw.get("stake")
                pick["stake"] = 1.0
                pick["stakeNormalized"] = True
                pick["stakeNormalizationReason"] = "LEGACY_STAKE_MODEL"
                if pick.get("exclusionReason") == "NON_ACTIONABLE_PICK":
                    pick.pop("excludedFromResults", None)
                    pick.pop("exclusionReason", None)
            if not _is_value_pick(pick) or pick.get("excludedFromResults"):
                continue
            accepted += 1
            pick["game"] = pick.get("game") or pick.get("event") or pick.get("matchup") or "Evento sin nombre"
            effective_date = _effective_date(pick, path)
            if effective_date:
                pick["date"] = effective_date
            pick["pickCategory"] = pick.get("pickCategory") or pick.get("category") or "VALUE"
            pick["marketSignal"] = pick.get("marketSignal") or pick.get("signal") or "—"
            if str(pick.get("pickCategory") or "").upper() == "FREE":
                pick["pickCategory"] = "VALUE"
                pick.setdefault("freeRelease", True)
            result = _result_of(pick)
            pick["result"] = result
            if stake_normalized or pick.get("profitUnits") is None:
                pick["profitUnits"] = _american_profit(pick.get("odds"), pick.get("stake"), result)
            pick["historyFile"] = str(path.relative_to(root)).replace("\\", "/")
            key = _dedupe_key(pick, path)
            previous = records.get(key)
            if previous is None:
                records[key] = pick
            elif _record_rank(pick) > _record_rank(previous):
                records[key] = _merge_duplicate(pick, previous)
            else:
                records[key] = _merge_duplicate(previous, pick)
    duplicate_count = accepted - len(records)
    if duplicate_count:
        print(f"   ♻️ Historial consolidado · {duplicate_count} copias redundantes omitidas")
    return sorted(records.values(), key=lambda p: (p.get("date") or "", p.get("time") or "", p.get("game") or ""), reverse=True)


def generate_results_viewer(history_dir=HISTORY_DIR, output_file=OUTPUT_FILE):
    picks = load_history(history_dir)
    generated_at = datetime.now(CDMX_TZ).isoformat(timespec="seconds")
    json_data = json.dumps(picks, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = render_template(
        TEMPLATES_DIR / "results.html",
        {
            "RESULTS_CSS": read_utf8(ASSETS_DIR / "css" / "results.css"),
            "RESULTS_BODY": read_utf8(TEMPLATES_DIR / "results_body.html"),
            "RESULTS_JS": read_utf8(ASSETS_DIR / "js" / "results.js"),
            "PICKS_JSON": json_data,
            "GENERATED_AT": generated_at,
            "TODAY_CDMX": datetime.now(CDMX_TZ).date().isoformat(),
        },
    )
    output_path = Path(output_file)
    atomic_write_text(output_path, html)
    print(f"   🧾 Resultados listos · {len(picks)} picks históricos · {output_path.name}")
    return str(output_path)



if __name__ == "__main__":
    generate_results_viewer()
