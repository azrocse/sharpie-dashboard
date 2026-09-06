const PICKS=__PICKS_JSON__;
const TODAY_CDMX='__TODAY_CDMX__';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>Number.isFinite(Number(v))?Number(v):0;
const fmt=(v,d=2)=>num(v).toFixed(d);
const finalSet=new Set(['WIN','HALF_WIN','LOSS','HALF_LOSS','PUSH','VOID']);
const numericFilters=['oddsMin','oddsMax','modelMin','modelMax','edgeMin','edgeMax','evMin','evMax','divMin','divMax'];
let filtered=[],scoped=[],page=1,unitsChart,resultChart;
const PAGE_SIZE=50,MIN_SAMPLE=12;

function divergence(p){return num(p.signedDivergence??p.divergence);}
function americanOdds(p){return num(String(p.odds??0).replace('+',''));}
function populate(){
  for(const [id,key,label] of [['league','league','Todas las ligas'],['market','market','Todos los mercados']]){
    const values=[...new Set(PICKS.map(p=>p[key]).filter(Boolean))].sort();
    $(id).innerHTML=`<option value="">${label}</option>`+values.map(v=>`<option>${esc(v)}</option>`).join('');
  }
}
function shiftIsoDate(iso,days){const d=new Date(`${iso}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);}
function setRange(value){
  $('range').value=value;
  document.querySelectorAll('#rangeTabs button').forEach(b=>b.classList.toggle('active',b.dataset.range===value));
  $('customDates').hidden=value!=='custom';
  if(value==='custom')return;
  if(value==='all'){$('dateFrom').value='';$('dateTo').value='';return;}
  if(value==='today'){$('dateFrom').value=TODAY_CDMX;$('dateTo').value=TODAY_CDMX;return;}
  if(value==='yesterday'){const y=shiftIsoDate(TODAY_CDMX,-1);$('dateFrom').value=y;$('dateTo').value=y;return;}
  $('dateFrom').value=shiftIsoDate(TODAY_CDMX,-(Number(value)-1));$('dateTo').value=TODAY_CDMX;
}
function passesBound(value,minId,maxId){const min=$(minId).value,max=$(maxId).value;return(!min||value>=num(min))&&(!max||value<=num(max));}
function apply(){
  const q=$('search').value.toLowerCase().trim(),from=$('dateFrom').value,to=$('dateTo').value;
  const league=$('league').value,cat=$('category').value,market=$('market').value,res=$('result').value,stake=$('stake').value;
  scoped=PICKS.filter(p=>{const blob=`${p.game||''} ${p.pick||''} ${p.league||''} ${p.market||''}`.toLowerCase(),date=p.date||'';
    return date<=TODAY_CDMX&&num(p.ev)>0&&num(p.modelEdge)>0&&(!q||blob.includes(q))&&(!from||date>=from)&&(!to||date<=to)&&(!league||p.league===league)&&(!cat||p.pickCategory===cat)&&(!market||p.market===market)&&(!stake||num(p.stake)===num(stake))&&(!$('freeOnly').checked||p.freeRelease)&&passesBound(americanOdds(p),'oddsMin','oddsMax')&&passesBound(num(p.modelProb),'modelMin','modelMax')&&passesBound(num(p.modelEdge),'edgeMin','edgeMax')&&passesBound(num(p.ev),'evMin','evMax')&&passesBound(divergence(p),'divMin','divMax');
  });
  filtered=scoped.filter(p=>!res||(res==='SETTLED'?finalSet.has(p.result):p.result===res));page=1;render();
}
function metrics(){
  const settled=filtered.filter(p=>finalSet.has(p.result)),wins=settled.filter(p=>p.result==='WIN').length+settled.filter(p=>p.result==='HALF_WIN').length*.5,losses=settled.filter(p=>p.result==='LOSS').length+settled.filter(p=>p.result==='HALF_LOSS').length*.5,push=settled.filter(p=>p.result==='PUSH').length;
  const units=settled.reduce((s,p)=>s+num(p.profitUnits),0),risk=settled.filter(p=>p.result!=='VOID').reduce((s,p)=>s+num(p.stake),0),pending=scoped.filter(p=>p.result==='PENDING').length,review=scoped.filter(p=>p.result==='REVIEW').length,yieldPct=risk?units/risk*100:0,wr=wins+losses?wins/(wins+losses)*100:0;
  $('kSettled').textContent=settled.length;$('kTotalSub').textContent=`${filtered.length} visibles`;$('kRecord').textContent=`${wins}-${losses}-${push}`;$('kUnits').textContent=`${units>=0?'+':''}${fmt(units)}u`;$('kRoi').textContent=`${yieldPct>=0?'+':''}${fmt(yieldPct)}%`;$('kRisked').textContent=`${fmt(risk)}u apostadas`;$('kWinRate').textContent=`${fmt(wr)}%`;$('kPending').textContent=pending+review;$('kReview').textContent=`${review} revisión · ${pending} en curso`;
  $('kUnits').className='kpi-value '+(units>=0?'positive':'negative');$('kRoi').className='kpi-value '+(yieldPct>=0?'positive':'negative');
}
function score(p){const s=p.settlement||{};if(s.awayScore==null||s.homeScore==null)return'—';return /\s@\s/.test(p.game||'')?`${s.awayScore}-${s.homeScore}`:`${s.homeScore}-${s.awayScore}`;}
function renderRows(){
  const start=(page-1)*PAGE_SIZE,items=filtered.slice(start,start+PAGE_SIZE);
  $('rows').innerHTML=items.map((p,i)=>`<tr><td data-label="Fecha"><span class="mono">${esc(p.date)}<br>${esc(p.time||'')}</span></td><td data-label="Evento"><div class="event">${esc(p.game)}</div><span class="muted">${esc(p.league)}</span></td><td data-label="Pick"><div class="pick">${esc(p.pick)}</div><span class="muted">${esc(p.market)}</span></td><td data-label="Categoría"><span class="badge ${esc(p.pickCategory)}">${esc(p.pickCategory)}</span>${p.freeRelease?'<br><span class="badge FREE">FREE RELEASE</span>':''}</td><td data-label="Cuota" class="mono">${esc(p.odds)}</td><td data-label="Stake" class="mono">${fmt(p.stake,1)}u</td><td data-label="Modelo" class="mono">${fmt(p.modelProb)}%</td><td data-label="Edge" class="mono">${num(p.modelEdge)>=0?'+':''}${fmt(p.modelEdge)}%</td><td data-label="EV" class="mono">${num(p.ev)>=0?'+':''}${fmt(p.ev)}%</td><td data-label="Divergencia" class="mono">${divergence(p)>=0?'+':''}${fmt(divergence(p))}%</td><td data-label="Resultado"><span class="badge ${esc(p.result)}">${esc(p.result)}</span></td><td data-label="Marcador" class="mono">${score(p)}</td><td data-label="Balance" class="mono ${num(p.profitUnits)>0?'positive':num(p.profitUnits)<0?'negative':''}">${p.profitUnits==null?'—':`${num(p.profitUnits)>=0?'+':''}${fmt(p.profitUnits)}u`}</td><td data-label="Detalle"><button class="details-btn" data-index="${start+i}">Ver</button></td></tr>`).join('');
  $('empty').hidden=items.length>0;$('rows').hidden=items.length===0;document.querySelectorAll('.details-btn').forEach(b=>b.onclick=()=>openDetail(filtered[Number(b.dataset.index)]));
  const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));$('pageInfo').textContent=`Página ${page} de ${pages}`;$('prev').disabled=page<=1;$('next').disabled=page>=pages;
}
function charts(){
  if(typeof Chart==='undefined')return;
  const settled=[...filtered].filter(p=>finalSet.has(p.result)).sort((a,b)=>(a.date||'').localeCompare(b.date||'')),byDate={};settled.forEach(p=>byDate[p.date]=(byDate[p.date]||0)+num(p.profitUnits));let acc=0;
  const labels=Object.keys(byDate).sort(),values=labels.map(d=>acc+=byDate[d]),dark=document.documentElement.dataset.theme!=='light',text=dark?'#94a3b8':'#64748b',grid=dark?'#243572':'#e2e8f0';
  if(unitsChart)unitsChart.destroy();unitsChart=new Chart($('unitsChart'),{type:'line',data:{labels,datasets:[{data:values,borderColor:'#2dd4bf',backgroundColor:'rgba(45,212,191,.12)',fill:true,tension:.25,pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:text,maxTicksLimit:8},grid:{color:grid}},y:{ticks:{color:text,callback:v=>v+'u'},grid:{color:grid}}}}});
  const states=['WIN','HALF_WIN','LOSS','HALF_LOSS','PUSH','VOID','PENDING','REVIEW'],colors=['#22c55e','#86efac','#fb7185','#fda4af','#fbbf24','#64748b','#60a5fa','#a78bfa'],active=states.map((r,i)=>({r,n:filtered.filter(p=>p.result===r).length,c:colors[i]})).filter(x=>x.n);
  if(resultChart)resultChart.destroy();resultChart=new Chart($('resultChart'),{type:'doughnut',data:{labels:active.map(x=>x.r),datasets:[{data:active.map(x=>x.n),backgroundColor:active.map(x=>x.c),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'67%',plugins:{legend:{position:'bottom',labels:{color:text,boxWidth:10}}}}});
}
function detail(label,value){return `<div class="detail"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;}
function sourceLink(url){return /^https:\/\//i.test(url||'')?`<p class="source-link"><a href="${esc(url)}" target="_blank" rel="noopener">Abrir consulta original de ESPN ↗</a></p>`:'';}
function openDetail(p){const s=p.settlement||{},e=p.eventLookup||{},snaps=Array.isArray(p.qualificationSnapshots)?p.qualificationSnapshots:[];$('modalTitle').textContent=p.pick||'Detalle';$('modalBody').innerHTML=`<div class="modal-grid">${detail('Evento',p.game||p.event)}${detail('Fecha y hora',`${p.date||'—'} ${p.time||''}`)}${detail('Liga registrada',p.league)}${detail('Mercado',p.market)}${detail('Pick',p.pick)}${detail('Cuota',p.odds)}${detail('Stake',`${fmt(p.stake,1)}u`)}${detail('Categoría',p.pickCategory)}${detail('Señal',p.marketSignal)}${detail('Modelo',`${fmt(p.modelProb)}%`)}${detail('Edge',`${fmt(p.modelEdge)}%`)}${detail('EV',`${fmt(p.ev)}%`)}${detail('Bets / Handle',`${fmt(p.betsPct)}% / ${fmt(p.handlePct)}%`)}${detail('Divergencia',`${fmt(divergence(p))}%`)}${detail('Resultado',p.result)}${detail('Balance',p.profitUnits==null?'—':fmt(p.profitUnits)+'u')}${detail('Marcador',score(p))}${detail('Fuente',s.source||e.provider||'—')}${detail('ESPN Event ID',s.eventId||e.eventId||'—')}${detail('Estado del cotejo',e.matchStatus||'—')}${detail('Causa',s.failureCode||s.notes||'—')}${detail('Archivo',p.historyFile)}${detail('Snapshots',snaps.length)}</div>${sourceLink(s.sourceUrl)}`;openModal($('detailModal'));}
function openModal(modal){if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','');}

function bucket(value,cuts,labels){for(let i=0;i<cuts.length;i++)if(value<cuts[i])return labels[i];return labels[labels.length-1];}
const dimensions=[
  {name:'Categoría',get:p=>p.pickCategory||'—'},{name:'Cuota',get:p=>bucket(americanOdds(p),[-150,-100,101,151,251],['< -150','-150 a -101','-100 a +100','+101 a +150','+151 a +250','≥ +251'])},
  {name:'Stake',get:p=>`${fmt(p.stake,1)}u`},{name:'Modelo',get:p=>bucket(num(p.modelProb),[55,60,65],['<55%','55–59.9%','60–64.9%','≥65%'])},
  {name:'Edge',get:p=>bucket(num(p.modelEdge),[5,10,15],['0–4.9%','5–9.9%','10–14.9%','≥15%'])},{name:'EV',get:p=>bucket(num(p.ev),[5,10,15,25],['0–4.9%','5–9.9%','10–14.9%','15–24.9%','≥25%'])},
  {name:'Divergencia',get:p=>bucket(divergence(p),[0,10,20,35],['Negativa','0–9.9%','10–19.9%','20–34.9%','≥35%'])},{name:'Mercado',get:p=>p.market||'—'},{name:'Liga',get:p=>p.league||'—'}
];
function summarize(label,items){const risk=items.filter(p=>p.result!=='VOID').reduce((s,p)=>s+num(p.stake),0),profit=items.reduce((s,p)=>s+num(p.profitUnits),0),wins=items.filter(p=>p.result==='WIN').length+items.filter(p=>p.result==='HALF_WIN').length*.5,losses=items.filter(p=>p.result==='LOSS').length+items.filter(p=>p.result==='HALF_LOSS').length*.5;return{label,n:items.length,risk,profit,yieldPct:risk?profit/risk*100:0,wins,losses};}
function analyze(){
  const settled=filtered.filter(p=>finalSet.has(p.result)),segments=[];
  function collect(labelFn){const groups=new Map();settled.forEach(p=>{const label=labelFn(p);if(!groups.has(label))groups.set(label,[]);groups.get(label).push(p);});groups.forEach((items,label)=>{if(items.length>=MIN_SAMPLE)segments.push(summarize(label,items));});}
  dimensions.forEach(d=>collect(p=>`${d.name}: ${d.get(p)}`));
  for(let i=0;i<dimensions.length;i++)for(let j=i+1;j<dimensions.length;j++){const a=dimensions[i],b=dimensions[j];collect(p=>`${a.name}: ${a.get(p)} · ${b.name}: ${b.get(p)}`);}
  const overall=summarize('Total',settled),gains=segments.filter(s=>s.profit>0).sort((a,b)=>b.yieldPct-a.yieldPct||b.n-a.n).slice(0,8),losses=segments.filter(s=>s.profit<0).sort((a,b)=>a.yieldPct-b.yieldPct||b.n-a.n).slice(0,8);
  const cards=list=>list.length?list.map(s=>`<article class="analysis-row"><b>${esc(s.label)}</b><span>${s.n} picks · ${fmt(s.risk)}u apostadas · ${s.wins} favorables / ${s.losses} desfavorables</span><strong class="${s.profit>=0?'positive':'negative'}">${s.profit>=0?'+':''}${fmt(s.profit)}u <small>Yield ${s.yieldPct>=0?'+':''}${fmt(s.yieldPct)}%</small></strong></article>`).join(''):'<p class="analysis-empty">No hay segmentos que superen la muestra mínima.</p>';
  $('analysisBody').innerHTML=`<div class="analysis-kpis"><div><span>Muestra</span><b>${overall.n}</b></div><div><span>Balance</span><b class="${overall.profit>=0?'positive':'negative'}">${overall.profit>=0?'+':''}${fmt(overall.profit)}u</b></div><div><span>Yield</span><b class="${overall.yieldPct>=0?'positive':'negative'}">${overall.yieldPct>=0?'+':''}${fmt(overall.yieldPct)}%</b></div><div><span>Muestra mínima</span><b>${MIN_SAMPLE} picks</b></div></div><p class="analysis-note">Se probaron variables individuales y todos los cruces de dos variables. Los resultados describen el historial filtrado; no garantizan rendimiento futuro. Se descartan segmentos con menos de ${MIN_SAMPLE} picks.</p><h3>Dónde están las ganancias</h3><div class="analysis-list">${cards(gains)}</div><h3>Dónde están las pérdidas</h3><div class="analysis-list">${cards(losses)}</div>`;
  openModal($('analysisModal'));
}
function exportCsv(){
  const headers=['Fecha','Hora','Liga','Evento','Pick','Mercado','Categoría','Cuota','Stake','Modelo %','Edge %','EV %','Divergencia %','Resultado','Balance u'];
  const quote=v=>`"${String(v??'').replace(/"/g,'""')}"`,rows=filtered.map(p=>[p.date,p.time,p.league,p.game,p.pick,p.market,p.pickCategory,p.odds,p.stake,p.modelProb,p.modelEdge,p.ev,divergence(p),p.result,p.profitUnits].map(quote).join(','));
  const blob=new Blob(['\ufeff'+[headers.map(quote).join(','),...rows].join('\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`sharpie-resultados-${TODAY_CDMX}.csv`;a.click();URL.revokeObjectURL(url);
}
function render(){$('shown').textContent=filtered.length;$('total').textContent=scoped.length;metrics();renderRows();charts();}
['search',...numericFilters].forEach(id=>$(id).addEventListener('input',apply));
['league','category','market','stake','result','freeOnly'].forEach(id=>$(id).addEventListener('change',apply));
document.querySelectorAll('#rangeTabs button').forEach(b=>b.onclick=()=>{setRange(b.dataset.range);apply();});
['dateFrom','dateTo'].forEach(id=>$(id).onchange=apply);
$('clear').onclick=()=>{$('search').value='';['league','category','market','stake'].forEach(id=>$(id).value='');numericFilters.forEach(id=>$(id).value='');$('result').value='SETTLED';$('freeOnly').checked=false;setRange('all');apply();};
$('exportCsv').onclick=exportCsv;$('analyze').onclick=analyze;
$('prev').onclick=()=>{page--;renderRows();scrollTo(0,0);};$('next').onclick=()=>{page++;renderRows();scrollTo(0,0);};
$('closeModal').onclick=()=>$('detailModal').close();$('closeAnalysis').onclick=()=>$('analysisModal').close();
[$('detailModal'),$('analysisModal')].forEach(m=>m.onclick=e=>{if(e.target===m)m.close();});
$('theme').onclick=()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light';charts();};
populate();setRange('all');apply();

