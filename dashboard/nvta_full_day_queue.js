(() => {
  const payload = window.NVTA_FULL_DAY;
  const { link, summary, gates, episodes, series, sweep } = payload;
  const branchB = summary.branch_b_speed_inversion;
  const byId = (id) => document.getElementById(id);
  const tooltip = byId('tooltip');
  const num = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const one = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
  const clockLabel = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  const isoClock = (iso) => {
    const match = String(iso).match(/T(\d\d):(\d\d)/);
    const minute = Number(match[1]) * 60 + Number(match[2]);
    return minute < 360 ? minute + 1440 : minute;
  };

  const PERIODS = [['AM', 360, 540, 'am-band'], ['MD', 540, 900, 'md-band'], ['PM', 900, 1140, 'pm-band'], ['NT', 1140, 1800, 'nt-band']];
  const BOUNDARIES = [['AM → MD', 540], ['MD → PM', 900], ['PM → NT', 1140]];
  const START = 360;
  const END = 1800;
  const svgNS = 'http://www.w3.org/2000/svg';

  const el = (name, attrs = {}) => {
    const node = document.createElementNS(svgNS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const path = (points, cls) => el('path', { class: cls, d: points.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ') });

  const qBands = gates.queue_at_reporting_boundaries_veh;
  const qmax = gates.estimated_qmax_veh;
  const residual = branchB.measurement_residual_veh;

  byId('clockNote').textContent = `minutes ${START}–${END} · ${link.date} · America/New_York`;
  byId('footerNote').textContent = `${link.tmc} · link ${link.netLinkId} · ${link.lengthMi.toFixed(2)} mi · ${link.lanes} lanes · ${link.county} County`;
  byId('scopeLine').textContent = gates.what_this_is_not;
  byId('measuredSwing').textContent = num.format(branchB.measurement_largest_single_bin_change_veh);
  byId('recurrenceSwing').textContent = num.format(branchB.largest_single_bin_change_veh);

  // The headline number is the reported run, the one drawn on the chart; the
  // range beneath it is the spread over every assumption combination.
  const baseBoundary = branchB.queue_at_period_boundaries_veh;
  byId('metrics').innerHTML = [
    ['Peak queue', `${num.format(branchB.qmax_veh)} veh`, `range ${num.format(qmax.min)}–${num.format(qmax.max)} across 36 assumption cases`, 'accent'],
    ['At 09:00 AM → MD', `${num.format(baseBoundary['AM->MD 09:00'])} veh`, `range ${num.format(qBands['AM->MD 09:00'].min)}–${num.format(qBands['AM->MD 09:00'].max)}`, 'teal'],
    ['At 15:00 MD → PM', `${num.format(baseBoundary['MD->PM 15:00'])} veh`, `range ${num.format(qBands['MD->PM 15:00'].min)}–${num.format(qBands['MD->PM 15:00'].max)}`, 'teal'],
    ['Model residual', `${one.format(residual.rmse)} veh`, 'RMSE vs speed-implied queue', 'violet']
  ].map((m) => `<article><span>${m[0]}</span><strong class="${m[3]}">${m[1]}</strong><small>${m[2]}</small></article>`).join('');

  byId('boundarySentence').textContent =
    `${num.format(baseBoundary['AM->MD 09:00'])} vehicles remain at 09:00 and ${num.format(baseBoundary['MD->PM 15:00'])} at 15:00. `
    + `The PM episode begins at 14:20, inside MD, so a period-by-period run would start PM from zero and lose that queue entirely.`;

  byId('gateTally').textContent =
    `${gates.gate_tally.pass} pass · ${gates.gate_tally.fail} fail · ${gates.gate_tally.not_testable} not testable`;

  const GATE_TEXT = {
    G1_vehicle_conservation: ['Vehicle conservation', 'Q(t) is produced only by the recurrence, so it carries Q(t−1) and no boundary resets it. Structural, not evidence of magnitude.'],
    G2_speed_consistency: ['Speed consistency', 'Peak sits inside a speed episode and the long free-flow night retains no queue.'],
    G3_spatial_storage: ['Spatial storage', 'Worst-case peak stays inside the link storage, so no spillback is indicated.'],
    G4_occupancy_consistency: ['Occupancy consistency', 'INRIX provides speed only. No occupancy series exists for this link.'],
    G5_boundary_flow_quality: ['Boundary flow quality', 'NVTA has no flow measurement at any boundary, so this gate has no input at all.'],
    G6_temporal_persistence: ['Temporal persistence', 'The recurrence supplies the stock inertia a pointwise read of speed lacks.'],
    G7_cross_method_agreement: ['Cross-method agreement', 'The QVDF prior carries no independent information; its queue follows the capacity assumption.']
  };
  byId('gateGrid').innerHTML = Object.entries(gates.gates).map(([key, gate]) => {
    const [title, note] = GATE_TEXT[key] || [key, ''];
    return `<article><span class="verdict ${gate.verdict}">${gate.verdict.replace('_', ' ')}</span><h3>${title}</h3><p>${note}</p></article>`;
  }).join('');

  byId('episodeKey').innerHTML = episodes.map((e) =>
    `<span><b>${e.id}</b> ${clockLabel(isoClock(e.t0))}→${clockLabel(isoClock(e.t3))} · P ${e.P} h · v(T2) ${e.vT2} mph · asymmetry ${e.asymmetry}</span>`
  ).join('') + `<span><b>Asymmetry</b> below 1 means recovery takes longer than onset</span>`;

  function frame(element, yMax, yMin = 0) {
    const width = element.clientWidth || 1000;
    const height = element.clientHeight || 360;
    const margin = { left: 62, right: 26, top: 26, bottom: 40 };
    const x = (m) => margin.left + ((m - START) / (END - START)) * (width - margin.left - margin.right);
    const y = (v) => height - margin.bottom - ((v - yMin) / (yMax - yMin || 1)) * (height - margin.top - margin.bottom);
    const svg = el('svg', { viewBox: `0 0 ${width} ${height}` });
    PERIODS.forEach(([label, lo, hi, cls]) => {
      svg.appendChild(el('rect', { class: cls, x: x(lo), y: margin.top, width: x(hi) - x(lo), height: height - margin.top - margin.bottom }));
      const text = el('text', { class: 'axis-label', x: (x(lo) + x(hi)) / 2, y: margin.top - 10, 'text-anchor': 'middle' });
      text.textContent = label;
      svg.appendChild(text);
    });
    for (let m = 360; m <= END; m += 180) {
      svg.appendChild(el('line', { class: 'grid', x1: x(m), x2: x(m), y1: margin.top, y2: height - margin.bottom }));
      const t = el('text', { class: 'axis', x: x(m), y: height - margin.bottom + 16, 'text-anchor': 'middle' });
      t.textContent = clockLabel(m % 1440);
      svg.appendChild(t);
    }
    return { svg, x, y, width, height, margin };
  }

  function yAxis(ctx, values, format = (v) => num.format(v)) {
    values.forEach((v) => {
      ctx.svg.appendChild(el('line', { class: 'grid', x1: ctx.margin.left, x2: ctx.width - ctx.margin.right, y1: ctx.y(v), y2: ctx.y(v) }));
      const t = el('text', { class: 'axis', x: ctx.margin.left - 9, y: ctx.y(v) + 3, 'text-anchor': 'end' });
      t.textContent = format(v);
      ctx.svg.appendChild(t);
    });
  }

  function hover(node, html) {
    node.addEventListener('mousemove', (event) => {
      tooltip.style.display = 'block';
      tooltip.innerHTML = html;
      tooltip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 220)}px`;
      tooltip.style.top = `${event.clientY - 12}px`;
    });
    node.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
  }

  function drawQueue() {
    const element = byId('queueChart');
    element.innerHTML = '';
    const top = Math.max(...series.map((r) => r.queueHigh)) * 1.12;
    const ctx = frame(element, top);
    yAxis(ctx, [0, 100, 200, 300, 400].filter((v) => v <= top));

    const upper = series.map((r) => [ctx.x(r.clock), ctx.y(r.queueHigh)]);
    const lower = series.map((r) => [ctx.x(r.clock), ctx.y(r.queueLow)]).reverse();
    ctx.svg.appendChild(el('path', { class: 'queue-band', d: [...upper, ...lower].map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ') + ' Z' }));

    series.filter((r) => r.queueMeasured > 0).forEach((r) => {
      ctx.svg.appendChild(el('circle', { class: 'measure-dot', cx: ctx.x(r.clock), cy: ctx.y(r.queueMeasured), r: 2.1 }));
    });
    ctx.svg.appendChild(path(series.map((r) => [ctx.x(r.clock), ctx.y(r.queue)]), 'queue-line'));

    BOUNDARIES.forEach(([label, minute]) => {
      const row = series.find((r) => r.clock === minute);
      if (!row) return;
      ctx.svg.appendChild(el('line', { class: 'boundary-line', x1: ctx.x(minute), x2: ctx.x(minute), y1: ctx.margin.top, y2: ctx.height - ctx.margin.bottom }));
      ctx.svg.appendChild(el('circle', { class: 'handoff-dot', cx: ctx.x(minute), cy: ctx.y(row.queue), r: 5.5 }));
      const t = el('text', { class: 'marker-label', x: ctx.x(minute) + 8, y: ctx.y(row.queue) - 10 });
      t.textContent = `${label} · ${num.format(row.queue)} veh`;
      ctx.svg.appendChild(t);
    });

    const overlay = el('rect', { x: ctx.margin.left, y: ctx.margin.top, width: ctx.width - ctx.margin.left - ctx.margin.right, height: ctx.height - ctx.margin.top - ctx.margin.bottom, fill: 'transparent' });
    overlay.addEventListener('mousemove', (event) => {
      const rect = element.getBoundingClientRect();
      const minute = START + ((event.clientX - rect.left - ctx.margin.left) / (ctx.width - ctx.margin.left - ctx.margin.right)) * (END - START);
      const row = series.reduce((best, r) => (Math.abs(r.clock - minute) < Math.abs(best.clock - minute) ? r : best), series[0]);
      tooltip.style.display = 'block';
      tooltip.innerHTML = `<b>${row.time}</b> · ${row.period}<br>queue ${one.format(row.queue)} veh <span style="opacity:.65">[${num.format(row.queueLow)}–${num.format(row.queueHigh)}]</span><br>speed ${row.speedRaw} mph<br>λ ${num.format(row.lambdaB)} · μ ${num.format(row.mu)} veh/h`;
      tooltip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 230)}px`;
      tooltip.style.top = `${event.clientY - 12}px`;
    });
    overlay.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
    ctx.svg.appendChild(overlay);
    element.appendChild(ctx.svg);
  }

  function drawInertia() {
    const element = byId('inertiaChart');
    element.innerHTML = '';
    const stepOf = (key) => series.map((r, i) => (i ? Math.abs(r[key] - series[i - 1][key]) : 0));
    const measured = stepOf('queueMeasured');
    const recurrence = stepOf('queue');
    const top = Math.max(...measured) * 1.12;
    const ctx = frame(element, top);
    yAxis(ctx, [0, 50, 100, 150].filter((v) => v <= top));
    ctx.svg.appendChild(path(series.map((r, i) => [ctx.x(r.clock), ctx.y(measured[i])]), 'step-line step-measured'));
    ctx.svg.appendChild(path(series.map((r, i) => [ctx.x(r.clock), ctx.y(recurrence[i])]), 'step-line step-recurrence'));
    const legend = [['pointwise from speed', '#8fa1ad', 20], ['recurrence estimate', '#ec7541', 200]];
    legend.forEach(([label, colour, offset]) => {
      ctx.svg.appendChild(el('line', { x1: ctx.margin.left + offset, x2: ctx.margin.left + offset + 18, y1: ctx.margin.top + 6, y2: ctx.margin.top + 6, stroke: colour, 'stroke-width': 2.6 }));
      const t = el('text', { class: 'axis', x: ctx.margin.left + offset + 24, y: ctx.margin.top + 9 });
      t.textContent = label;
      ctx.svg.appendChild(t);
    });
    element.appendChild(ctx.svg);
  }

  function drawSpeed() {
    const element = byId('speedChart');
    element.innerHTML = '';
    const ctx = frame(element, 80);
    yAxis(ctx, [0, 20, 40, 60, 80]);
    ctx.svg.appendChild(path(series.map((r) => [ctx.x(r.clock), ctx.y(r.speedRaw)]), 'speed-raw'));
    ctx.svg.appendChild(path(series.map((r) => [ctx.x(r.clock), ctx.y(r.speed)]), 'speed-line'));
    const cutoff = 49;
    ctx.svg.appendChild(el('line', { class: 'cutoff-line', x1: ctx.margin.left, x2: ctx.width - ctx.margin.right, y1: ctx.y(cutoff), y2: ctx.y(cutoff) }));
    const cutoffLabel = el('text', { class: 'axis', x: ctx.width - ctx.margin.right - 4, y: ctx.y(cutoff) - 6, 'text-anchor': 'end' });
    cutoffLabel.textContent = 'cutoff 49 mph';
    ctx.svg.appendChild(cutoffLabel);
    episodes.forEach((e) => {
      [['T0', isoClock(e.t0)], ['T2', isoClock(e.t2)], ['T3', isoClock(e.t3)]].forEach(([label, minute]) => {
        ctx.svg.appendChild(el('line', { class: 'marker-line', x1: ctx.x(minute), x2: ctx.x(minute), y1: ctx.margin.top, y2: ctx.height - ctx.margin.bottom }));
        const t = el('text', { class: 'marker-label', x: ctx.x(minute) + 4, y: ctx.margin.top + 14 });
        t.textContent = label;
        ctx.svg.appendChild(t);
      });
      ctx.svg.appendChild(el('circle', { class: 'marker-dot', cx: ctx.x(isoClock(e.t2)), cy: ctx.y(e.vT2), r: 5, fill: '#d6534c' }));
    });
    element.appendChild(ctx.svg);
  }

  function drawSweep() {
    const element = byId('sweepChart');
    element.innerHTML = '';
    const width = element.clientWidth || 1000;
    const height = element.clientHeight || 360;
    const margin = { left: 70, right: 26, top: 26, bottom: 44 };
    const storage = gates.gates.G3_spatial_storage.storage_veh;
    const caps = sweep.map((s) => s.assumed_capacity_vphpl);
    const lo = Math.min(...caps);
    const hi = Math.max(...caps);
    const x = (c) => margin.left + ((c - lo) / (hi - lo)) * (width - margin.left - margin.right);
    const logMin = 1;
    const logMax = 5;
    const y = (v) => {
      const value = Math.max(v, 10);
      return height - margin.bottom - ((Math.log10(value) - logMin) / (logMax - logMin)) * (height - margin.top - margin.bottom);
    };
    const svg = el('svg', { viewBox: `0 0 ${width} ${height}` });
    svg.appendChild(el('rect', { class: 'plausible-band', x: x(1900), y: margin.top, width: x(hi) - x(1900), height: height - margin.top - margin.bottom }));
    const bandLabel = el('text', { class: 'axis-label', x: (x(1900) + x(hi)) / 2, y: margin.top - 8, 'text-anchor': 'middle' });
    bandLabel.textContent = 'PHYSICALLY PLAUSIBLE CAPACITY';
    svg.appendChild(bandLabel);
    [10, 100, 1000, 10000, 100000].forEach((v) => {
      svg.appendChild(el('line', { class: 'grid', x1: margin.left, x2: width - margin.right, y1: y(v), y2: y(v) }));
      const t = el('text', { class: 'axis', x: margin.left - 9, y: y(v) + 3, 'text-anchor': 'end' });
      t.textContent = num.format(v);
      svg.appendChild(t);
    });
    caps.forEach((c, i) => {
      if (i % 3) return;
      const t = el('text', { class: 'axis', x: x(c), y: height - margin.bottom + 16, 'text-anchor': 'middle' });
      t.textContent = num.format(c);
      svg.appendChild(t);
    });
    svg.appendChild(el('line', { class: 'storage-line', x1: margin.left, x2: width - margin.right, y1: y(storage), y2: y(storage) }));
    const storageLabel = el('text', { class: 'axis', x: margin.left + 6, y: y(storage) - 6 });
    storageLabel.textContent = `link storage ${num.format(storage)} veh`;
    svg.appendChild(storageLabel);
    const producing = sweep.filter((s) => s.branch_a_qmax_veh > 1);
    svg.appendChild(path(producing.map((s) => [x(s.assumed_capacity_vphpl), y(s.branch_a_qmax_veh)]), 'sweep-line'));
    sweep.forEach((s) => {
      const node = el('circle', { class: 'sweep-dot', cx: x(s.assumed_capacity_vphpl), cy: y(s.branch_a_qmax_veh), r: s.a_admissible ? 6 : 3.4 });
      hover(node, `<b>${num.format(s.assumed_capacity_vphpl)} vphpl</b><br>peak ${num.format(s.branch_a_qmax_veh)} veh<br>${s.a_admissible ? 'physically admissible' : (s.branch_a_qmax_veh <= 1 ? 'no queue at all' : 'exceeds link storage')}`);
      svg.appendChild(node);
    });
    const axisLabel = el('text', { class: 'axis-label', x: (margin.left + width - margin.right) / 2, y: height - 8, 'text-anchor': 'middle' });
    axisLabel.textContent = 'ASSUMED CAPACITY (VEH/H/LANE)';
    svg.appendChild(axisLabel);
    element.appendChild(svg);
  }

  function drawAll() { drawQueue(); drawInertia(); drawSpeed(); drawSweep(); }
  drawAll();
  let timer;
  window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(drawAll, 160); });
})();
