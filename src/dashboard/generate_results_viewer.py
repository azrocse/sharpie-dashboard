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
RESULTS_SNAPSHOT_FILE = BASE_DIR / "data" / "results_snapshot.json"
OUTPUT_FILE = BASE_DIR / "results.html"
TEMPLATES_DIR = CURRENT_DIR / "templates"
ASSETS_DIR = CURRENT_DIR / "assets"
CDMX_TZ = ZoneInfo("America/Mexico_City")
VALUE_CATEGORIES = {"VALUE", "PREMIUM", "LONGSHOT"}
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"}


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"\s+", " ", text).strip().casefold().split())


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
    if category == "FREE":
        category = "VALUE"
    if category not in VALUE_CATEGORIES:
        return False
    try:
        ev = float(pick.get("ev") or 0)
        edge = float(pick.get("modelEdge") or 0)
        stake = float(pick.get("stake") or 0)
        odds = float(str(pick.get("odds") or 0).replace("+", ""))
        if stake < 0.5:
            return False
        if category == "PREMIUM":
            return ev >= 6.0 and edge >= 4.0
        if category == "VALUE":
            return ev >= 3.0 and edge >= 2.0 and odds < 151
        if odds >= 251:
            return ev >= 8.0 and edge >= 3.0
        return odds >= 151 and ev >= 5.0 and edge >= 2.0
    except (TypeError, ValueError):
        return False


def _dedupe_key(pick):
    if pick.get("historyId"):
        return str(pick["historyId"])
    return "||".join(_norm(pick.get(key)) for key in ("date", "league", "game", "market", "pick"))


def load_history(history_dir=HISTORY_DIR, snapshot_file=RESULTS_SNAPSHOT_FILE):
    records = {}
    root = Path(history_dir)
    snapshot = Path(snapshot_file) if snapshot_file else None
    if snapshot and snapshot.exists():
        try:
            archived = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            archived = []
        if isinstance(archived, list):
            for raw in archived:
                if isinstance(raw, dict) and _is_value_pick(raw) and not raw.get("excludedFromResults"):
                    pick = dict(raw)
                    if str(pick.get("pickCategory") or "").upper() == "FREE":
                        pick["pickCategory"] = "VALUE"
                        pick.setdefault("freeRelease", True)
                    records[_dedupe_key(pick)] = pick
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
            pick["game"] = pick.get("game") or pick.get("event") or pick.get("matchup") or "Evento sin nombre"
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
            key = _dedupe_key(pick)
            previous = records.get(key)
            if previous is None or str(pick.get("lastQualifiedAt") or pick.get("iso") or "") >= str(previous.get("lastQualifiedAt") or previous.get("iso") or ""):
                records[key] = pick
    return sorted(records.values(), key=lambda p: (p.get("date") or "", p.get("time") or "", p.get("game") or ""), reverse=True)


def generate_results_viewer(history_dir=HISTORY_DIR, output_file=OUTPUT_FILE, snapshot_file=RESULTS_SNAPSHOT_FILE):
    picks = load_history(history_dir, snapshot_file)
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
    print(f"[OK] Visualizador de resultados: {output_path} ({len(picks)} picks)")
    return str(output_path)



if __name__ == "__main__":
    generate_results_viewer()
