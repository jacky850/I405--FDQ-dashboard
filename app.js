const data = window.DASHBOARD_DATA;
const select = document.querySelector('#linkSelect');
const metrics = document.querySelector('#metrics');
const colors = {blue:'#246bce', orange:'#e07a31', teal:'#159a8c', red:'#c94747'};

function fmt(x, digits=1){ return Number(x).toLocaleString(undefined,{maximumFractionDigits:digits}); }
function esc(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
function makeSvg(id, series, opts={}){
  const el=document.querySelector('#'+id), W=720,H=265,p={l:48,r:18,t:18,b:30};
  const all=series.flatMap(s=>s.values).filter(Number.isFinite); let ymin=opts.ymin ?? Math.min(...all), ymax=opts.ymax ?? Math.max(...all);
  if(ymin===ymax){ymin-=1;ymax+=1;} const pad=(ymax-ymin)*.08; ymin-=pad; ymax+=pad;
  const x=i=>p.l+i/(series[0].values.length-1)*(W-p.l-p.r), y=v=>H-p.b-(v-ymin)/(ymax-ymin)*(H-p.t-p.b);
  let html=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="chart"><line class="axis" x1="${p.l}" y1="${H-p.b}" x2="${W-p.r}" y2="${H-p.b}"/><line class="axis" x1="${p.l}" y1="${p.t}" x2="${p.l}" y2="${H-p.b}"/>`;
  for(let j=0;j<5;j++){const v=ymin+(ymax-ymin)*j/4; const yy=y(v); html+=`<line class="gridline" x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}"/><text class="tick" x="${p.l-7}" y="${yy+3}" text-anchor="end">${fmt(v,0)}</text>`;}
  [0,72,144,216,287].forEach(i=>{html+=`<text class="tick" x="${x(i)}" y="${H-8}" text-anchor="middle">${series[0].labels[i]}</text>`});
  series.forEach(s=>{let d=s.values.map((v,i)=>`${i?'L':'M'} ${x(i)} ${y(v)}`).join(' '); html+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.4"/>`;});
  series.forEach((s,i)=>{html+=`<line x1="${p.l+10+i*145}" y1="${p.t-4}" x2="${p.l+30+i*145}" y2="${p.t-4}" stroke="${s.color}" stroke-width="3"/><text class="legend" x="${p.l+35+i*145}" y="${p.t}">${esc(s.name)}</text>`});
  html+='</svg>'; el.innerHTML=html;
}
function makeQueueChart(id, labels, queueSeries){
  const el=document.querySelector('#'+id), W=720,H=265,p={l:52,r:18,t:18,b:30};
  const qAll=queueSeries.flatMap(s=>s.values).filter(Number.isFinite); let qMin=Math.min(...qAll), qMax=Math.max(...qAll);
  if(qMin===qMax){qMin-=1;qMax+=1;}
  const qPad=(qMax-qMin)*.08; qMin-=qPad; qMax+=qPad;
  const x=i=>p.l+i/(labels.length-1)*(W-p.l-p.r), yQ=v=>H-p.b-(v-qMin)/(qMax-qMin)*(H-p.t-p.b);
  let html=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="queue chart"><line class="axis" x1="${p.l}" y1="${H-p.b}" x2="${W-p.r}" y2="${H-p.b}"/><line class="axis" x1="${p.l}" y1="${p.t}" x2="${p.l}" y2="${H-p.b}"/>`;
  for(let j=0;j<5;j++){const qv=qMin+(qMax-qMin)*j/4, yy=yQ(qv); html+=`<line class="gridline" x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}"/><text class="tick" x="${p.l-7}" y="${yy+3}" text-anchor="end">${fmt(qv,0)}</text>`;}
  [0,72,144,216,287].forEach(i=>{html+=`<text class="tick" x="${x(i)}" y="${H-8}" text-anchor="middle">${labels[i]}</text>`});
  queueSeries.forEach(s=>{const d=s.values.map((v,i)=>`${i?'L':'M'} ${x(i)} ${yQ(v)}`).join(' '); html+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.4"/>`;});
  const legend=queueSeries.map(s=>[s.name,s.color]); legend.forEach((s,i)=>{const col=i%3,row=Math.floor(i/3), lx=p.l+10+col*220, ly=p.t-4+row*15; html+=`<line x1="${lx}" y1="${ly}" x2="${lx+20}" y2="${ly}" stroke="${s[1]}" stroke-width="3"/><text class="legend" x="${lx+25}" y="${ly+4}">${esc(s[0])}</text>`;});
  html+=`<text class="tick" transform="translate(12 ${H/2}) rotate(-90)" text-anchor="middle">queue (vehicles)</text></svg>`; el.innerHTML=html;
}
function makeFd(id, link){
  const el=document.querySelector('#'+id), W=720,H=265,p={l:48,r:18,t:18,b:30}; const pts=link.rows, curve=link.fdCurve;
  const observedMaxDensity=Math.max(...pts.map(d=>d.density));
  const mentorInRange=link.mentorCurve.filter(r=>r.density<=observedMaxDensity*1.08);
  const xmax=Math.max(...pts.map(d=>d.density),...curve.map(d=>d.density),...mentorInRange.map(d=>d.density))*1.08, ymax=Math.max(...pts.map(d=>d.observedFlow),...curve.map(d=>d.flow),...mentorInRange.map(d=>d.flow))*1.08;
  const x=v=>p.l+v/xmax*(W-p.l-p.r), y=v=>H-p.b-v/ymax*(H-p.t-p.b); let html=`<svg viewBox="0 0 ${W} ${H}"><line class="axis" x1="${p.l}" y1="${H-p.b}" x2="${W-p.r}" y2="${H-p.b}"/><line class="axis" x1="${p.l}" y1="${p.t}" x2="${p.l}" y2="${H-p.b}"/>`;
  for(let j=0;j<5;j++){const v=ymax*j/4, yy=y(v); html+=`<line class="gridline" x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}"/><text class="tick" x="${p.l-7}" y="${yy+3}" text-anchor="end">${fmt(v,0)}</text>`;}
  let d=curve.map((r,i)=>`${i?'L':'M'} ${x(r.density)} ${y(r.flow)}`).join(' '); html+=`<path d="${d}" fill="none" stroke="${colors.orange}" stroke-width="2.6"/>`;
  let mentorD=mentorInRange.map((r,i)=>`${i?'L':'M'} ${x(r.density)} ${y(r.flow)}`).join(' '); html+=`<path d="${mentorD}" fill="none" stroke="#697586" stroke-width="2.2" stroke-dasharray="6 4"/>`;
  pts.forEach(r=>{html+=`<circle cx="${x(r.density)}" cy="${y(r.observedFlow)}" r="2.4" fill="${colors.blue}" opacity=".55"/>`;}); html+=`<text class="legend" x="${p.l+10}" y="${p.t}" fill="${colors.blue}">Observed points</text><text class="legend" x="${p.l+125}" y="${p.t}" fill="${colors.orange}">S3 curve</text><text class="legend" x="${p.l+205}" y="${p.t}" fill="#697586">Mentor FDQ v2 (in range)</text><text class="tick" x="${W/2}" y="${H-4}" text-anchor="middle">density (veh/mi/lane)</text><text class="tick" transform="translate(12 ${H/2}) rotate(-90)" text-anchor="middle">flow (veh/h)</text></svg>`; el.innerHTML=html;
}
function render(link){
  metrics.innerHTML=[['Link',link.linkId,'TMC '+link.tmcId],['Lanes',fmt(link.lanes,0),'network metadata'],['S3 R²',fmt(link.s3R2,3),'speed → flow diagnostic'],['S3 MAE',fmt(link.s3Mae,0)+' veh/h','overall observed-flow error'],['Max queue',fmt(link.maxQueue,0),'vehicles; observed λ']].map(x=>`<div class="metric card"><div class="label">${x[0]}</div><div class="value">${esc(x[1])}</div><div class="detail">${x[2]}</div></div>`).join('');
  const labels=link.rows.map(r=>r.time), speed=link.rows.map(r=>r.speed), obs=link.rows.map(r=>r.observedFlow), inf=link.rows.map(r=>r.inferredFlow), mu=link.rows.map(r=>r.mu), q=link.rows.map(r=>r.queue);
  const periodInf=link.rows.map(r=>r.periodInferredFlow), anchoredInf=link.rows.map(r=>r.anchoredInferredFlow); makeSvg('speedChart',[{name:'speed',values:speed,color:colors.blue,labels}]); makeSvg('flowChart',[{name:'observed flow',values:obs,color:colors.blue,labels},{name:'global S3',values:inf,color:colors.orange,labels},{name:'period S3',values:periodInf,color:colors.teal,labels},{name:'anchored S3',values:anchoredInf,color:'#c026d3',labels}]); makeQueueChart('queueChart',labels,[{name:'observed-flow baseline',values:link.rows.map(r=>r.queueObserved),color:colors.red},{name:'period S3 queue',values:link.rows.map(r=>r.queuePeriodS3),color:colors.teal},{name:'anchored S3 queue',values:link.rows.map(r=>r.queueAnchoredS3),color:'#c026d3'},{name:'dynamic μ + observed flow',values:link.rows.map(r=>r.queueDynamic),color:colors.orange}]); makeSvg('muChart',[{name:'constant μ',values:mu,color:'#111827',labels},{name:'dynamic μ',values:link.rows.map(r=>r.muDynamic),color:'#d97706',labels}]); makeFd('fdChart',link); document.querySelector('#contractStatus').textContent='Observed λ · constant μ baseline · dynamic μ candidate · continuous Q';
  document.querySelector('#periodStats').innerHTML=link.periodStats.map(s=>`<tr><th>${s.period}</th><td>${s.n}</td><td>${fmt(s.observedMean,0)}</td><td>${fmt(s.predictedMean,0)}</td><td>${fmt(s.bias,0)}</td><td>${fmt(s.mae,0)}</td><td>${fmt(s.rmse,0)}</td></tr>`).join('')+`<tr class="total"><th>Overall</th><td>${link.rows.length}</td><td>—</td><td>—</td><td>${fmt(link.periodS3Overall.bias,0)}</td><td>${fmt(link.periodS3Overall.mae,0)}</td><td>${fmt(link.periodS3Overall.rmse,0)}</td></tr>`;
  document.querySelector('#s3ModelSummary').innerHTML=`<tr><th>Global S3</th><td>${fmt(link.s3R2,3)}</td><td>${fmt(link.s3Mae,0)}</td><td>${fmt(link.s3Rmse,0)}</td></tr><tr><th>Period-specific S3</th><td>${fmt(link.periodS3Overall.r2,3)}</td><td>${fmt(link.periodS3Overall.mae,0)}</td><td>${fmt(link.periodS3Overall.rmse,0)}</td></tr><tr><th>Anchored period S3</th><td>${fmt(link.anchoredS3Overall.r2,3)}</td><td>${fmt(link.anchoredS3Overall.mae,0)}</td><td>${fmt(link.anchoredS3Overall.rmse,0)}</td></tr>`;
  document.querySelector('#queueSummary').innerHTML=[['Observed-flow baseline',link.queueScenarios.observed],['Period S3 inflow',link.queueScenarios.periodS3],['Anchored S3 inflow',link.queueScenarios.anchoredS3],['Dynamic μ + observed flow',{maxQueue:link.dynamicMuSummary.dynamicMaxQueue,finalQueue:link.dynamicMuSummary.dynamicFinalQueue,maeVsObservedBaseline:link.dynamicMuSummary.queueMaeDifference}]].map(([name,s])=>`<tr><th>${name}</th><td>${fmt(s.maxQueue,0)}</td><td>${fmt(s.finalQueue,0)}</td><td>${fmt(s.maeVsObservedBaseline,0)}</td></tr>`).join('');
}
document.querySelector('#linkSummary').innerHTML=data.links.map(l=>`<tr data-link="${l.id}"><th>${esc(l.linkId)} · ${esc(l.tmcId)}</th><td>${fmt(l.lanes,0)}</td><td>${fmt(l.s3R2,3)}</td><td>${fmt(l.s3Mae,0)}</td><td>${fmt(l.s3Rmse,0)}</td><td>${fmt(l.maxQueue,0)}</td></tr>`).join('');
document.querySelectorAll('#linkSummary tr').forEach(row=>row.addEventListener('click',()=>{select.value=row.dataset.link; render(data.links.find(l=>l.id===row.dataset.link));}));
document.querySelector('#implementationSummary').innerHTML=data.links.flatMap(l=>[
  `<tr><th rowspan="2">${esc(l.linkId)} · ${esc(l.tmcId)}</th><td>Our S3</td><td>${fmt(l.s3R2,3)}</td><td>${fmt(l.s3Mae,0)}</td><td>${fmt(l.s3Rmse,0)}</td></tr>`,
  `<tr><td>Mentor triangular</td><td>${fmt(l.mentorMetrics.r2,3)}</td><td>${fmt(l.mentorMetrics.mae_vehph_total,0)}</td><td>${fmt(l.mentorMetrics.rmse_vehph_total,0)}</td></tr>`
]).join('');
data.links.forEach(l=>{const o=document.createElement('option');o.value=l.id;o.textContent=`${l.linkId} · TMC ${l.tmcId}`;select.appendChild(o);}); select.addEventListener('change',()=>render(data.links.find(l=>l.id===select.value))); render(data.links[0]);
