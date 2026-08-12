(() => {
  const data=window.QVDF_MULTI, cases=data.cases, supported=cases.filter(d=>d.final_supported);
  const $=id=>document.getElementById(id), fmt=new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
  const state={case:supported[0]};
  const statusLabel={not_identified_no_speed_episode:'No episode',not_identified_speed_branch_failure:'Speed gate failed',not_identified_duration_extrapolation:'Duration gate failed',identified_under_calibrated_qvdf:'Supported'};
  const hour=m=>m/60, time=m=>`${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;
  const minuteFromIso=s=>{const m=String(s||'').match(/T(\d\d):(\d\d):(\d\d)/);return m?+m[1]*60 + +m[2] + +m[3]/60:null};
  const apeClass=v=>v<15?'ape-low':v<30?'ape-mid':'ape-high';
  const pct=v=>`${v.toFixed(2)}%`;

  // Peak demand D and period volume V are the same estimate in two units:
  // V_inferred = D_inferred / PLF with a per-link peak-load factor calibrated on
  // the training weeks. Both are shown because the advisor asked for the D
  // triple, but they are not two independent checks.
  (function comparisonBlock(){
    const c=data.comparison; if(!c) return;
    const s1=c.supported_cases, all=c.all_episode_cases;
    $('dvMetrics').innerHTML=[
      ['Peak demand D',pct(s1.demand_D.mape_pct),`MAE ${fmt.format(s1.demand_D.mae)} veh/h · bias ${fmt.format(s1.demand_D.bias)}`,'orange'],
      ['Period volume V',pct(s1.volume_V.mape_pct),`MAE ${fmt.format(s1.volume_V.mae)} veh · bias ${fmt.format(s1.volume_V.bias)}`,'orange'],
      ['Inferred D/C',pct(s1.d_over_c.mape_pct),`MAE ${s1.d_over_c.mae.toFixed(2)} · bias ${s1.d_over_c.bias.toFixed(2)}`,''],
      ['Minimum speed v(T2)',`${s1.vT2_mae_mph.toFixed(2)} mph`,'MAE on supported cases','teal']
    ].map(m=>`<article><span>${m[0]}</span><strong class="${m[3]}">${m[1]}</strong><small>${m[2]}</small></article>`).join('');
    $('comparisonNote').textContent=
      `Errors are conditional on the ${c.coverage.supported_both_gates} supported cases `
      + `(${c.coverage.supported_pct.toFixed(2)}% of ${c.coverage.total_cases}); the method `
      + `abstains on the other ${c.coverage.abstained}. Across all `
      + `${all.demand_D.cases} episode cases, before the support gates, demand MAPE is `
      + `${pct(all.demand_D.mape_pct)} and volume MAPE ${pct(all.volume_V.mape_pct)}. `
      + `V and D are one estimate in two units: V = D / PLF with a per-link peak-load `
      + `factor from the training weeks, so they are not independent checks. `
      + `P is observed and is an input to the inversion, not a prediction.`;
  })();

  // Forward projection: the inferred state pushed back through the QVDF speed
  // map. The duration branch round-trips by construction, so what is on trial
  // here is the frozen severity branch and the (1-tau^2)^2 episode shape.
  const PERIOD_WINDOW={AM:[360,600],PM:[900,1140]};
  (function projectionBlock(){
    const p=data.projection; if(!p) return;
    const s=p.supported_cases, d=p.period_error_decomposition_supported;
    $('projectionIntro').textContent=p.what_is_predicted;
    $('projectionMetrics').innerHTML=[
      ['Congested window',`${s.model_window.forward.mae_mph.toFixed(2)} mph`,`MAE · bias ${s.model_window.forward.bias_mph.toFixed(2)}`,'teal'],
      ['Whole period',`${s.period.forward.mae_mph.toFixed(2)} mph`,`MAE · bias +${s.period.forward.bias_mph.toFixed(2)}`,'orange'],
      ['Skill vs free-flow',s.period.forward.skill_vs_free_flow.toFixed(3),`baseline MAE ${s.period.free_flow_baseline.mae_mph.toFixed(1)} mph`,''],
      ['Worst 5-min bin',`${s.period.forward.max_abs_error_mph.toFixed(1)} mph`,'largest single-bin error','']
    ].map(m=>`<article><span>${m[0]}</span><strong class="${m[3]}">${m[1]}</strong><small>${m[2]}</small></article>`).join('');
    $('projectionNote').textContent=
      `Scored on the ${p.coverage.supported_cases} supported cases. `
      + `Handing the model the observed depth instead of the predicted one changes the `
      + `congested-window MAE only from ${s.model_window.forward.mae_mph.toFixed(2)} to `
      + `${s.model_window.shape_only.mae_mph.toFixed(2)} mph, so the frozen severity branch is not `
      + `the binding error. The episode is symmetric about T₂ but the detected one is not: `
      + `T₂ sits ${Math.abs(p.episode_alignment.T2_minus_episode_midpoint_min_mean).toFixed(1)} min off the `
      + `episode midpoint on average, up to ${p.episode_alignment.T2_minus_episode_midpoint_min_abs_max.toFixed(0)} min.`;
    const inside=d.inside_model_window, outside=d.outside_model_window, check=d.outside_window_reality_check;
    $('projectionSplit').innerHTML=`
      <h3>Where the period error actually comes from</h3>
      <div class="split-bar" style="display:flex;height:30px;border-radius:7px;overflow:hidden;color:#fff;font-size:11px;font-weight:700"><span class="split-in" style="width:${inside.sse_share_pct.toFixed(1)}%;background:#3f7ea8;display:flex;align-items:center;justify-content:center">${inside.sse_share_pct.toFixed(0)}%</span><span class="split-out" style="width:${outside.sse_share_pct.toFixed(1)}%;background:#ee783f;display:flex;align-items:center;justify-content:center">${outside.sse_share_pct.toFixed(0)}%</span></div>
      <div class="split-legend"><span><i class="in" style="background:#3f7ea8"></i>inside the modelled episode · ${inside.bin_share_pct.toFixed(0)}% of bins · MAE ${inside.mae_mph.toFixed(2)} mph · bias ${inside.bias_mph.toFixed(2)}</span><span><i class="out" style="background:#ee783f"></i>outside, where the model asserts free flow · ${outside.bin_share_pct.toFixed(0)}% of bins · MAE ${outside.mae_mph.toFixed(2)} mph · bias +${outside.bias_mph.toFixed(2)}</span></div>
      <p>Inside its own window the model is essentially unbiased. Outside it, the error is one-sided and large: ${check.bins_below_90pct_free_speed_pct.toFixed(0)}% of those bins are still below 90% of free speed and ${check.bins_below_cutoff_speed_pct.toFixed(0)}% are below the cutoff speed v₍c₎ the model itself uses to define congestion. Across the period, ${d.period_congestion_coverage.period_bins_below_cutoff_speed_pct.toFixed(0)}% of bins are congested by that definition while the modelled episode covers ${d.period_congestion_coverage.model_window_share_of_period_pct.toFixed(0)}%. The boxcar edge, not the depth of the dip, is what limits the speed projection.</p>`;
  })();

  // Two lines and the gap between them: observed speed, reconstructed speed,
  // and the error shaded in. Every colour is an inline SVG attribute rather
  // than a CSS class, so the chart still reads correctly if the stylesheet is
  // stale or missing (an unstyled <path> defaults to a solid black fill).
  function renderProjection(){
    const el=$('projectionChart'),d=state.case;
    const curve=data.projectionCurves[`${d.link_id}|${d.period}|${d.week_start}`];
    if(!curve){el.innerHTML='<div class="empty">No holdout episode: the speed map is never entered for this case.</div>';return}
    const [lo_m,hi_m]=PERIOD_WINDOW[d.period];
    const obs=data.profiles[`${d.link_id}|${d.week_start}`].filter(p=>p[0]>=lo_m&&p[0]<hi_m).map(p=>[p[0],p[1]]);
    const fwd=curve.map(c=>[c[0],c[1]]);
    const {w,h,m}=dims(el,{l:52,r:104,t:26,b:46});
    const all=[...obs.map(p=>p[1]),...fwd.map(p=>p[1])];
    const lo=Math.floor(Math.min(...all)-4),hi=Math.ceil(Math.max(...all)+4);
    const x=scale(lo_m,hi_m,m.l,w-m.r),y=scale(lo,hi,h-m.b,m.t);

    // Error ribbon, split where the model is too fast vs too slow. The
    // observed grid and the model grid share timestamps, so they pair directly.
    const paired=fwd.map((f,i)=>[f[0],f[1],obs[i]?obs[i][1]:null]).filter(p=>p[2]!==null);
    const ribbons=[];
    let run=[];
    const flush=()=>{
      if(run.length<2){run=[];return}
      const top=run.map(p=>[p[0],p[1]]),bottom=[...run].reverse().map(p=>[p[0],p[2]]);
      const tooFast=run[0][1]>run[0][2];
      ribbons.push(`<path d="${linePath(top,x,y)} ${linePath(bottom,x,y).replace('M','L')} Z" fill="${tooFast?'#ee783f':'#256fd2'}" fill-opacity=".17" stroke="none"/>`);
      run=[];
    };
    paired.forEach((p,i)=>{
      if(i&&Math.sign(p[1]-p[2])!==Math.sign(paired[i-1][1]-paired[i-1][2])){const last=run[run.length-1];flush();run.push(last)}
      run.push(p);
    });
    flush();

    // The modelled episode marked on the axis, not as a fill over the plot.
    const win=curve.filter(c=>c[3]===1).map(c=>c[0]);
    const t0=minuteFromIso(d.t0_la),t3=minuteFromIso(d.t3_la);
    const baseY=h-m.b;
    const spanBar=(from,to,offset,colour,label)=>{
      const x1=x(Math.max(from,lo_m)),x2=x(Math.min(to,hi_m));
      return `<line x1="${x1}" x2="${x2}" y1="${baseY+offset}" y2="${baseY+offset}" stroke="${colour}" stroke-width="5" stroke-linecap="round"/><text x="${x2+7}" y="${baseY+offset+3.5}" fill="${colour}" font="600 9px 'DM Sans'" font-size="9" font-weight="600">${label}</text>`;
    };
    const spans=(win.length?spanBar(win[0],win[win.length-1],11,'#ee783f','modelled episode'):'')
      + spanBar(t0,t3,22,'#0f8b7f','detected episode');

    const stat=data.projectionMetrics[`${d.link_id}|${d.period}|${d.week_start}`];
    const endLabel=(pts,colour,text)=>{
      const last=pts[pts.length-1];
      return `<text x="${x(last[0])+8}" y="${y(last[1])+4}" fill="${colour}" font-size="11" font-weight="700">${text}</text>`;
    };
    const ticks=[lo_m,(lo_m+hi_m)/2,hi_m];
    el.innerHTML=`<svg viewBox="0 0 ${w} ${h}">`
      + axes(w,h,m,ticks,[lo,(lo+hi)/2,hi],x,y,v=>time(v),v=>Math.round(v))
      + ribbons.join('')
      + `<path d="${linePath(fwd,x,y)}" fill="none" stroke="#ee783f" stroke-width="2.6" stroke-linejoin="round"/>`
      + `<path d="${linePath(obs,x,y)}" fill="none" stroke="#256fd2" stroke-width="2.6" stroke-linejoin="round"/>`
      + endLabel(fwd,'#ee783f','reconstructed')
      + endLabel(obs,'#256fd2','observed')
      + spans
      + `<text class="axis-label" transform="translate(14 ${(m.t+baseY)/2}) rotate(-90)" text-anchor="middle">Speed (mph)</text>`
      + `</svg>`
      + `<div class="chart-legend"><span><i style="background:#256fd2"></i>observed</span><span><i style="background:#ee783f"></i>reconstructed from the inferred state</span><span><i style="background:#ee783f;opacity:.35"></i>model too fast</span><span><i style="background:#256fd2;opacity:.35"></i>model too slow</span>`
      + (stat?`<span class="chart-stat">this case · MAE ${stat.mae_mph.toFixed(2)} mph · bias ${stat.bias_mph>=0?'+':'−'}${Math.abs(stat.bias_mph).toFixed(2)}</span>`:'')
      + `</div>`;
  }

  function options(){
    $('linkSelect').innerHTML=data.links.map(v=>`<option>${v}</option>`).join('');
    $('linkSelect').value=state.case.link_id;
    syncPeriods();
  }
  function syncPeriods(){
    const periods=['AM','PM'];
    $('periodSelect').innerHTML=periods.map(v=>`<option>${v}</option>`).join('');
    if(periods.includes(state.case.period)) $('periodSelect').value=state.case.period;
    syncWeeks();
  }
  function syncWeeks(){
    const matches=cases.filter(d=>d.link_id===$('linkSelect').value&&d.period===$('periodSelect').value);
    $('weekSelect').innerHTML=matches.map(d=>`<option value="${d.week_start}">${d.week_start}</option>`).join('');
    if(matches.some(d=>d.week_start===state.case.week_start)) $('weekSelect').value=state.case.week_start;
    state.case=matches.find(d=>d.week_start===$('weekSelect').value)||matches[0];
    render();
  }
  $('linkSelect').addEventListener('change',()=>{state.case=cases.find(d=>d.link_id===$('linkSelect').value&&d.period===$('periodSelect').value&&d.week_start===$('weekSelect').value)||cases.find(d=>d.link_id===$('linkSelect').value);syncPeriods()});
  $('periodSelect').addEventListener('change',()=>{state.case=cases.find(d=>d.link_id===$('linkSelect').value&&d.period===$('periodSelect').value&&d.week_start===$('weekSelect').value)||cases.find(d=>d.link_id===$('linkSelect').value&&d.period===$('periodSelect').value);syncWeeks()});
  $('weekSelect').addEventListener('change',()=>{state.case=cases.find(d=>d.link_id===$('linkSelect').value&&d.period===$('periodSelect').value&&d.week_start===$('weekSelect').value);render()});

  function render(){renderTimeline();renderSummary();renderSpeed();renderVolume();renderCalibration();renderWeeklyVolumes();renderProjection();renderTable()}
  function renderTimeline(){
    const weeks=[...data.weeks.slice(0,4),'2025-06-30',...data.weeks.slice(4)];
    $('weekTimeline').innerHTML=weeks.map(w=>{
      const kind=w==='2025-06-30'?'holiday':w===state.case.week_start?'holdout':'training';
      const label=kind==='holiday'?'excluded':kind;
      return `<div class="week ${kind}"><b>${w.slice(5)}</b><span>${label}</span></div>`
    }).join('');
  }
  function renderSummary(){
    const d=state.case;
    const hasEpisode=!!d.episode_identified, hasCandidate=Number.isFinite(d.V_hat_veh), status=statusLabel[d.inverse_status]||d.inverse_status;
    $('caseSummary').innerHTML=[
      ['Case',`${d.link_id} · ${d.period}`,d.week_start],
      ['Congestion P',hasEpisode?`${d.P_h.toFixed(2)} h`:'Not identified',hasEpisode?`T₂ ${String(d.T2_la).slice(11,16)} LA`:'no canonical speed episode'],
      ['Inferred D/C',Number.isFinite(d.x_hat_D_over_C)?d.x_hat_D_over_C.toFixed(2):'Not inferred',Number.isFinite(d.training_max_observed_D_over_C)?`training max ${d.training_max_observed_D_over_C.toFixed(2)}`:'insufficient episode evidence'],
      ['Observed V',fmt.format(d.observed_average_period_volume_veh),'vehicles'],
      [hasCandidate?(d.final_supported?'Inferred V̂':'Candidate V̂'):'Inferred V̂',hasCandidate?fmt.format(d.V_hat_veh):'Abstained',hasCandidate?`${d.absolute_percentage_error_pct.toFixed(2)}% retrospective APE`:'no point estimate'],
      ['Inference status',d.final_supported?'PASS':'ABSTAIN',status,d.final_supported?'pass':hasEpisode?'fail':'abstain'],
    ].map(x=>`<article class="${x[3]||''}"><span>${x[0]}</span><strong>${x[1]}</strong><small>${x[2]}</small></article>`).join('');
    const reason=$('failureReason');
    if(d.final_supported){reason.hidden=true;reason.className='failure-reason';return}
    reason.hidden=false;
    if(d.inverse_status==='not_identified_no_speed_episode'){
      reason.className='failure-reason no-episode';
      reason.innerHTML='<strong>Why this case abstains: no canonical episode</strong>The holdout speed profile does not contain a persistent congestion-and-recovery episode, so P, T₂, D/C, and period volume are not identifiable from speed alone.';
    }else if(d.inverse_status==='not_identified_speed_branch_failure'){
      reason.className='failure-reason';
      reason.innerHTML=`<strong>Why this case abstains: speed-consistency gate failed</strong>An episode was detected, but the frozen severity branch does not reproduce the holdout minimum speed closely enough. Severity ratio: ${d.severity_ratio.toFixed(2)} (allowed 0.50–2.00); |v̂(T₂) − vobs(T₂)|: ${Math.abs(d.vT2_error_mph).toFixed(2)} mph (allowed ≤10 mph).`;
    }else if(d.inverse_status==='not_identified_duration_extrapolation'){
      reason.className='failure-reason duration';
      reason.innerHTML=`<strong>Why this case abstains: duration-extrapolation gate failed</strong>The inferred D/C is ${d.duration_extrapolation_ratio.toFixed(2)}× the largest training-episode D/C, exceeding the allowed 1.25× calibration envelope.`;
    }else{
      reason.className='failure-reason';reason.innerHTML=`<strong>Why this case abstains</strong>${status}.`;
    }
  }
  const dims=(el,m={l:48,r:18,t:20,b:36})=>({w:el.clientWidth||600,h:el.clientHeight||300,m});
  const scale=(a,b,c,d)=>x=>c+(x-a)*(d-c)/(b-a||1);
  const linePath=(pts,x,y)=>pts.map((p,i)=>`${i?'L':'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
  function axes(w,h,m,xTicks,yTicks,x,y,xFmt=v=>v,yFmt=v=>v){
    return `<g>${yTicks.map(v=>`<line class="grid-line" x1="${m.l}" x2="${w-m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-text" x="${m.l-8}" y="${y(v)+3}" text-anchor="end">${yFmt(v)}</text>`).join('')}${xTicks.map(v=>`<text class="axis-text" x="${x(v)}" y="${h-22}" text-anchor="middle">${xFmt(v)}</text>`).join('')}</g>`
  }
  function renderSpeed(){
    const el=$('speedChart'),d=state.case,pts=data.profiles[`${d.link_id}|${d.week_start}`].map(p=>[p[0],p[1]]),{w,h,m}=dims(el),ys=pts.map(p=>p[1]),lo=Math.floor(Math.min(...ys)-3),hi=Math.ceil(Math.max(...ys)+3),x=scale(0,1440,m.l,w-m.r),y=scale(lo,hi,h-m.b,m.t),yt=[lo,(lo+hi)/2,hi];
    let episode='';
    if(d.episode_identified){
      const t0=minuteFromIso(d.t0_la),t2=minuteFromIso(d.T2_la),t3=minuteFromIso(d.t3_la);
      episode=`<rect class="episode-area" x="${x(t0)}" y="${m.t}" width="${Math.max(1,x(t3)-x(t0))}" height="${h-m.t-m.b}"/><line class="cutoff-line" x1="${m.l}" x2="${w-m.r}" y1="${y(d.cutoff_speed_vc_mph)}" y2="${y(d.cutoff_speed_vc_mph)}"/><line class="t2-line" x1="${x(t2)}" x2="${x(t2)}" y1="${m.t}" y2="${h-m.b}"/><circle cx="${x(t2)}" cy="${y(d.vT2_mph)}" r="4" fill="#df4b42"/><text class="axis-label" x="${x(t2)+7}" y="${y(d.vT2_mph)-8}">T₂ · ${d.vT2_mph.toFixed(1)} mph</text>`;
    }
    el.innerHTML=`<svg viewBox="0 0 ${w} ${h}">${axes(w,h,m,[0,360,720,1080,1440],yt,x,y,v=>time(v),v=>Math.round(v))}${episode}<path class="speed-line" d="${linePath(pts,x,y)}"/></svg><div class="chart-legend"><span><i style="background:#256fd2"></i>speed</span>${d.episode_identified?'<span><i style="background:#ee783f"></i>episode</span><span><i style="background:#0f8b7f"></i>v₍c₎</span>':'<span>no canonical episode</span>'}</div>`;
  }
  function renderVolume(){
    const el=$('volumeChart'),d=state.case,{w,h,m}=dims(el,{l:58,r:25,t:25,b:48}),hasCandidate=Number.isFinite(d.V_hat_veh),vals=[d.observed_average_period_volume_veh,...(hasCandidate?[d.V_hat_veh]:[])],max=Math.max(...vals)*1.18,y=scale(0,max,h-m.b,m.t),barW=Math.min(90,(w-m.l-m.r)/4),centers=[m.l+(w-m.l-m.r)*.3,m.l+(w-m.l-m.r)*.7];
    const inferredClass=d.final_supported?'inf-bar':d.inverse_status==='not_identified_duration_extrapolation'?'duration-bar':'failed-bar';
    const inferred=hasCandidate?`<rect class="${inferredClass}" x="${centers[1]-barW/2}" y="${y(d.V_hat_veh)}" width="${barW}" height="${h-m.b-y(d.V_hat_veh)}" rx="7"/><text class="bar-label" x="${centers[1]}" y="${y(d.V_hat_veh)-9}" text-anchor="middle">${fmt.format(d.V_hat_veh)}</text><text class="axis-label" x="${centers[1]}" y="${h-14}" text-anchor="middle">${d.final_supported?'Inferred V̂':'Rejected candidate V̂'}</text>`:`<text class="no-estimate" x="${centers[1]}" y="${(m.t+h-m.b)/2}" text-anchor="middle">No volume estimate</text><text class="axis-label" x="${centers[1]}" y="${h-14}" text-anchor="middle">Abstained</text>`;
    el.innerHTML=`<svg viewBox="0 0 ${w} ${h}">${axes(w,h,m,[],[0,max/2,max],v=>v,y,v=>v,v=>fmt.format(v))}<rect class="obs-bar" x="${centers[0]-barW/2}" y="${y(d.observed_average_period_volume_veh)}" width="${barW}" height="${h-m.b-y(d.observed_average_period_volume_veh)}" rx="7"/><text class="bar-label" x="${centers[0]}" y="${y(d.observed_average_period_volume_veh)-9}" text-anchor="middle">${fmt.format(d.observed_average_period_volume_veh)}</text><text class="axis-label" x="${centers[0]}" y="${h-14}" text-anchor="middle">Observed V</text>${inferred}</svg>`;
  }
  function renderCalibration(){
    const el=$('calibrationChart'),d=state.case;
    if(!d.episode_identified){el.innerHTML='<div class="empty">No holdout episode: duration inversion is not attempted.</div>';return}
    if(!Number.isFinite(d.x_hat_D_over_C)||!Number.isFinite(d.training_max_observed_D_over_C)){el.innerHTML='<div class="empty">Insufficient training episodes for the duration branch.</div>';return}
    const train=cases.filter(x=>x.link_id===d.link_id&&x.period===d.period&&x.week_start!==d.week_start&&x.episode_identified).map(x=>[x.P_h,x.observed_peak_1h_demand_veh_h/d.capacity_vph]),hold=[d.P_h,d.x_hat_D_over_C],all=[...train,hold],{w,h,m}=dims(el,{l:52,r:22,t:24,b:42}),xmax=Math.max(...all.map(p=>p[0]))*1.15,ymax=Math.max(...all.map(p=>p[1]),d.training_max_observed_D_over_C*1.25)*1.15,x=scale(0,xmax,m.l,w-m.r),y=scale(0,ymax,h-m.b,m.t),limit=d.training_max_observed_D_over_C*1.25;
    el.innerHTML=`<svg viewBox="0 0 ${w} ${h}">${axes(w,h,m,[0,xmax/2,xmax],[0,ymax/2,ymax],x,y,v=>v.toFixed(1),v=>v.toFixed(1))}<line class="limit-line" x1="${m.l}" x2="${w-m.r}" y1="${y(limit)}" y2="${y(limit)}"/><text class="axis-text" x="${w-m.r}" y="${y(limit)-6}" text-anchor="end">1.25× training max</text>${train.map(p=>`<circle class="training-dot" cx="${x(p[0])}" cy="${y(p[1])}" r="5"/>`).join('')}<circle class="holdout-dot" cx="${x(hold[0])}" cy="${y(hold[1])}" r="7"/><text class="axis-label" x="${x(hold[0])+9}" y="${y(hold[1])-8}">holdout</text><text class="axis-label" x="${(m.l+w-m.r)/2}" y="${h-8}" text-anchor="middle">Congestion duration P (h)</text><text class="axis-label" transform="translate(13 ${(m.t+h-m.b)/2}) rotate(-90)" text-anchor="middle">Demand / capacity</text></svg><div class="chart-legend"><span><i style="background:#8fb0c5"></i>training episodes</span><span><i style="background:#ee783f"></i>holdout inference</span></div>`;
  }
  function renderWeeklyVolumes(){
    const el=$('weeklyVolumeChart'),d=state.case,rows=cases.filter(x=>x.link_id===d.link_id&&x.period===d.period),{w,h,m}=dims(el,{l:60,r:18,t:22,b:52}),max=Math.max(...rows.flatMap(r=>[r.observed_average_period_volume_veh,r.V_hat_veh||0]))*1.12,y=scale(0,max,h-m.b,m.t),slot=(w-m.l-m.r)/rows.length,bw=Math.min(16,slot*.28);
    const marks=rows.map((r,i)=>{
      const cx=m.l+slot*(i+.5),active=r.week_start===d.week_start,baseY=h-m.b-7;
      let resultMark='';
      if(r.final_supported) resultMark=`<rect class="weekly-inf" x="${cx+1}" y="${y(r.V_hat_veh)}" width="${bw}" height="${h-m.b-y(r.V_hat_veh)}" rx="2" opacity="${active?1:.72}"/>`;
      else if(r.inverse_status==='not_identified_speed_branch_failure') resultMark=`<path class="weekly-speed-fail" d="M${cx+2},${baseY-6} l10,10 M${cx+12},${baseY-6} l-10,10"/>`;
      else if(r.inverse_status==='not_identified_duration_extrapolation') resultMark=`<path class="weekly-duration-fail" d="M${cx+7},${baseY-8} l7,7 -7,7 -7,-7 z"/>`;
      else resultMark=`<circle class="weekly-no-episode" cx="${cx+7}" cy="${baseY}" r="6"/>`;
      return `<rect class="weekly-obs" x="${cx-bw-1}" y="${y(r.observed_average_period_volume_veh)}" width="${bw}" height="${h-m.b-y(r.observed_average_period_volume_veh)}" rx="2" opacity="${active?1:.72}"/>${resultMark}<text class="axis-text" x="${cx}" y="${h-18}" text-anchor="middle" transform="rotate(-35 ${cx} ${h-18})">${r.week_start.slice(5)}</text>${active?`<path d="M${cx-6},${h-m.b+5}h12" stroke="#102b46" stroke-width="3"/>`:''}`;
    }).join('');
    el.innerHTML=`<svg viewBox="0 0 ${w} ${h}">${axes(w,h,m,[],[0,max/2,max],v=>v,y,v=>v,v=>fmt.format(v))}${marks}</svg><div class="chart-legend"><span><i style="background:#74a0bf"></i>observed</span><span><i style="background:#ee783f"></i>supported V̂</span><span style="color:#c84d4d">× speed fail</span><span style="color:#7858a6">◆ duration fail</span><span>○ no episode</span></div>`;
  }
  function renderTable(){
    const delta=(inferred,observed)=>{const diff=inferred-observed;const sign=diff>=0?'+':'−';return `${sign}${fmt.format(Math.abs(diff))}`;};
    $('caseTable').innerHTML=supported.map(d=>`<tr data-key="${d.link_id}|${d.period}|${d.week_start}" class="${d===state.case?'active':''}"><td>${d.link_id}</td><td>${d.period}</td><td>${d.week_start}</td><td>${d.P_h.toFixed(2)}</td><td>${fmt.format(d.observed_peak_1h_demand_veh_h)}</td><td>${fmt.format(d.D_hat_veh_h)}</td><td>${delta(d.D_hat_veh_h,d.observed_peak_1h_demand_veh_h)}</td><td>${fmt.format(d.observed_average_period_volume_veh)}</td><td>${fmt.format(d.V_hat_veh)}</td><td>${delta(d.V_hat_veh,d.observed_average_period_volume_veh)}</td><td class="${apeClass(d.absolute_percentage_error_pct)}">${d.absolute_percentage_error_pct.toFixed(2)}%</td><td class="status-pass">Passed</td></tr>`).join('');
    [...$('caseTable').querySelectorAll('tr')].forEach(tr=>tr.addEventListener('click',()=>{const [l,p,w]=tr.dataset.key.split('|');state.case=supported.find(d=>d.link_id===l&&d.period===p&&d.week_start===w);$('linkSelect').value=l;syncPeriods();$('periodSelect').value=p;syncWeeks();$('weekSelect').value=w;state.case=supported.find(d=>d.link_id===l&&d.period===p&&d.week_start===w);render();window.scrollTo({top:$('linkSelect').getBoundingClientRect().top+window.scrollY-30,behavior:'smooth'})}));
  }
  window.addEventListener('resize',()=>render());
  options();
})();
