"""Genera results.html a partir del historial persistente de Sharpie."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent.parent
HISTORY_DIR = BASE_DIR / "data" / "history"
OUTPUT_FILE = BASE_DIR / "results.html"
VALUE_CATEGORIES = {"VALUE", "PREMIUM", "WHALE", "FREE"}
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID"}


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
    if result in {"PUSH", "VOID"}:
        return 0.0
    if result != "WIN" or price == 0:
        return None
    multiplier = abs(price) - 1 if 1.01 <= abs(price) <= 50 else price / 100 if price > 0 else 100 / abs(price)
    return round(units * multiplier, 4)


def _result_of(pick):
    settlement = pick.get("settlement") or {}
    result = str(settlement.get("result") or pick.get("result") or settlement.get("status") or "PENDING").upper()
    if result == "SETTLED":
        result = "REVIEW"
    return result if result in FINAL_RESULTS | {"PENDING", "REVIEW"} else "PENDING"


def _is_value_pick(pick):
    category = str(pick.get("pickCategory") or "").upper()
    return category in VALUE_CATEGORIES or pick.get("actionKey") == "bet" or bool(pick.get("historyId"))


def _dedupe_key(pick):
    if pick.get("historyId"):
        return str(pick["historyId"])
    return "||".join(_norm(pick.get(key)) for key in ("date", "league", "game", "market", "pick"))


def load_history(history_dir=HISTORY_DIR):
    records = {}
    root = Path(history_dir)
    for path in sorted(root.glob("????-??-??/sharpie.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        picks = payload.get("picks", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for raw in picks:
            if not isinstance(raw, dict) or not _is_value_pick(raw):
                continue
            pick = dict(raw)
            pick["game"] = pick.get("game") or pick.get("event") or pick.get("matchup") or "Evento sin nombre"
            pick["pickCategory"] = pick.get("pickCategory") or pick.get("category") or "VALUE"
            pick["marketSignal"] = pick.get("marketSignal") or pick.get("signal") or "—"
            if str(pick.get("pickCategory") or "").upper() == "FREE":
                pick["pickCategory"] = "VALUE"
                pick.setdefault("freeRelease", True)
            result = _result_of(pick)
            pick["result"] = result
            if pick.get("profitUnits") is None:
                pick["profitUnits"] = _american_profit(pick.get("odds"), pick.get("stake"), result)
            pick["historyFile"] = str(path.relative_to(root)).replace("\\", "/")
            key = _dedupe_key(pick)
            previous = records.get(key)
            if previous is None or str(pick.get("lastQualifiedAt") or pick.get("iso") or "") >= str(previous.get("lastQualifiedAt") or previous.get("iso") or ""):
                records[key] = pick
    return sorted(records.values(), key=lambda p: (p.get("date") or "", p.get("time") or "", p.get("game") or ""), reverse=True)


def generate_results_viewer(history_dir=HISTORY_DIR, output_file=OUTPUT_FILE):
    picks = load_history(history_dir)
    generated_at = datetime.now(timezone(timedelta(hours=-6))).isoformat(timespec="seconds")
    json_data = json.dumps(picks, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__PICKS_JSON__", json_data).replace("__GENERATED_AT__", generated_at)
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(html, encoding="utf-8")
    os.replace(temp_path, output_path)
    print(f"[OK] Visualizador de resultados: {output_path} ({len(picks)} picks)")
    return str(output_path)


HTML_TEMPLATE = r'''<!doctype html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sharpie · Resultados</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0} :root{--bg:#0b1329;--panel:#111c40;--panel2:#1e295d;--text:#f8fafc;--muted:#94a3b8;--border:#243572;--teal:#2dd4bf;--green:#22c55e;--red:#fb7185;--amber:#fbbf24;--blue:#60a5fa;--purple:#a78bfa;--shadow:0 10px 25px rgba(0,0,0,.25)}
[data-theme=light]{--bg:#f8fafc;--panel:#fff;--panel2:#f1f5f9;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;--teal:#0d9488;--green:#15803d;--red:#e11d48;--amber:#d97706;--blue:#2563eb;--purple:#7c3aed;--shadow:0 4px 12px rgba(15,23,42,.08)}
body{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);padding:20px;max-width:1680px;margin:auto;overflow-x:hidden}button,select,input{font:inherit}.header,.panel,.kpi,.chart-card{background:var(--panel);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow)}
.header{padding:18px 20px;display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:18px}.brand h1{font-size:25px}.brand h1 span{color:var(--teal)}.brand p,.updated{color:var(--muted);font-size:12px;margin-top:3px}.header-actions{display:flex;align-items:center;gap:10px}.icon-btn{width:42px;height:42px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);color:var(--text);cursor:pointer}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:18px}.kpi{padding:13px 14px;min-width:0}.kpi-label{font-size:9px;color:var(--muted);text-transform:uppercase;font-weight:800;letter-spacing:.55px}.kpi-value{font-size:21px;font-weight:850;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kpi-sub{font-size:10px;color:var(--muted);margin-top:2px}.positive{color:var(--green)!important}.negative{color:var(--red)!important}.neutral{color:var(--amber)!important}
.panel{padding:14px;margin-bottom:18px}.filters{display:grid;grid-template-columns:1.5fr repeat(5,minmax(130px,1fr)) auto;gap:8px}.filters input,.filters select,.filters button{width:100%;min-width:0;padding:9px 10px;border:1px solid var(--border);border-radius:8px;background:var(--panel2);color:var(--text)}.filters button{cursor:pointer;font-weight:700}.check{display:flex!important;align-items:center;justify-content:center;gap:6px;white-space:nowrap}.check input{width:auto}.summary{font-size:12px;color:var(--muted);margin-top:10px}.summary b{color:var(--teal)}
.charts{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:18px}.chart-card{padding:15px;min-width:0}.chart-title{font-weight:800;font-size:13px;margin-bottom:10px}.chart-box{height:230px;position:relative}
.table-panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}.table-wrap{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;min-width:1180px}th{position:sticky;top:0;background:var(--panel2);z-index:1;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.45px;text-align:left;padding:10px 9px;border-bottom:1px solid var(--border)}td{padding:10px 9px;border-bottom:1px solid var(--border);font-size:11px;vertical-align:top}tr:hover td{background:rgba(45,212,191,.035)}.event{font-weight:750;max-width:230px}.pick{font-weight:750;color:var(--teal);max-width:230px}.muted{color:var(--muted)}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.badge{display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;border:1px solid currentColor;font-size:9px;font-weight:850;white-space:nowrap}.WIN{color:var(--green)}.LOSS{color:var(--red)}.PUSH,.VOID{color:var(--amber)}.PENDING,.REVIEW{color:var(--muted)}.VALUE{color:var(--teal)}.PREMIUM{color:var(--purple)}.WHALE{color:var(--blue)}.FREE{color:var(--amber);margin-top:4px}.details-btn{border:1px solid var(--border);background:var(--panel2);color:var(--text);border-radius:7px;padding:5px 8px;cursor:pointer}.pagination{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 14px;color:var(--muted);font-size:11px}.pagination button{padding:7px 12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);border-radius:7px;cursor:pointer}.pagination button:disabled{opacity:.4;cursor:not-allowed}
.empty{text-align:center;padding:50px;color:var(--muted)}dialog{width:min(680px,calc(100vw - 28px));max-height:85vh;overflow:auto;margin:auto;border:1px solid var(--border);border-radius:14px;background:var(--panel);color:var(--text);padding:0;box-shadow:0 30px 80px rgba(0,0,0,.5)}dialog::backdrop{background:rgba(2,6,23,.7)}.modal-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:15px 17px;border-bottom:1px solid var(--border)}.modal-body{padding:16px}.modal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.detail{background:var(--panel2);padding:9px;border-radius:8px;min-width:0}.detail span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase}.detail b{font-size:12px;overflow-wrap:anywhere}.snapshots{margin-top:14px}.snapshots h3{font-size:12px;margin-bottom:7px}.snapshot{display:grid;grid-template-columns:1.3fr repeat(5,1fr);gap:5px;padding:7px;border-bottom:1px solid var(--border);font-size:10px}.close{border:0;background:none;color:var(--text);font-size:21px;cursor:pointer}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.filters{grid-template-columns:repeat(3,1fr)}.charts{grid-template-columns:1fr}}
@media(max-width:680px){body{padding:10px}.header{align-items:flex-start}.brand h1{font-size:20px}.updated{display:none}.kpis{grid-template-columns:repeat(2,1fr)}.filters{grid-template-columns:1fr 1fr}.filters>:first-child{grid-column:1/-1}.chart-box{height:190px}.modal-grid{grid-template-columns:1fr}.snapshot{grid-template-columns:1fr 1fr}.table-wrap{overflow:visible}table,thead,tbody,tr,td{display:block;min-width:0}thead{display:none}tbody{padding:8px}tr{border:1px solid var(--border);border-radius:10px;margin-bottom:9px;padding:9px;background:var(--panel2)}td{display:grid;grid-template-columns:105px minmax(0,1fr);gap:8px;border:0;padding:5px 2px;overflow-wrap:anywhere}td::before{content:attr(data-label);font-size:9px;color:var(--muted);font-weight:800;text-transform:uppercase}.event,.pick{max-width:none}.pagination{flex-wrap:wrap}}
@media(max-width:390px){.kpis,.filters{grid-template-columns:1fr}.filters>:first-child{grid-column:auto}.kpi-value{font-size:19px}}
</style></head>
<body>
<header class="header"><div class="brand"><h1>Sharp<span>IE</span> · Resultados</h1><p>Rendimiento histórico de picks con valor</p></div><div class="header-actions"><div class="updated">Actualizado<br><b>__GENERATED_AT__</b></div><button id="theme" class="icon-btn" title="Cambiar tema">🌓</button></div></header>
<section class="kpis">
<div class="kpi"><div class="kpi-label">Picks liquidados</div><div id="kSettled" class="kpi-value">0</div><div id="kTotalSub" class="kpi-sub">0 históricos</div></div>
<div class="kpi"><div class="kpi-label">Récord</div><div id="kRecord" class="kpi-value">0-0-0</div><div class="kpi-sub">WIN · LOSS · PUSH</div></div>
<div class="kpi"><div class="kpi-label">Balance</div><div id="kUnits" class="kpi-value">0.00u</div><div class="kpi-sub">Ganancia/pérdida neta</div></div>
<div class="kpi"><div class="kpi-label">ROI</div><div id="kRoi" class="kpi-value">0.00%</div><div id="kRisked" class="kpi-sub">0.00u apostadas</div></div>
<div class="kpi"><div class="kpi-label">Win rate</div><div id="kWinRate" class="kpi-value">0.00%</div><div class="kpi-sub">Sin contar push/void</div></div>
<div class="kpi"><div class="kpi-label">Incidencias ESPN</div><div id="kPending" class="kpi-value">0</div><div id="kReview" class="kpi-sub">Fuera de resultados</div></div>
</section>
<section class="panel"><div class="filters">
<input id="search" placeholder="Buscar evento, pick o liga">
<select id="range"><option value="2" selected>Hoy y ayer</option><option value="1">Hoy</option><option value="7">Últimos 7 días</option><option value="30">Últimos 30 días</option><option value="all">Todo el historial</option><option value="custom">Rango personalizado</option></select>
<input id="dateFrom" type="date" title="Desde"><input id="dateTo" type="date" title="Hasta">
<select id="league"><option value="">Todas las ligas</option></select>
<select id="category"><option value="">Todas las categorías</option><option>VALUE</option><option>PREMIUM</option><option>WHALE</option></select>
<select id="result"><option value="SETTLED" selected>Solo liquidados</option><option value="">Todos los estados</option><option>WIN</option><option>LOSS</option><option>PUSH</option><option>VOID</option><option>PENDING</option><option>REVIEW</option></select>
<label class="check"><input id="freeOnly" type="checkbox"> Free Release</label>
<button id="clear">Limpiar</button>
</div><div class="summary">Mostrando <b id="shown">0</b> de <b id="total">0</b> picks con valor</div></section>
<section class="charts"><article class="chart-card"><div class="chart-title">📈 Balance acumulado por fecha</div><div class="chart-box"><canvas id="unitsChart"></canvas></div></article><article class="chart-card"><div class="chart-title">🎯 Distribución de resultados</div><div class="chart-box"><canvas id="resultChart"></canvas></div></article></section>
<section class="table-panel"><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Evento</th><th>Pick</th><th>Categoría</th><th>Cuota</th><th>Stake</th><th>Modelo</th><th>Edge</th><th>EV</th><th>Resultado</th><th>Marcador</th><th>Balance</th><th></th></tr></thead><tbody id="rows"></tbody></table><div id="empty" class="empty" hidden>No existen resultados con estos filtros.</div></div><div class="pagination"><span id="pageInfo"></span><div><button id="prev">← Anterior</button> <button id="next">Siguiente →</button></div></div></section>
<dialog id="detailModal"><div class="modal-head"><b id="modalTitle">Detalle</b><button class="close" id="closeModal">×</button></div><div id="modalBody" class="modal-body"></div></dialog>
<script>const PICKS=__PICKS_JSON__;let filtered=[],scoped=[],page=1;const PAGE_SIZE=50;let unitsChart,resultChart;
const $=id=>document.getElementById(id);const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const num=v=>Number.isFinite(Number(v))?Number(v):0;const fmt=(v,d=2)=>num(v).toFixed(d);const finalSet=new Set(['WIN','LOSS','PUSH','VOID']);
function populate(){const leagues=[...new Set(PICKS.map(p=>p.league).filter(Boolean))].sort();$('league').innerHTML='<option value="">Todas las ligas</option>'+leagues.map(v=>`<option>${esc(v)}</option>`).join('')}
function isoDate(date){return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,10)}function setRange(value){const today=new Date(),end=isoDate(today);$('dateTo').value=end;if(value==='all'){$('dateFrom').value='';return}if(value==='custom')return;const days=Math.max(1,Number(value)||2),start=new Date(today);start.setDate(start.getDate()-(days-1));$('dateFrom').value=isoDate(start)}
function apply(){const q=$('search').value.toLowerCase().trim(),from=$('dateFrom').value,to=$('dateTo').value,league=$('league').value,cat=$('category').value,res=$('result').value,free=$('freeOnly').checked,today=isoDate(new Date());scoped=PICKS.filter(p=>{const blob=`${p.game||''} ${p.pick||''} ${p.league||''} ${p.market||''}`.toLowerCase(),date=p.date||'';return date<=today&&(!q||blob.includes(q))&&(!from||date>=from)&&(!to||date<=to)&&(!league||p.league===league)&&(!cat||p.pickCategory===cat)&&(!free||p.freeRelease)});filtered=scoped.filter(p=>!res||(res==='SETTLED'?finalSet.has(p.result):p.result===res));page=1;render()}
function metrics(){const settled=filtered.filter(p=>finalSet.has(p.result)),wins=settled.filter(p=>p.result==='WIN').length,losses=settled.filter(p=>p.result==='LOSS').length,push=settled.filter(p=>p.result==='PUSH').length,units=settled.reduce((s,p)=>s+num(p.profitUnits),0),risk=settled.filter(p=>p.result!=='VOID').reduce((s,p)=>s+num(p.stake),0),pending=scoped.filter(p=>p.result==='PENDING').length,review=scoped.filter(p=>p.result==='REVIEW').length,roi=risk?units/risk*100:0,wr=wins+losses?wins/(wins+losses)*100:0;$('kSettled').textContent=settled.length;$('kTotalSub').textContent=`${filtered.length} visibles`;$('kRecord').textContent=`${wins}-${losses}-${push}`;$('kUnits').textContent=`${units>=0?'+':''}${fmt(units)}u`;$('kRoi').textContent=`${roi>=0?'+':''}${fmt(roi)}%`;$('kRisked').textContent=`${fmt(risk)}u apostadas`;$('kWinRate').textContent=`${fmt(wr)}%`;$('kPending').textContent=pending+review;$('kReview').textContent=`${review} revisión · ${pending} en curso`;$('kUnits').className='kpi-value '+(units>=0?'positive':'negative');$('kRoi').className='kpi-value '+(roi>=0?'positive':'negative')}
function score(p){const s=p.settlement||{};return s.awayScore!=null&&s.homeScore!=null?`${s.awayScore}-${s.homeScore}`:'—'}
function renderRows(){const start=(page-1)*PAGE_SIZE,items=filtered.slice(start,start+PAGE_SIZE);$('rows').innerHTML=items.map((p,i)=>`<tr><td data-label="Fecha"><span class="mono">${esc(p.date)}<br>${esc(p.time||'')}</span></td><td data-label="Evento"><div class="event">${esc(p.game)}</div><span class="muted">${esc(p.league)}</span></td><td data-label="Pick"><div class="pick">${esc(p.pick)}</div><span class="muted">${esc(p.market)}</span></td><td data-label="Categoría"><span class="badge ${esc(p.pickCategory)}">${esc(p.pickCategory)}</span>${p.freeRelease?'<br><span class="badge FREE">FREE RELEASE</span>':''}</td><td data-label="Cuota" class="mono">${esc(p.odds)}</td><td data-label="Stake" class="mono">${fmt(p.stake,1)}u</td><td data-label="Modelo" class="mono">${fmt(p.modelProb)}%</td><td data-label="Edge" class="mono">${num(p.modelEdge)>=0?'+':''}${fmt(p.modelEdge)}%</td><td data-label="EV" class="mono">${num(p.ev)>=0?'+':''}${fmt(p.ev)}%</td><td data-label="Resultado"><span class="badge ${esc(p.result)}">${esc(p.result)}</span></td><td data-label="Marcador" class="mono">${score(p)}</td><td data-label="Balance" class="mono ${num(p.profitUnits)>0?'positive':num(p.profitUnits)<0?'negative':''}">${p.profitUnits==null?'—':`${num(p.profitUnits)>=0?'+':''}${fmt(p.profitUnits)}u`}</td><td data-label="Detalle"><button class="details-btn" data-index="${start+i}">Ver</button></td></tr>`).join('');$('empty').hidden=items.length>0;$('rows').hidden=items.length===0;document.querySelectorAll('.details-btn').forEach(b=>b.onclick=()=>openDetail(filtered[Number(b.dataset.index)]));const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));$('pageInfo').textContent=`Página ${page} de ${pages}`;$('prev').disabled=page<=1;$('next').disabled=page>=pages}
function charts(){const settled=[...filtered].filter(p=>finalSet.has(p.result)).sort((a,b)=>(a.date||'').localeCompare(b.date||'')),byDate={};settled.forEach(p=>byDate[p.date]=(byDate[p.date]||0)+num(p.profitUnits));let acc=0;const labels=Object.keys(byDate).sort(),values=labels.map(d=>acc+=byDate[d]);const dark=document.documentElement.dataset.theme!=='light',text=dark?'#94a3b8':'#64748b',grid=dark?'#243572':'#e2e8f0';if(unitsChart)unitsChart.destroy();unitsChart=new Chart($('unitsChart'),{type:'line',data:{labels,datasets:[{data:values,borderColor:'#2dd4bf',backgroundColor:'rgba(45,212,191,.12)',fill:true,tension:.25,pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:text,maxTicksLimit:8},grid:{color:grid}},y:{ticks:{color:text,callback:v=>v+'u'},grid:{color:grid}}}}});const counts=['WIN','LOSS','PUSH','VOID','PENDING','REVIEW'].map(r=>filtered.filter(p=>p.result===r).length),active=['WIN','LOSS','PUSH','VOID','PENDING','REVIEW'].map((r,i)=>({r,n:counts[i],c:['#22c55e','#fb7185','#fbbf24','#64748b','#60a5fa','#a78bfa'][i]})).filter(x=>x.n);if(resultChart)resultChart.destroy();resultChart=new Chart($('resultChart'),{type:'doughnut',data:{labels:active.map(x=>x.r),datasets:[{data:active.map(x=>x.n),backgroundColor:active.map(x=>x.c),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'67%',plugins:{legend:{position:'bottom',labels:{color:text,boxWidth:10}}}}})}
function detail(label,value){return `<div class="detail"><span>${esc(label)}</span><b>${esc(value)}</b></div>`}function sourceLink(url){return /^https:\/\//i.test(url||'')?`<p style="margin-top:12px"><a href="${esc(url)}" target="_blank" rel="noopener" style="color:var(--teal)">Abrir consulta original de ESPN ↗</a></p>`:''}function openDetail(p){const s=p.settlement||{},e=p.eventLookup||{},snaps=Array.isArray(p.qualificationSnapshots)?p.qualificationSnapshots:[];$('modalTitle').textContent=p.pick||'Detalle';$('modalBody').innerHTML=`<div class="modal-grid">${detail('Evento',p.game||p.event)}${detail('Fecha y hora',`${p.date||'—'} ${p.time||''}`)}${detail('Liga registrada',p.league)}${detail('Ruta ESPN',e.espnSport&&e.espnLeague?`${e.espnSport}/${e.espnLeague}`:'Sin identificar')}${detail('Mercado',p.market)}${detail('Pick',p.pick)}${detail('Cuota',p.odds)}${detail('Stake',`${fmt(p.stake,1)}u`)}${detail('Categoría',p.pickCategory)}${detail('Señal',p.marketSignal)}${detail('Modelo',`${fmt(p.modelProb)}%`)}${detail('Edge',`${fmt(p.modelEdge)}%`)}${detail('EV',`${fmt(p.ev)}%`)}${detail('Bets / Handle',`${fmt(p.betsPct)}% / ${fmt(p.handlePct)}%`)}${detail('Divergencia',`${fmt(p.signedDivergence??p.divergence)}%`)}${detail('Resultado',p.result)}${detail('Balance',p.profitUnits==null?'—':fmt(p.profitUnits)+'u')}${detail('Marcador',score(p))}${detail('Fuente',s.source||e.provider||'—')}${detail('ESPN Event ID',s.eventId||e.eventId||'—')}${detail('Coincidencia',s.matchConfidence??e.matchConfidence??'—')}${detail('Estado del cotejo',e.matchStatus||'—')}${detail('Causa',s.failureCode||s.notes||'—')}${detail('Mejor candidato',e.bestCandidate||'—')}${detail('Rutas consultadas',(e.attemptedRoutes||[]).join(', ')||'—')}${detail('Fechas consultadas',(e.attemptedDates||[]).join(', ')||'—')}${detail('Primera calificación',p.firstQualifiedAt)}${detail('Última versión viable',p.lastQualifiedAt)}${detail('Archivo',p.historyFile)}${detail('Snapshots',snaps.length)}</div>${sourceLink(s.sourceUrl)}${snaps.length?`<div class="snapshots"><h3>Evolución mientras conservó valor</h3>${snaps.map(x=>`<div class="snapshot"><span>${esc(x.observedAt)}</span><span>Cuota ${esc(x.odds)}</span><span>EV ${fmt(x.ev)}%</span><span>Edge ${fmt(x.modelEdge)}%</span><span>${fmt(x.stake,1)}u</span><span>${esc(x.marketSignal)}</span></div>`).join('')}</div>`:''}`;const modal=$('detailModal');if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','')}
function render(){$('shown').textContent=filtered.length;$('total').textContent=scoped.length;metrics();renderRows();charts()}['search','league','category','result','freeOnly'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',apply));$('range').onchange=()=>{setRange($('range').value);apply()};['dateFrom','dateTo'].forEach(id=>$(id).onchange=()=>{$('range').value='custom';apply()});$('clear').onclick=()=>{$('search').value='';$('league').value='';$('category').value='';$('result').value='SETTLED';$('freeOnly').checked=false;$('range').value='2';setRange('2');apply()};$('prev').onclick=()=>{page--;renderRows();scrollTo(0,0)};$('next').onclick=()=>{page++;renderRows();scrollTo(0,0)};$('closeModal').onclick=()=>$('detailModal').close();$('detailModal').onclick=e=>{if(e.target===$('detailModal'))$('detailModal').close()};$('theme').onclick=()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light';charts()};populate();setRange('2');apply();</script>
</body></html>'''


if __name__ == "__main__":
    generate_results_viewer()
