const PICKS = __PICKS_JSON__;
const TODAY_CDMX = '__TODAY_CDMX__';
const PAGE_SIZE = 50;
const finalSet = new Set(['WIN','HALF_WIN','LOSS','HALF_LOSS','PUSH','VOID']);
let filtered = [], scoped = [], page = 1;
let unitsChart, resultChart, calibrationChart;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const fmt = (value, digits=2) => num(value).toFixed(digits);

function populate() {
    const leagues = [...new Set(PICKS.map(pick => pick.league).filter(Boolean))].sort();
    $('league').innerHTML = '<option value="">Todas las ligas</option>' + leagues.map(value => `<option>${esc(value)}</option>`).join('');
}

function shiftIsoDate(iso, days) {
    const date = new Date(`${iso}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

function setRange(value) {
    const custom = value === 'custom';
    $('customDates').hidden = !custom;
    $('dateFrom').disabled = !custom;
    $('dateTo').disabled = !custom;
    if (custom) return;
    if (value === 'all') { $('dateFrom').value = ''; $('dateTo').value = ''; return; }
    if (value === 'yesterday') {
        const yesterday = shiftIsoDate(TODAY_CDMX, -1);
        $('dateFrom').value = yesterday; $('dateTo').value = yesterday; return;
    }
    $('dateTo').value = TODAY_CDMX;
    if (value === 'today') { $('dateFrom').value = TODAY_CDMX; return; }
    const days = Math.max(1, Number(value) || 7);
    $('dateFrom').value = shiftIsoDate(TODAY_CDMX, -(days - 1));
}

function apply() {
    const q = $('search').value.toLowerCase().trim();
    const from = $('dateFrom').value, to = $('dateTo').value;
    const league = $('league').value, category = $('category').value, result = $('result').value;
    const free = $('freeOnly').checked, stake = $('stake').value;
    const oddsMin = $('oddsMin').value, oddsMax = $('oddsMax').value;
    const modelMin = $('modelMin').value, modelMax = $('modelMax').value;
    const divergenceMin = $('divergenceMin').value, divergenceMax = $('divergenceMax').value;
    const edgeMin = $('edgeMin').value, evMin = $('evMin').value;
    scoped = PICKS.filter(pick => {
        const blob = `${pick.game||''} ${pick.pick||''} ${pick.league||''} ${pick.market||''}`.toLowerCase();
        const date = pick.date || '';
        return date <= TODAY_CDMX && num(pick.ev) > 0 && num(pick.modelEdge) > 0 &&
            (!q || blob.includes(q)) && (!from || date >= from) && (!to || date <= to) &&
            (!league || pick.league === league) && (!category || pick.pickCategory === category) &&
            (!stake || num(pick.stake) === num(stake)) &&
            (!oddsMin || num(pick.odds) >= num(oddsMin)) && (!oddsMax || num(pick.odds) <= num(oddsMax)) &&
            (!modelMin || num(pick.modelProb) >= num(modelMin)) && (!modelMax || num(pick.modelProb) <= num(modelMax)) &&
            (!divergenceMin || num(pick.signedDivergence ?? pick.divergence) >= num(divergenceMin)) &&
            (!divergenceMax || num(pick.signedDivergence ?? pick.divergence) <= num(divergenceMax)) &&
            (!edgeMin || num(pick.modelEdge) >= num(edgeMin)) && (!evMin || num(pick.ev) >= num(evMin)) &&
            (!free || pick.freeRelease);
    });
    filtered = scoped.filter(pick => !result || (result === 'SETTLED' ? finalSet.has(pick.result) : pick.result === result));
    page = 1;
    render();
}

function probabilityOutcome(result) {
    return {WIN:1, HALF_WIN:.75, HALF_LOSS:.25, LOSS:0}[result];
}

function diagnostics(settled) {
    const valid = settled.map(pick => ({pick, predicted:num(pick.modelProb)/100, actual:probabilityOutcome(pick.result)}))
        .filter(row => row.actual !== undefined && row.predicted > 0 && row.predicted < 1);
    if (!valid.length) return {brier:null, calibration:null, buckets:[], drawdown:0};
    const brier = valid.reduce((sum,row) => sum + (row.predicted-row.actual)**2, 0) / valid.length;
    const buckets = new Map();
    valid.forEach(row => {
        const index = Math.min(9, Math.floor(row.predicted*10));
        const bucket = buckets.get(index) || {count:0,predicted:0,actual:0};
        bucket.count++; bucket.predicted += row.predicted; bucket.actual += row.actual; buckets.set(index,bucket);
    });
    let calibration = 0;
    const points = [...buckets.entries()].sort((a,b)=>a[0]-b[0]).map(([index,bucket]) => {
        const predicted = bucket.predicted/bucket.count, actual = bucket.actual/bucket.count;
        calibration += bucket.count/valid.length*Math.abs(predicted-actual);
        return {label:`${index*10}-${(index+1)*10}%`, predicted:predicted*100, actual:actual*100, count:bucket.count};
    });
    let cumulative=0, peak=0, drawdown=0;
    [...settled].sort((a,b)=>`${a.date||''}${a.time||''}`.localeCompare(`${b.date||''}${b.time||''}`)).forEach(pick => {
        cumulative += num(pick.profitUnits); peak = Math.max(peak,cumulative); drawdown = Math.max(drawdown,peak-cumulative);
    });
    return {brier, calibration:calibration*100, buckets:points, drawdown};
}

function metrics() {
    const settled = filtered.filter(pick => finalSet.has(pick.result));
    const wins = settled.filter(p=>p.result==='WIN').length + settled.filter(p=>p.result==='HALF_WIN').length*.5;
    const losses = settled.filter(p=>p.result==='LOSS').length + settled.filter(p=>p.result==='HALF_LOSS').length*.5;
    const push = settled.filter(p=>p.result==='PUSH').length;
    const units = settled.reduce((sum,pick)=>sum+num(pick.profitUnits),0);
    const risk = settled.filter(p=>p.result!=='VOID').reduce((sum,pick)=>sum+num(pick.stake),0);
    const review = scoped.filter(p=>p.result==='REVIEW').length;
    const pending = scoped.filter(p=>p.result==='PENDING');
    const live = pending.filter(p=>((p.settlement||{}).failureCode||'')==='EVENT_IN_PROGRESS').length;
    const waiting = pending.filter(p=>!['NOT_STARTED_FUTURE','NOT_STARTED_SCHEDULED','EVENT_IN_PROGRESS'].includes(((p.settlement||{}).failureCode||''))).length;
    const roi = risk ? units/risk*100 : 0, winRate = wins+losses ? wins/(wins+losses)*100 : 0;
    const model = diagnostics(settled);
    $('kSettled').textContent=settled.length; $('kTotalSub').textContent=`${filtered.length} visibles`;
    $('kRecord').textContent=`${wins}-${losses}-${push}`; $('kUnits').textContent=`${units>=0?'+':''}${fmt(units)}u`;
    $('kRoi').textContent=`${roi>=0?'+':''}${fmt(roi)}%`; $('kRisked').textContent=`${fmt(risk)}u apostadas`;
    $('kYield').textContent=`${roi>=0?'+':''}${fmt(roi)}%`; $('kYield').className='kpi-value '+(roi>=0?'positive':'negative');
    $('kWinRate').textContent=`${fmt(winRate)}%`; $('kPending').textContent=review;
    const notes=[review?`${review} requieren intervención`:'Sin incidencias reales']; if(live)notes.push(`${live} en juego`); if(waiting)notes.push(`${waiting} esperando confirmación`); $('kReview').textContent=notes.join(' · ');
    $('kBrier').textContent=model.brier==null?'—':model.brier.toFixed(4); $('kCalibration').textContent=model.calibration==null?'—':`${model.calibration.toFixed(2)}%`; $('kDrawdown').textContent=`-${model.drawdown.toFixed(2)}u`;
    $('kUnits').className='kpi-value '+(units>=0?'positive':'negative'); $('kRoi').className='kpi-value '+(roi>=0?'positive':'negative');
    return model;
}

function score(pick) {
    const settlement=pick.settlement||{}; if(settlement.awayScore==null||settlement.homeScore==null)return'—';
    return /\s@\s/.test(pick.game||'')?`${settlement.awayScore}-${settlement.homeScore}`:`${settlement.homeScore}-${settlement.awayScore}`;
}

function renderRows() {
    const start=(page-1)*PAGE_SIZE, items=filtered.slice(start,start+PAGE_SIZE);
    $('rows').innerHTML=items.map((pick,index)=>`<tr><td data-label="Fecha"><span class="mono">${esc(pick.date)}<br>${esc(pick.time||'')}</span></td><td data-label="Evento"><div class="event">${esc(pick.game)}</div><span class="muted">${esc(pick.league)}</span></td><td data-label="Pick"><div class="pick">${esc(pick.pick)}</div><span class="muted">${esc(pick.market)}</span></td><td data-label="Categoría"><span class="badge ${esc(pick.pickCategory)}">${esc(pick.pickCategory)}</span>${pick.freeRelease?'<br><span class="badge FREE">FREE RELEASE</span>':''}</td><td data-label="Cuota" class="mono">${esc(pick.odds)}</td><td data-label="Stake" class="mono">${fmt(pick.stake,1)}u</td><td data-label="Modelo" class="mono">${fmt(pick.modelProb)}%</td><td data-label="Edge" class="mono">${num(pick.modelEdge)>=0?'+':''}${fmt(pick.modelEdge)}%</td><td data-label="EV" class="mono">${num(pick.ev)>=0?'+':''}${fmt(pick.ev)}%</td><td data-label="Resultado"><span class="badge ${esc(pick.result)}">${esc(pick.result)}</span></td><td data-label="Marcador" class="mono">${score(pick)}</td><td data-label="Balance" class="mono ${num(pick.profitUnits)>0?'positive':num(pick.profitUnits)<0?'negative':''}">${pick.profitUnits==null?'—':`${num(pick.profitUnits)>=0?'+':''}${fmt(pick.profitUnits)}u`}</td><td data-label="Detalle"><button class="details-btn" data-index="${start+index}">Ver</button></td></tr>`).join('');
    $('empty').hidden=items.length>0; $('rows').hidden=items.length===0;
    document.querySelectorAll('.details-btn').forEach(button=>button.onclick=()=>openDetail(filtered[Number(button.dataset.index)]));
    const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE)); $('pageInfo').textContent=`Página ${page} de ${pages}`; $('prev').disabled=page<=1; $('next').disabled=page>=pages;
}

function charts(model) {
    if(typeof Chart==='undefined')return;
    const settled=[...filtered].filter(p=>finalSet.has(p.result)).sort((a,b)=>(a.date||'').localeCompare(b.date||'')), byDate={};
    settled.forEach(p=>byDate[p.date]=(byDate[p.date]||0)+num(p.profitUnits)); let acc=0;
    const labels=Object.keys(byDate).sort(), values=labels.map(date=>acc+=byDate[date]);
    const dark=document.documentElement.dataset.theme!=='light', text=dark?'#94a3b8':'#64748b', grid=dark?'#243572':'#e2e8f0';
    if(unitsChart)unitsChart.destroy(); unitsChart=new Chart($('unitsChart'),{type:'line',data:{labels,datasets:[{data:values,borderColor:'#2dd4bf',backgroundColor:'rgba(45,212,191,.12)',fill:true,tension:.25,pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:text,maxTicksLimit:8},grid:{color:grid}},y:{ticks:{color:text,callback:v=>v+'u'},grid:{color:grid}}}}});
    const states=['WIN','HALF_WIN','LOSS','HALF_LOSS','PUSH','VOID','PENDING','REVIEW'], colors=['#22c55e','#86efac','#fb7185','#fda4af','#fbbf24','#64748b','#60a5fa','#a78bfa'];
    const active=states.map((result,index)=>({result,count:filtered.filter(p=>p.result===result).length,color:colors[index]})).filter(item=>item.count);
    if(resultChart)resultChart.destroy(); resultChart=new Chart($('resultChart'),{type:'doughnut',data:{labels:active.map(x=>x.result),datasets:[{data:active.map(x=>x.count),backgroundColor:active.map(x=>x.color),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'67%',plugins:{legend:{position:'bottom',labels:{color:text,boxWidth:10}}}}});
    if(calibrationChart)calibrationChart.destroy();
    calibrationChart=new Chart($('calibrationChart'),{type:'line',data:{labels:model.buckets.map(x=>x.label),datasets:[{label:'Pronóstico',data:model.buckets.map(x=>x.predicted),borderColor:'#60a5fa',tension:.2},{label:'Real',data:model.buckets.map(x=>x.actual),borderColor:'#2dd4bf',tension:.2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:text,boxWidth:10}}},scales:{x:{ticks:{color:text,maxTicksLimit:6},grid:{color:grid}},y:{min:0,max:100,ticks:{color:text,callback:v=>v+'%'},grid:{color:grid}}}}});
}

function detail(label,value){return `<div class="detail"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;}
function sourceLink(url){return /^https:\/\//i.test(url||'')?`<p style="margin-top:12px"><a href="${esc(url)}" target="_blank" rel="noopener" style="color:var(--teal)">Abrir consulta original de ESPN ↗</a></p>`:'';}
function openDetail(pick){
    const settlement=pick.settlement||{}, event=pick.eventLookup||{}, snapshots=Array.isArray(pick.qualificationSnapshots)?pick.qualificationSnapshots:[];
    $('modalTitle').textContent=pick.pick||'Detalle';
    $('modalBody').innerHTML=`<div class="modal-grid">${detail('Evento',pick.game||pick.event)}${detail('Fecha y hora',`${pick.date||'—'} ${pick.time||''}`)}${detail('Liga registrada',pick.league)}${detail('Mercado',pick.market)}${detail('Pick',pick.pick)}${detail('Cuota',pick.odds)}${detail('Stake',`${fmt(pick.stake,1)}u`)}${detail('Categoría',pick.pickCategory)}${detail('Señal',pick.marketSignal)}${detail('Modelo',`${fmt(pick.modelProb)}%`)}${detail('Edge',`${fmt(pick.modelEdge)}%`)}${detail('EV',`${fmt(pick.ev)}%`)}${detail('Bets / Handle',`${fmt(pick.betsPct)}% / ${fmt(pick.handlePct)}%`)}${detail('Divergencia',`${fmt(pick.signedDivergence??pick.divergence)}%`)}${detail('Resultado',pick.result)}${detail('Balance',pick.profitUnits==null?'—':fmt(pick.profitUnits)+'u')}${detail('Marcador',score(pick))}${detail('Ruta ESPN',event.espnSport&&event.espnLeague?`${event.espnSport}/${event.espnLeague}`:'Sin identificar')}${detail('ESPN Event ID',settlement.eventId||event.eventId||'—')}${detail('Estado del cotejo',event.matchStatus||'—')}${detail('Causa',settlement.failureCode||settlement.notes||'—')}${detail('Primera calificación',pick.firstQualifiedAt)}${detail('Última versión viable',pick.lastQualifiedAt)}${detail('Archivo',pick.historyFile)}${detail('Snapshots',snapshots.length)}</div>${sourceLink(settlement.sourceUrl)}`;
    const modal=$('detailModal'); if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','');
}

function render(){ $('shown').textContent=filtered.length; $('total').textContent=scoped.length; const model=metrics(); renderRows(); charts(model); }

function csvCell(value) {
    const text = String(value ?? '').replace(/\r?\n/g, ' ').replace(/"/g, '""');
    return `"${text}"`;
}

function exportCsv() {
    if (!filtered.length) return;
    const headers = ['Fecha','Hora','Liga','Evento','Mercado','Pick','Categoría','Cuota','Stake','Modelo %','Divergencia %','Edge %','EV %','Bets %','Handle %','Resultado','Marcador','Balance unidades'];
    const rows = filtered.map(pick => [pick.date,pick.time,pick.league,pick.game,pick.market,pick.pick,pick.pickCategory,pick.odds,pick.stake,pick.modelProb,pick.signedDivergence ?? pick.divergence,pick.modelEdge,pick.ev,pick.betsPct,pick.handlePct,pick.result,score(pick),pick.profitUnits]);
    const csv = '\uFEFFsep=,\r\n' + [headers, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n');
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'}), url = URL.createObjectURL(blob), link = document.createElement('a');
    const range = $('range').value, suffix = range === 'custom' ? `${$('dateFrom').value || 'inicio'}_${$('dateTo').value || 'fin'}` : range;
    link.href = url; link.download = `sharpie-resultados-${suffix}-${TODAY_CDMX}.csv`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}

function bucket(value, cuts, labels) {
    const current=num(value); for(let index=0;index<cuts.length;index++)if(current<cuts[index])return labels[index]; return labels[labels.length-1];
}

function segmentDimensions(pick) {
    const divergence=pick.signedDivergence ?? pick.divergence;
    return {
        'Categoría':pick.pickCategory||'Sin categoría', 'Liga':pick.league||'Sin liga', 'Mercado':pick.market||'Sin mercado',
        'Cuota':bucket(pick.odds,[-150,-110,101,151,251],['≤ -151','-150 a -111','-110 a +100','+101 a +150','+151 a +250','≥ +251']),
        'Stake':`${fmt(pick.stake,1)}u`,
        'Modelo':bucket(pick.modelProb,[55,60,65,70],['<55%','55–59.9%','60–64.9%','65–69.9%','≥70%']),
        'Edge':bucket(pick.modelEdge,[5,10,15,25],['<5%','5–9.9%','10–14.9%','15–24.9%','≥25%']),
        'EV':bucket(pick.ev,[5,10,15,25],['<5%','5–9.9%','10–14.9%','15–24.9%','≥25%']),
        'Divergencia':bucket(divergence,[0,10,20,35],['Negativa','0–9.9%','10–19.9%','20–34.9%','≥35%'])
    };
}

function analyzeSegments() {
    const settled=filtered.filter(pick=>finalSet.has(pick.result));
    $('analysisScope').textContent=`${settled.length} picks liquidados · respeta los filtros activos`;
    if(!settled.length){$('analysisBody').innerHTML='<div class="analysis-empty">No hay picks liquidados suficientes dentro de los filtros actuales.</div>';openAnalysis();return;}
    const minSample=Math.max(3,Math.ceil(settled.length*.03)), groups=new Map();
    const add=(label,pick)=>{const row=groups.get(label)||{label,count:0,risk:0,profit:0,wins:0,losses:0};row.count++;row.risk+=pick.result==='VOID'?0:num(pick.stake);row.profit+=num(pick.profitUnits);if(['WIN','HALF_WIN'].includes(pick.result))row.wins++;if(['LOSS','HALF_LOSS'].includes(pick.result))row.losses++;groups.set(label,row);};
    settled.forEach(pick=>{const dimensions=segmentDimensions(pick), entries=Object.entries(dimensions);entries.forEach(([name,value])=>add(`${name}: ${value}`,pick));for(let left=0;left<entries.length;left++)for(let right=left+1;right<entries.length;right++)add(`${entries[left][0]}: ${entries[left][1]} · ${entries[right][0]}: ${entries[right][1]}`,pick);});
    const segments=[...groups.values()].filter(row=>row.count>=minSample&&row.risk>0).map(row=>({...row,yield:row.profit/row.risk*100}));
    const profitable=segments.filter(row=>row.profit>0).sort((a,b)=>b.yield-a.yield||b.count-a.count).slice(0,8);
    const losing=segments.filter(row=>row.profit<0).sort((a,b)=>a.yield-b.yield||b.count-a.count).slice(0,8);
    const totalProfit=settled.reduce((sum,pick)=>sum+num(pick.profitUnits),0),totalRisk=settled.filter(pick=>pick.result!=='VOID').reduce((sum,pick)=>sum+num(pick.stake),0),totalYield=totalRisk?totalProfit/totalRisk*100:0;
    const renderSegment=row=>`<div class="segment"><div><div class="segment-title">${esc(row.label)}</div><div class="segment-meta">${row.count} picks · ${fmt(row.risk)}u apostadas · ${row.wins} favorables / ${row.losses} desfavorables</div></div><div class="segment-result ${row.profit>=0?'positive':'negative'}">${row.profit>=0?'+':''}${fmt(row.profit)}u<small>Yield ${row.yield>=0?'+':''}${fmt(row.yield)}%</small></div></div>`;
    const best=profitable[0],worst=losing[0];
    $('analysisBody').innerHTML=`<div class="analysis-overview"><div class="analysis-stat"><span>Muestra</span><b>${settled.length}</b></div><div class="analysis-stat"><span>Balance</span><b class="${totalProfit>=0?'positive':'negative'}">${totalProfit>=0?'+':''}${fmt(totalProfit)}u</b></div><div class="analysis-stat"><span>Yield</span><b class="${totalYield>=0?'positive':'negative'}">${totalYield>=0?'+':''}${fmt(totalYield)}%</b></div><div class="analysis-stat"><span>Muestra mínima</span><b>${minSample} picks</b></div></div><div class="analysis-note">Se probaron variables individuales y todos los cruces de dos variables. Los resultados describen el historial filtrado; no garantizan rendimiento futuro. Los segmentos con menos de ${minSample} picks fueron descartados para reducir conclusiones por muestras aisladas.${best?` La mayor concentración positiva aparece en <b>${esc(best.label)}</b>.`:''}${worst?` La principal fuga aparece en <b>${esc(worst.label)}</b>.`:''}</div><div class="analysis-columns"><section class="analysis-section"><h3 class="positive">Dónde están las ganancias</h3><div class="segment-list">${profitable.length?profitable.map(renderSegment).join(''):'<div class="analysis-empty">No se detectaron segmentos rentables con muestra suficiente.</div>'}</div></section><section class="analysis-section"><h3 class="negative">Dónde están las pérdidas</h3><div class="segment-list">${losing.length?losing.map(renderSegment).join(''):'<div class="analysis-empty">No se detectaron segmentos perdedores con muestra suficiente.</div>'}</div></section></div>`;
    openAnalysis();
}

function openAnalysis(){const modal=$('analysisModal');if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','');}

const numericFilters=['oddsMin','oddsMax','modelMin','modelMax','divergenceMin','divergenceMax','edgeMin','evMin'];
['search','league','category','stake',...numericFilters,'result','freeOnly'].forEach(id=>$(id).addEventListener(id==='search'||numericFilters.includes(id)?'input':'change',apply));
$('range').onchange=()=>{setRange($('range').value);apply();}; ['dateFrom','dateTo'].forEach(id=>$(id).onchange=()=>{$('range').value='custom';apply();});
$('clear').onclick=()=>{$('search').value='';$('league').value='';$('category').value='';$('stake').value='';numericFilters.forEach(id=>$(id).value='');$('result').value='SETTLED';$('freeOnly').checked=false;$('range').value='today';setRange('today');apply();};
$('export').onclick=exportCsv;
$('analyze').onclick=analyzeSegments;
$('prev').onclick=()=>{page--;renderRows();scrollTo(0,0);}; $('next').onclick=()=>{page++;renderRows();scrollTo(0,0);};
$('closeModal').onclick=()=>$('detailModal').close(); $('detailModal').onclick=event=>{if(event.target===$('detailModal'))$('detailModal').close();};
$('closeAnalysis').onclick=()=>$('analysisModal').close(); $('analysisModal').onclick=event=>{if(event.target===$('analysisModal'))$('analysisModal').close();};
$('theme').onclick=()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light';charts(diagnostics(filtered.filter(p=>finalSet.has(p.result))));};
populate(); setRange('today'); apply();
