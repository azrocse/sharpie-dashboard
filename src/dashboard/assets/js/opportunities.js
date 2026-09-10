'use strict';
let archive = window.OPPORTUNITIES;
let page = 0;
const pageSize = 20;
const byId = id => document.getElementById(id);
const bounds = {model:'modelProb', edge:'modelEdge', ev:'ev', stake:'stake', odds:'odds', bets:'betsPct', handle:'handlePct', divergence:'divergence'};
const filterIds = ['search','date','from','to','league','market','signal','category','sort', ...Object.keys(bounds).flatMap(key => [key+'Min',key+'Max'])];
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalize = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const numeric = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
const number = value => numeric(value) === null ? '—' : Number(value).toLocaleString('es-MX',{maximumFractionDigits:2});
const dateValue = value => {
    if (!value) return null;
    const text = String(value);
    const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : text+'-06:00');
    return isNaN(date) ? null : date;
};
const dateText = value => dateValue(value)?.toLocaleString('es-MX',{timeZone:'America/Mexico_City',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) || '—';
const cdmxDay = date => new Intl.DateTimeFormat('en-CA',{timeZone:'America/Mexico_City',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
const eventDay = p => { const date=dateValue(p.iso); return date ? cdmxDay(date) : ''; };
const category = p => ({VALUE:'FREE',FREE_RELEASE:'FREE'}[p.pickCategory] || p.pickCategory || 'FREE');
const opportunityState = p => p.opportunityState || (p.frozenAt ? 'CLOSED' : 'ACTIVE');
const categoryMeta = value => ({FREE:['🔓','FREE'],PREMIUM:['💎','PREMIUM'],WHALE:['🐋','WHALE']}[value] || ['🎯',value]);
const stateMeta = value => ({ACTIVE:['🟢','Vigente'],NO_LONGER_VALUE:['🔴','Ya no apostar'],CLOSED:['🏁','Cerrada']}[value] || ['⚪','Guardada']);
function historicalRows() {
    const today=cdmxDay(new Date());
    return archive.picks.filter(p=>{ const day=eventDay(p); return day && day<=today; });
}
const signalColors = {SMART_MONEY:'#2563eb',CONSENSUS:'#2dd4bf',STEAM_MOVE:'#14b8a6',REVERSE_LINE_MOVEMENT:'#8b5cf6',PUBLIC_HEAVY:'#f43f5e',SHARP_VS_PUBLIC:'#f59e0b',BALANCED_ACTION:'#94a3b8',LOW_LIQUIDITY:'#38bdf8',NO_ACTION:'#64748b'};
const displayGame = p => p && p.away && p.home ? `${p.away} vs ${p.home}` : ((p && p.game) || 'Evento');
let modelChart = null;
let signalsChart = null;

function populateOptions() {
    for (const [id,key,label] of [['league','league','🏆 Todas las ligas'],['date','date','📆 Todas las fechas'],['signal','marketSignal','📊 Todas las señales']]) {
        const selected = byId(id).value;
        const values = [...new Set(historicalRows().map(p => key==='date' ? eventDay(p) : p[key]).filter(Boolean))].sort();
        if (key==='date') values.reverse();
        byId(id).innerHTML = `<option value="">${label} (${values.length})</option>` + values.map(value => `<option value="${escape(value)}">${escape(value.replaceAll('_',' '))}</option>`).join('');
        byId(id).value = values.includes(selected) ? selected : '';
    }
}

function matchingRows() {
    const filters = Object.fromEntries(filterIds.map(id => [id,byId(id).value]));
    const query = normalize(filters.search.trim());
    return historicalRows().filter(p => {
        if (query && !normalize([p.game,p.pick,p.market,p.league,p.opportunityId].join(' ')).includes(query)) return false;
        const day = eventDay(p);
        if (filters.date && day !== filters.date || filters.from && day < filters.from || filters.to && day > filters.to) return false;
        if (filters.league && p.league !== filters.league || filters.market && p.market !== filters.market || filters.category && category(p) !== filters.category || filters.signal && p.marketSignal !== filters.signal) return false;
        for (const [prefix,key] of Object.entries(bounds)) {
            const min = numeric(filters[prefix+'Min']), max = numeric(filters[prefix+'Max']), value = numeric(p[key]);
            if ((min !== null || max !== null) && value === null) return false;
            if (min !== null && value < min || max !== null && value > max) return false;
        }
        return true;
    }).sort((a,b) => {
        const time = p => dateValue(p.iso)?.getTime() || 0;
        if (filters.sort === 'date-asc') return time(a)-time(b);
        if (filters.sort === 'captured') return (dateValue(b.firstCapturedAt)?.getTime()||0)-(dateValue(a.firstCapturedAt)?.getTime()||0);
        if (filters.sort === 'ev' || filters.sort === 'stake') return Number(b[filters.sort]||0)-Number(a[filters.sort]||0);
        return time(b)-time(a);
    });
}

function initCharts() {
    if (typeof Chart === 'undefined') { byId('chartNotice').hidden=false; return; }
    const style = getComputedStyle(document.documentElement);
    const color = style.getPropertyValue('--muted').trim(), grid = style.getPropertyValue('--border').trim();
    modelChart?.destroy(); signalsChart?.destroy();
    modelChart = new Chart(byId('modelChart'), {type:'scatter',data:{datasets:[{label:'Oportunidades',data:[],backgroundColor:'#2dd4bf',pointRadius:6}]},options:{animation:false,responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:context => `${context.raw.pick}: Modelo ${number(context.raw.x)}% · EV ${number(context.raw.y)}%`}}},scales:{x:{title:{display:true,text:'Modelo Prob. (%)',color},ticks:{color},grid:{color:grid}},y:{title:{display:true,text:'EV (%)',color},ticks:{color},grid:{color:grid}}}}});
    signalsChart = new Chart(byId('signalsChart'), {type:'doughnut',data:{labels:[],datasets:[{data:[],backgroundColor:[],borderWidth:0}]},options:{animation:false,responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{position:'bottom',labels:{color,boxWidth:10,font:{size:10}}}}}});
}

function updateCharts(rows) {
    if (modelChart) {
        modelChart.data.datasets[0].data = rows.filter(p => numeric(p.modelProb)!==null && numeric(p.ev)!==null).map(p => ({x:Number(p.modelProb),y:Number(p.ev),pick:p.pick}));
        modelChart.update();
    }
    if (signalsChart) {
        const counts = {};
        rows.forEach(p => { const signal=p.marketSignal || 'NO_ACTION'; counts[signal]=(counts[signal]||0)+1; });
        const keys=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]);
        signalsChart.data.labels=keys.map(key=>key.replaceAll('_',' '));
        signalsChart.data.datasets[0].data=keys.map(key=>counts[key]);
        signalsChart.data.datasets[0].backgroundColor=keys.map(key=>signalColors[key]||'#64748b');
        signalsChart.update();
    }
}

function movementRows(p) {
    const history=Array.isArray(p.history) ? p.history.slice(-5).reverse() : [];
    if (!history.length) return '<div class="archive-panel"><p class="archive-empty-detail">Sin movimientos guardados.</p></div>';
    return `<div class="archive-panel"><div class="archive-detail-title">📊 Últimos 5 movimientos</div>${history.map(h=>`<div class="movement-row"><time>${escape(dateText(h.timestamp||h.time))}</time><span>💵 ${escape(h.odds??'—')}</span><span>🎟️ ${escape(h.betsPct??'—')}%</span><span>💰 ${escape(h.handlePct??'—')}%</span></div>`).join('')}</div>`;
}

function transitionRows(p) {
    const transitions=Array.isArray(p.transitions) ? p.transitions : [];
    if (!transitions.length) return '';
    return `<div class="archive-panel"><div class="archive-detail-title">⚡ Cambios del pick</div>${transitions.map(item=>{const [icon,label]=stateMeta(item.state);return `<div class="transition-row"><time>${escape(dateText(item.at))}</time><span>${icon} ${escape(label)}</span><b>${escape(category({pickCategory:item.category}))}</b></div>`;}).join('')}</div>`;
}

function render() {
    const rows=matchingRows();
    const activeCount=filterIds.filter(id=>id!=='sort' && byId(id).value!=='').length;
    byId('activeFilters').textContent=activeCount ? `${activeCount} ${activeCount===1?'filtro activo':'filtros activos'}` : 'Sin filtros activos';
    byId('exportXls').disabled=rows.length===0;
    page=Math.min(page,Math.max(0,Math.ceil(rows.length/pageSize)-1));
    const offset=page*pageSize;
    const average = key => { const values=rows.map(p=>numeric(p[key])).filter(n=>n!==null); return values.length ? number(values.reduce((a,b)=>a+b,0)/values.length)+'%' : '—'; };
    byId('total').textContent=historicalRows().length;
    byId('matches').textContent=rows.length;
    byId('summaryCount').textContent=rows.length;
    byId('summaryTotal').textContent=historicalRows().length;
    byId('avgEv').textContent=average('ev');
    byId('avgEdge').textContent=average('modelEdge');
    byId('stake').textContent=number(rows.reduce((sum,p)=>sum+(Number(p.stake)||0),0))+' u';
    byId('since').textContent='Desde '+dateText(archive.startedAt);
    byId('updated').textContent=dateText(archive.updatedAt);
    updateCharts(rows);
    byId('rows').innerHTML=rows.slice(offset,offset+pageSize).map(p=>{const cat=category(p),[catIcon,catLabel]=categoryMeta(cat),state=opportunityState(p),[stateIcon,stateLabel]=stateMeta(state);return `<article class="event-card state-${escape(state.toLowerCase())}">
      <div class="event-topline"><span class="event-league">${escape(p.league)}</span><time>${dateText(p.iso)} · CDMX</time><span class="state-tag">${stateIcon} ${escape(stateLabel)}</span><span class="saved-tag ${cat.toLowerCase()}">${catIcon} ${escape(catLabel)}</span></div>
      <div class="event-overview"><div class="event-identity"><h3>${escape(displayGame(p))}</h3><p class="event-selection">${escape(p.pick)}</p><p class="event-market">${escape(p.market)} <span>·</span> ${escape((p.marketSignal||'—').replaceAll('_',' '))}</p></div>
      <dl class="event-metrics">${[['Cuota',p.odds],['Modelo',numeric(p.modelProb)===null?null:number(p.modelProb)+'%'],['EV',numeric(p.ev)===null?null:number(p.ev)+'%'],['Stake público',numeric(p.stake)===null?null:number(p.stake)+' u']].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value??'—')}</dd></div>`).join('')}</dl></div>
      <details class="event-details"><summary><span>Ver seguimiento</span><span class="expand-icon" aria-hidden="true">+</span></summary><div class="event-expanded"><dl class="secondary-metrics">${[['⚖️ Edge',number(p.modelEdge)+'%'],['🎟️ Bets',number(p.betsPct)+'%'],['💰 Handle',number(p.handlePct)+'%'],['🐋 Divergencia',number(p.divergence)+'%'],['Primera captura',dateText(p.firstCapturedAt)],['Última actualización',dateText(p.lastUpdatedAt)]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl><div class="archive-detail-grid">${movementRows(p)}${transitionRows(p)}</div><button type="button" class="btn-chip detail-json-button" data-detail="${escape(p.opportunityId)}">Consultar JSON original</button></div></details>
    </article>`;}).join('');
    byId('empty').hidden=rows.length!==0;
    byId('empty').textContent=historicalRows().length ? 'No hay oportunidades que coincidan con estos filtros.' : 'Aún no hay oportunidades con fecha de hoy o anterior.';
    byId('range').textContent=rows.length ? `${offset+1}–${Math.min(offset+pageSize,rows.length)} de ${rows.length} oportunidades` : '0 oportunidades';
    byId('prev').disabled=page===0;
    byId('next').disabled=offset+pageSize>=rows.length;
}

async function refresh() {
    if (location.protocol==='file:') { location.reload(); return; }
    byId('refresh').disabled=true;
    try {
        const response=await fetch('data/opportunities.json',{cache:'no-store'});
        if (!response.ok) throw new Error('HTTP '+response.status);
        const payload=await response.json();
        if (payload.schemaVersion!==1 || !Array.isArray(payload.picks)) throw new Error('Formato inválido');
        archive=payload; populateOptions(); render();
    } catch (error) { byId('updated').textContent='No se pudo actualizar; se conservan los datos cargados.'; }
    finally { byId('refresh').disabled=false; }
}

function exportXls() {
    const rows = matchingRows();
    if (!rows.length) return;
    const headers = ['Evento','Selección','Inicio (CDMX)','Liga','Mercado','Categoría','Cuota','Modelo %','Edge %','EV %','Stake público (u)','Bets %','Handle %','Divergencia','Señal','Primera captura (CDMX)','Última actualización (CDMX)','ID oportunidad'];
    const workbook = XLSX.utils.book_new();
    // XLS admite 65.536 filas por hoja, incluida la cabecera.
    for (let offset=0; offset<rows.length; offset+=65535) {
        const values = rows.slice(offset,offset+65535).map(p => [
            String(p.game||''),String(p.pick||''),dateText(p.iso),String(p.league||''),String(p.market||''),category(p),
            ...['odds','modelProb','modelEdge','ev','stake','betsPct','handlePct','divergence'].map(key=>numeric(p[key])),
            String(p.marketSignal||'').replaceAll('_',' '),dateText(p.firstCapturedAt),dateText(p.lastUpdatedAt),String(p.opportunityId||'')
        ]);
        const sheet = XLSX.utils.aoa_to_sheet([headers,...values]);
        sheet['!cols'] = headers.map((_,index)=>({wch:index<2 ? 36 : index===17 ? 28 : index===2 || index>=14 ? 25 : 15}));
        XLSX.utils.book_append_sheet(workbook,sheet,offset===0 ? 'Oportunidades' : 'Oportunidades '+(offset/65535+1));
    }
    XLSX.writeFile(workbook,'oportunidades-'+new Date().toISOString().slice(0,10)+'.xls',{bookType:'biff8'});
}

const exportButton = document.createElement('button');
exportButton.id='exportXls';
exportButton.type='button';
exportButton.className='btn-chip';
exportButton.textContent='↓ Exportar XLS';
exportButton.title='Exportar todas las oportunidades filtradas, incluidas todas las páginas';
byId('exportSlot').append(exportButton);
exportButton.addEventListener('click',exportXls);
byId('densityToggle').addEventListener('click',()=>{
    const compact=document.querySelector('.history-table-wrap').classList.toggle('compact');
    byId('densityToggle').setAttribute('aria-pressed',String(compact));
    byId('densityToggle').textContent=compact ? 'Vista cómoda' : 'Vista compacta';
});
byId('filters').addEventListener('submit',event=>event.preventDefault());
filterIds.forEach(id=>byId(id).addEventListener('input',()=>{page=0;render();}));
byId('advancedToggle').addEventListener('click',()=>{byId('advanced').hidden=!byId('advanced').hidden;byId('advancedToggle').setAttribute('aria-expanded',String(!byId('advanced').hidden));});
byId('clear').addEventListener('click',()=>{byId('filters').reset();page=0;render();});
byId('prev').addEventListener('click',()=>{page--;render();byId('rows').scrollIntoView({block:'start'});});
byId('next').addEventListener('click',()=>{page++;render();byId('rows').scrollIntoView({block:'start'});});
byId('refresh').addEventListener('click',refresh);
byId('themeToggle').addEventListener('click',()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';initCharts();render();});
byId('rows').addEventListener('click',event=>{const button=event.target.closest('button[data-detail]');if(!button)return;byId('detailJson').textContent=JSON.stringify(archive.picks.find(p=>p.opportunityId===button.dataset.detail),null,2);byId('detail').showModal();});
byId('closeDetail').addEventListener('click',()=>byId('detail').close());
populateOptions();initCharts();render();
if (location.protocol==='http:' || location.protocol==='https:') setInterval(refresh,90000);
