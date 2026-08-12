(() => {
  const data=window.FULL_DAY_RESIDUAL, s=data.summary, rows=data.series, ep=data.episodes[0];
  const $=id=>document.getElementById(id), fmt=new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
  const minute=iso=>{const m=String(iso).match(/T(\d\d):(\d\d)/);return +m[1]*60 + +m[2]};
  const time=m=>`${String(Math.floor(m/60)).padStart(2,'0')}:${String(Math.round(m%60)).padStart(2,'0')}`;
  const t0=minute(ep.t0_la),t2=minute(ep.t2_la),t3=minute(ep.t3_la),boundary=600;
  const qBoundary=s.count_reference_queue_at_period_boundaries_veh['10:00'];

  $('metrics').innerHTML=[
    ['Episode',`${ep.duration_min} min`,`${ep.t0_la.slice(11,16)}–${ep.t3_la.slice(11,16)} LA`],
    ['Minimum speed',`${ep.minimum_speed_mph.toFixed(1)} mph`,`T₂ ${ep.t2_la.slice(11,16)}`],
    ['Reference Qmax',`${fmt.format(s.count_reference_maximum_queue_veh)} veh`,`peak ${s.count_reference_maximum_queue_time_la.slice(11,16)}`,'accent'],
    ['Queue at 10:00',`${fmt.format(qBoundary)} veh`,`carried from AM into MD`,'teal']
  ].map(x=>`<article><span>${x[0]}</span><strong class="${x[3]||''}">${x[1]}</strong><small>${x[2]}</small></article>`).join('');
  $('boundarySentence').textContent=`${fmt.format(qBoundary)} vehicles remain at the AM→MD boundary and continue into the next five-minute state.`;

  const margin={l:56,r:22,t:20,b:37};
  function chart(id,series,yLabel,extra={}){
    const el=$(id),w=el.clientWidth||900,h=el.clientHeight||320,m=margin;
    const values=series.flatMap(z=>z.values).filter(Number.isFinite),lo=extra.zero?0:Math.min(...values),hi=Math.max(...values)*1.08;
    const x=v=>m.l+v/1440*(w-m.l-m.r),y=v=>h-m.b-(v-lo)/(hi-lo||1)*(h-m.t-m.b);
    const yTicks=[lo,(lo+hi)/2,hi],xTicks=[0,360,600,720,900,1140,1440];
    const path=vals=>vals.map((v,i)=>`${i?'L':'M'}${x(rows[i].minute).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    let svg=`<svg viewBox="0 0 ${w} ${h}"><rect class="episode" x="${x(t0)}" y="${m.t}" width="${x(t3)-x(t0)}" height="${h-m.t-m.b}"/>`;
    svg+=yTicks.map(v=>`<line class="grid" x1="${m.l}" x2="${w-m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${m.l-8}" y="${y(v)+3}" text-anchor="end">${fmt.format(v)}</text>`).join('');
    svg+=xTicks.map(v=>`<text class="axis" x="${x(v)}" y="${h-13}" text-anchor="middle">${time(v)}</text>`).join('');
    if(extra.threshold) svg+=`<line class="threshold" x1="${m.l}" x2="${w-m.r}" y1="${y(extra.threshold)}" y2="${y(extra.threshold)}"/><text class="axis" x="${w-m.r}" y="${y(extra.threshold)-6}" text-anchor="end">entry ${extra.threshold.toFixed(1)} mph</text>`;
    svg+=`<line class="boundary" x1="${x(boundary)}" x2="${x(boundary)}" y1="${m.t}" y2="${h-m.b}"/><text class="axis" x="${x(boundary)+6}" y="${m.t+11}">10:00 · AM→MD</text>`;
    if(extra.t2) svg+=`<line class="t2" x1="${x(t2)}" x2="${x(t2)}" y1="${m.t}" y2="${h-m.b}"/>`;
    series.forEach(z=>svg+=`<path class="line ${z.className}" d="${path(z.values)}"/>`);svg+='</svg>';
    el.innerHTML=svg+`<div class="legend">${series.map(z=>`<span><i style="background:${z.color};${z.dashed?'height:0;border-top:2px dashed '+z.color:''}"></i>${z.label}</span>`).join('')}</div>`;
    const overlay=document.createElement('div');overlay.style.cssText='position:absolute;inset:20px 22px 37px 56px;cursor:crosshair';el.appendChild(overlay);
    overlay.addEventListener('mousemove',e=>{const rect=overlay.getBoundingClientRect(),min=Math.max(0,Math.min(1435,(e.clientX-rect.left)/rect.width*1440)),idx=Math.round(min/5),r=rows[idx],tip=$('tooltip');tip.innerHTML=`<b>${r.time} · ${r.period}</b><br>${series.map(z=>`${z.label}: ${fmt.format(z.values[idx])} ${yLabel}`).join('<br>')}`;tip.style.display='block';tip.style.left=`${e.clientX+14}px`;tip.style.top=`${e.clientY+14}px`});
    overlay.addEventListener('mouseleave',()=>{$('tooltip').style.display='none'});
  }

  chart('speedChart',[{label:'observed speed',values:rows.map(r=>r.speed),className:'speed',color:'#2e73bb'}],'mph',{threshold:s.entry_threshold_mph,t2:true});
  chart('queueChart',[
    {label:'count-based Q reference',values:rows.map(r=>r.queue_ref),className:'queue-ref',color:'#ef7840'},
    {label:'speed-delay diagnostic only',values:rows.map(r=>r.queue_speed_diagnostic),className:'queue-diag',color:'#8467b2',dashed:true}
  ],'vehicles',{zero:true});

  window.addEventListener('resize',()=>location.reload());
})();
