import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CDMX = ZoneInfo("America/Mexico_City")

# src/pipeline/lock_ev_history.py -> raíz del repo
BASE_DIR = Path(__file__).resolve().parents[2]
DAILY_HISTORY_DIR = BASE_DIR / "data" / "history"
LOCKED_DIR = BASE_DIR / "data" / "locked_picks"
STAGING_FILE = LOCKED_DIR / "_staging.json"
HISTORY_HTML = BASE_DIR / "history.html"


def _atomic_write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
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
        return dt.replace(tzinfo=CDMX)
    return dt.astimezone(CDMX)


def _pick_key(pick):
    raw = "||".join(str(pick.get(k, "")) for k in (
        "date", "league", "game", "market", "pick", "iso"
    ))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _ev_value(pick):
    try:
        return float(pick.get("ev"))
    except (TypeError, ValueError):
        return None


def _locked_record(pick, key, captured_at, locked_at):
    record = dict(pick)
    # El historial interno de evolución puede ser voluminoso y no es necesario
    # para la sábana congelada; las métricas finales sí se conservan.
    record.pop("history", None)
    record["lockedPickId"] = key
    record["capturedAt"] = captured_at
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
    picks.sort(key=lambda p: (str(p.get("iso") or ""), str(p.get("game") or ""), str(p.get("pick") or "")))
    payload = {
        "date": event_dt.strftime("%Y-%m-%d"),
        "updatedAt": datetime.now(CDMX).isoformat(timespec="seconds"),
        "count": len(picks),
        "picks": picks,
    }
    _atomic_write_json(path, payload)
    return True


def _current_dashboard_picks(now):
    """Lee exactamente la sábana diaria que acaba de construir el dashboard."""
    path = DAILY_HISTORY_DIR / now.strftime("%Y-%m-%d") / "sharpie.json"
    payload = _read_json(path, {})
    picks = payload.get("picks", []) if isinstance(payload, dict) else []
    return picks if isinstance(picks, list) else []


def sync_locked_ev_history():
    """Congela la última versión pregame observada. Única regla: EV > 0."""
    now = datetime.now(CDMX)
    now_iso = now.isoformat(timespec="seconds")
    LOCKED_DIR.mkdir(parents=True, exist_ok=True)

    staging = _read_json(STAGING_FILE, {"picks": {}})
    staged = staging.get("picks", {}) if isinstance(staging, dict) else {}
    if not isinstance(staged, dict):
        staged = {}

    remaining = {}
    locked_count = 0
    discarded_ev = 0

    # 1) Primero se congelan eventos que YA comenzaron usando el staging de la
    # corrida anterior. Así nunca usamos una versión post-inicio.
    for key, candidate in staged.items():
        if not isinstance(candidate, dict):
            continue
        pick = candidate.get("pick") if isinstance(candidate.get("pick"), dict) else candidate
        captured_at = candidate.get("capturedAt") or pick.get("capturedAt") or now_iso
        event_dt = _event_dt(pick)

        if event_dt is None or now < event_dt:
            remaining[key] = candidate
            continue

        ev = _ev_value(pick)
        if ev is not None and ev > 0:
            record = _locked_record(pick, key, captured_at, now_iso)
            if _append_locked(record, event_dt):
                locked_count += 1
        else:
            discarded_ev += 1

    # 2) Después se toma la salida que el dashboard acaba de construir y se
    # actualiza la última versión de cada pick todavía pregame.
    current = _current_dashboard_picks(now)
    observed_count = 0
    for pick in current:
        if not isinstance(pick, dict):
            continue
        event_dt = _event_dt(pick)
        if event_dt is None or now >= event_dt:
            continue

        key = _pick_key(pick)
        remaining[key] = {
            "capturedAt": now_iso,
            "pick": dict(pick),
        }
        observed_count += 1

    _atomic_write_json(STAGING_FILE, {
        "updatedAt": now_iso,
        "count": len(remaining),
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


def _all_locked_picks():
    rows = []
    if not LOCKED_DIR.exists():
        return rows
    for day_dir in sorted(LOCKED_DIR.iterdir()):
        if not day_dir.is_dir() or day_dir.name.startswith("_"):
            continue
        path = day_dir / "sharpie.json"
        payload = _read_json(path, {})
        picks = payload.get("picks", []) if isinstance(payload, dict) else []
        if isinstance(picks, list):
            rows.extend(p for p in picks if isinstance(p, dict))
    rows.sort(key=lambda p: str(p.get("iso") or ""), reverse=True)
    return rows


def generate_history_html():
    """Genera history.html independiente. No utiliza ni modifica template.html."""
    rows = _all_locked_picks()
    generated = datetime.now(CDMX).strftime("%Y-%m-%d %H:%M:%S")
    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")

    document = f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sharpie · Sábana Histórica EV+</title>
<style>
:root{{--bg:#0b1220;--panel:#111a2b;--line:#263449;--text:#e6edf7;--muted:#92a4bc;--accent:#2dd4bf;--good:#22c55e;--warn:#f59e0b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif;padding:20px}}
.wrap{{max-width:1900px;margin:auto}}h1{{margin:0 0 4px;font-size:25px}}.sub{{color:var(--muted);font-size:13px;margin-bottom:18px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:10px;margin-bottom:14px}}.metric{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.metric small{{display:block;color:var(--muted);margin-bottom:5px}}.metric b{{font-size:21px}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:12px}}input,select{{background:#0d1626;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px 10px}}
.tablebox{{overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel);max-height:75vh}}table{{border-collapse:collapse;width:100%;min-width:1750px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;text-align:left;white-space:nowrap}}th{{position:sticky;top:0;background:#162237;z-index:2;color:#cbd7e7}}tr:hover td{{background:#142036}}.num{{text-align:right;font-variant-numeric:tabular-nums}}.evpos{{color:var(--good);font-weight:700}}.muted{{color:var(--muted)}}
@media(max-width:700px){{body{{padding:10px}}.metrics{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body><div class="wrap">
<h1>Sharpie · Sábana Histórica EV+</h1>
<div class="sub">Snapshot congelado al inicio del evento · sólo última versión pregame con EV &gt; 0 · generado {html.escape(generated)}</div>
<div class="metrics">
 <div class="metric"><small>Registros congelados</small><b id="mCount">0</b></div>
 <div class="metric"><small>EV promedio</small><b id="mEv">—</b></div>
 <div class="metric"><small>Stake total</small><b id="mStake">—</b></div>
 <div class="metric"><small>Con resultado</small><b id="mSettled">0</b></div>
</div>
<div class="filters">
<input id="q" placeholder="Buscar evento / pick / liga" size="32">
<select id="league"><option value="">Todas las ligas</option></select>
<input id="evMin" type="number" step="0.1" placeholder="EV mín %">
<input id="edgeMin" type="number" step="0.1" placeholder="Edge mín %">
<select id="result"><option value="">Todos los resultados</option><option>PENDING</option><option>WIN</option><option>LOSS</option><option>PUSH</option><option>VOID</option></select>
</div>
<div class="tablebox"><table><thead><tr>
<th>Fecha</th><th>Hora</th><th>Liga</th><th>Evento</th><th>Pick</th><th>Mercado</th><th class="num">Cuota</th><th class="num">Modelo</th><th class="num">Edge</th><th class="num">EV</th><th class="num">Stake</th><th>Señal</th><th>Categoría</th><th class="num">Bets</th><th class="num">Handle</th><th class="num">Diverg.</th><th>Capturado</th><th>Congelado</th><th>Resultado</th><th class="num">Unidades</th><th class="num">Profit</th>
</tr></thead><tbody id="body"></tbody></table></div>
</div>
<script>
const DATA={data_json};
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[m]));
const num=(v,d=2)=>{{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'}};
const first=(p,...keys)=>{{for(const k of keys)if(p[k]!==undefined&&p[k]!==null&&p[k]!=='')return p[k];return null}};
const resultOf=p=>p.result||'PENDING';
const league=document.getElementById('league');
[...new Set(DATA.map(p=>p.league).filter(Boolean))].sort().forEach(v=>league.insertAdjacentHTML('beforeend',`<option>${{esc(v)}}</option>`));
function render(){{
 const q=document.getElementById('q').value.toLowerCase().trim();
 const l=league.value; const evm=Number(document.getElementById('evMin').value); const edm=Number(document.getElementById('edgeMin').value); const r=document.getElementById('result').value;
 const useEv=document.getElementById('evMin').value!==''; const useEdge=document.getElementById('edgeMin').value!=='';
 const rows=DATA.filter(p=>{{
   const hay=`${{p.game||''}} ${{p.pick||''}} ${{p.market||''}} ${{p.league||''}}`.toLowerCase();
   if(q&&!hay.includes(q))return false;if(l&&p.league!==l)return false;if(useEv&&Number(p.ev)<evm)return false;
   const edge=Number(first(p,'modelEdge','edge'));if(useEdge&&edge<edm)return false;if(r&&resultOf(p)!==r)return false;return true;
 }});
 document.getElementById('mCount').textContent=rows.length;
 const evs=rows.map(p=>Number(p.ev)).filter(Number.isFinite); document.getElementById('mEv').textContent=evs.length?(evs.reduce((a,b)=>a+b,0)/evs.length).toFixed(2)+'%':'—';
 const stakes=rows.map(p=>Number(p.stake)).filter(Number.isFinite);document.getElementById('mStake').textContent=stakes.length?stakes.reduce((a,b)=>a+b,0).toFixed(1)+'u':'—';
 document.getElementById('mSettled').textContent=rows.filter(p=>!['PENDING','',null,undefined].includes(resultOf(p))).length;
 document.getElementById('body').innerHTML=rows.map(p=>`<tr>
 <td>${{esc(p.date||'—')}}</td><td>${{esc(p.time||'—')}}</td><td>${{esc(p.league||'—')}}</td><td>${{esc(p.game||'—')}}</td><td><b>${{esc(p.pick||'—')}}</b></td><td>${{esc(p.market||'—')}}</td>
 <td class="num">${{esc(first(p,'odds','cuota')??'—')}}</td><td class="num">${{num(first(p,'modelProb','modelProbability'))}}%</td><td class="num">${{num(first(p,'modelEdge','edge'))}}%</td><td class="num evpos">${{num(p.ev)}}%</td><td class="num">${{num(p.stake,1)}}u</td>
 <td>${{esc(first(p,'marketSignal','trend','signal')??'—')}}</td><td>${{esc(first(p,'pickCategory','evaluation','category')??'—')}}</td><td class="num">${{num(first(p,'betsPct','bets'),1)}}%</td><td class="num">${{num(first(p,'handlePct','handle'),1)}}%</td><td class="num">${{num(first(p,'signedDivergence','divergence'),1)}}%</td>
 <td class="muted">${{esc(p.capturedAt||'—')}}</td><td class="muted">${{esc(p.lockedAt||'—')}}</td><td>${{esc(resultOf(p))}}</td><td class="num">${{p.unitsResult==null?'—':num(p.unitsResult,2)}}</td><td class="num">${{p.profit==null?'—':num(p.profit,2)}}</td></tr>`).join('');
}}
['q','league','evMin','edgeMin','result'].forEach(id=>document.getElementById(id).addEventListener(id==='q'?'input':'change',render));
render();
</script></body></html>'''

    _atomic_write_text(HISTORY_HTML, document)
    print(f"[OK] Sábana histórica generada: {HISTORY_HTML} · registros={len(rows)}")
    return HISTORY_HTML
