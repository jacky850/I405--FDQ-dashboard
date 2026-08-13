(() => {
  const data = window.NVTA_CORRIDOR;
  const dur = data.duration, q = data.queue, F = q.falsification_by_accumulation;
  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const clock = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  // Colours are inline SVG attributes throughout: an unstyled <path> falls back
  // to a solid black fill, so a stale cached stylesheet would read as a broken
  // chart rather than an unstyled one.
  const INK = '#10243a', MUTED = '#75858e', GRID = '#e2e9ec';
  const RED = '#d6534c', TEAL = '#118b81', ORANGE = '#ec7541', BLUE = '#3278bc', SLATE = '#8fa1ad';

  (function headline() {
    const cd = q.corridor_level, db = q.by_period;
    $('headline').innerHTML = [
      ['Duration branch · AM', dur.inferred.AM.x_hat_median.toFixed(2) + '×',
        `D/C from P = f_d·(D/C)^n · D ${fmt.format(dur.inferred.AM.D_median_vph)} veh/h`, 'red'],
      ['Conservation · AM', cd.AM.d_over_c.toFixed(2) + '×',
        `D = μ + dQ/dt · D ${fmt.format(cd.AM.peak_1h_demand_vph)} veh/h`, 'teal'],
      ['Duration branch · PM', dur.inferred.PM.x_hat_median.toFixed(2) + '×',
        `D ${fmt.format(dur.inferred.PM.D_median_vph)} veh/h`, 'red'],
      ['Conservation · PM', cd.PM.d_over_c.toFixed(2) + '×',
        `D ${fmt.format(cd.PM.peak_1h_demand_vph)} veh/h`, 'teal'],
    ].map((m) => `<article><span>${m[0]}</span><strong class="${m[3]}">${m[1]}</strong><small>${m[2]}</small></article>`).join('');
  })();

  const dims = (el, m) => ({ w: el.clientWidth || 900, h: el.clientHeight || 320, m });

  function falsifyChart() {
    const el = $('falsifyChart');
    const bars = [
      { label: 'Delay queue implied by observed speed, peak', value: F.observed_delay_queue_max_veh, colour: TEAL },
      { label: 'Corridor storage at jam density', value: F.storage_at_jam_density_veh, colour: SLATE },
      { label: 'AM · implied by duration branch', value: F.AM.implied_queue_accumulation_veh, colour: ORANGE },
      { label: 'PM · implied by duration branch', value: F.PM.implied_queue_accumulation_veh, colour: RED },
    ];
    const { w, h, m } = dims(el, { l: 250, r: 96, t: 26, b: 44 });
    const lo = 100, hi = 60000;
    const x = (v) => m.l + (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * (w - m.l - m.r);
    const ticks = [100, 1000, 10000, 60000];
    const rowH = (h - m.t - m.b) / bars.length;
    const storageX = x(F.storage_at_jam_density_veh);
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}">
      ${ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${h - m.b}" stroke="${GRID}"/><text x="${x(t)}" y="${h - m.b + 18}" text-anchor="middle" fill="${MUTED}" font-size="10">${fmt.format(t)}</text>`).join('')}
      <rect x="${storageX}" y="${m.t}" width="${Math.max(0, x(hi) - storageX)}" height="${h - m.t - m.b}" fill="${RED}" fill-opacity=".07"/>
      <line x1="${storageX}" x2="${storageX}" y1="${m.t}" y2="${h - m.b}" stroke="${RED}" stroke-width="1.6" stroke-dasharray="6 4"/>
      <text x="${storageX + 7}" y="${m.t + 12}" fill="${RED}" font-size="10" font-weight="700">physically impossible beyond here</text>
      ${bars.map((b, i) => {
        const cy = m.t + rowH * (i + 0.5), bh = Math.min(30, rowH * 0.54);
        return `<rect x="${m.l}" y="${cy - bh / 2}" width="${Math.max(2, x(b.value) - m.l)}" height="${bh}" rx="4" fill="${b.colour}"/>
          <text x="${m.l - 12}" y="${cy + 4}" text-anchor="end" fill="${INK}" font-size="11.5">${b.label}</text>
          <text x="${x(b.value) + 9}" y="${cy + 4}" fill="${b.colour}" font-size="12" font-weight="700">${fmt.format(b.value)}</text>`;
      }).join('')}
      <text x="${(m.l + w - m.r) / 2}" y="${h - 8}" text-anchor="middle" fill="${MUTED}" font-size="10" font-weight="700">VEHICLES ACCUMULATED (LOG SCALE)</text>
    </svg>`;
    $('verdict').innerHTML = `<b>The accumulation has nowhere to go</b>
      Demand at the duration branch's level would deposit ${fmt.format(F.AM.implied_queue_accumulation_veh)} vehicles in AM and
      ${fmt.format(F.PM.implied_queue_accumulation_veh)} in PM. The corridor is ${F.corridor_length_mi.toFixed(2)} miles and holds
      ${fmt.format(F.storage_at_jam_density_veh)} vehicles bumper to bumper — so the implied accumulation exceeds the physical
      storage by ${F.AM.times_larger_than_corridor_storage.toFixed(1)}× and ${F.PM.times_larger_than_corridor_storage.toFixed(1)}×,
      and the delay queue implied by the observed speed by ${F.AM.times_larger_than_observed_queue.toFixed(0)}× and
      ${F.PM.times_larger_than_observed_queue.toFixed(0)}×. No calibration choice rescues a demand that cannot fit on the road.`;
  }

  function queueChart() {
    const el = $('queueChart'), s = data.corridorSeries;
    const { w, h, m } = dims(el, { l: 58, r: 20, t: 24, b: 44 });
    const xs = s.map((r) => r[0]), qs = s.map((r) => r[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), qmax = Math.max(...qs) * 1.15;
    const X = (v) => m.l + (v - x0) / (x1 - x0) * (w - m.l - m.r);
    const Y = (v) => (h - m.b) - v / qmax * (h - m.t - m.b);
    const area = `M${X(x0)},${Y(0)} ` + s.map((r) => `L${X(r[0]).toFixed(1)},${Y(r[1]).toFixed(1)}`).join(' ') + ` L${X(x1)},${Y(0)} Z`;
    const line = s.map((r, i) => `${i ? 'L' : 'M'}${X(r[0]).toFixed(1)},${Y(r[1]).toFixed(1)}`).join(' ');
    const peak = s[qs.indexOf(Math.max(...qs))];
    const yTicks = [0, qmax / 2, qmax];
    const bands = [['AM', 300, 600, '#fff0e5'], ['MD', 600, 840, '#e6f3f1'], ['PM', 840, 1200, '#f3ecf7'], ['NT', 1200, 1320, '#edf1f3']];
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}">
      ${bands.map(([l, a, b, c]) => a < x1 ? `<rect x="${X(Math.max(a, x0))}" y="${m.t}" width="${Math.max(0, X(Math.min(b, x1)) - X(Math.max(a, x0)))}" height="${h - m.t - m.b}" fill="${c}"/><text x="${(X(Math.max(a, x0)) + X(Math.min(b, x1))) / 2}" y="${m.t + 13}" text-anchor="middle" fill="${MUTED}" font-size="10" font-weight="700">${l}</text>` : '').join('')}
      ${yTicks.map((t) => `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="${GRID}"/><text x="${m.l - 8}" y="${Y(t) + 3}" text-anchor="end" fill="${MUTED}" font-size="10">${fmt.format(t)}</text>`).join('')}
      ${[360, 540, 720, 900, 1080, 1260].filter((t) => t >= x0 && t <= x1).map((t) => `<text x="${X(t)}" y="${h - m.b + 18}" text-anchor="middle" fill="${MUTED}" font-size="10">${clock(t)}</text>`).join('')}
      <path d="${area}" fill="${TEAL}" fill-opacity=".15"/>
      <path d="${line}" fill="none" stroke="${TEAL}" stroke-width="2.6" stroke-linejoin="round"/>
      <circle cx="${X(peak[0])}" cy="${Y(peak[1])}" r="5" fill="${TEAL}" stroke="#fff" stroke-width="2"/>
      <text x="${X(peak[0]) + 9}" y="${Y(peak[1]) - 8}" fill="${INK}" font-size="11" font-weight="700">${fmt.format(peak[1])} veh · ${clock(peak[0])}</text>
      <text transform="translate(14 ${(m.t + h - m.b) / 2}) rotate(-90)" text-anchor="middle" fill="#536672" font-size="10" font-weight="700">Corridor queue (veh)</text>
    </svg>`;
    $('queueNote').textContent =
      `Summed across all 23 links, because a queue is one physical object spread over consecutive links. Per link it holds about `
      + `15 vehicles and dQ/dt is 0.5% of μ, which collapses the per-link demand estimate onto the assumed service rate; `
      + `across the corridor dQ/dt reaches 15% of μ and the estimate carries signal. That is why the per-link conservation `
      + `column in the table below should be read as a floor, not a measurement.`;
  }

  function convergeChart() {
    const el = $('convergeChart');
    const items = [
      { label: 'PeMS upstream + ramp counts', value: 1.05, colour: TEAL, note: 'measured, ahead of the bottleneck' },
      { label: 'This corridor, conservation (AM)', value: q.corridor_level.AM.d_over_c, colour: BLUE, note: 'speed + geometry, no power law' },
      { label: 'Advisor’s own speed-derived flow', value: 0.97, colour: SLATE, note: 'peak of count_total_15min' },
      { label: 'Duration branch (AM)', value: dur.inferred.AM.x_hat_median, colour: ORANGE, note: 'P = f_d·(D/C)^n' },
      { label: 'Duration branch (PM)', value: dur.inferred.PM.x_hat_median, colour: RED, note: 'P = f_d·(D/C)^n' },
    ];
    const { w, h, m } = dims(el, { l: 250, r: 130, t: 20, b: 40 });
    const max = 5;
    const X = (v) => m.l + v / max * (w - m.l - m.r);
    const rowH = (h - m.t - m.b) / items.length;
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}">
      ${[0, 1, 2, 3, 4, 5].map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="${m.t}" y2="${h - m.b}" stroke="${GRID}"/><text x="${X(t)}" y="${h - m.b + 17}" text-anchor="middle" fill="${MUTED}" font-size="10">${t}×</text>`).join('')}
      <line x1="${X(1)}" x2="${X(1)}" y1="${m.t}" y2="${h - m.b}" stroke="${INK}" stroke-width="1.4"/>
      <text x="${X(1) + 6}" y="${h - m.b - 4}" fill="${INK}" font-size="9.5" font-weight="700">capacity</text>
      ${items.map((it, i) => {
        const cy = m.t + rowH * (i + 0.5), bh = Math.min(22, rowH * 0.5);
        return `<rect x="${m.l}" y="${cy - bh / 2}" width="${Math.max(2, X(it.value) - m.l)}" height="${bh}" rx="4" fill="${it.colour}"/>
          <text x="${m.l - 12}" y="${cy + 4}" text-anchor="end" fill="${INK}" font-size="11.5">${it.label}</text>
          <text x="${X(it.value) + 9}" y="${cy + 4}" fill="${it.colour}" font-size="12" font-weight="700">${it.value.toFixed(2)}×</text>`;
      }).join('')}
    </svg>`;
  }

  function linkTable() {
    $('linkTable').innerHTML = data.links.map((d) => `<tr class="${d.period === 'AM' ? 'am' : ''}">
      <td>${d.link_id}</td><td>${d.period}</td><td>${d.P_h.toFixed(2)}</td>
      <td>${d.vT2_mph.toFixed(1)}</td><td>${d.x_hat_D_over_C.toFixed(2)}</td>
      <td>${fmt.format(d.demand_D_inferred_vph)}</td><td>${fmt.format(d.volume_V_inferred_veh)}</td>
      <td>${fmt.format(d.demand_D_queue_vph)}</td>
      <td class="${d.D_ratio_qvdf_over_queue >= 3 ? 'ratio-high' : ''}">${d.D_ratio_qvdf_over_queue.toFixed(2)}×</td></tr>`).join('');
    $('tableNote').textContent =
      `D and V come from the advisor's own parameters and conventions: a fixed ${data.links[0] ? '49' : '49'} mph cutoff for the episode, `
      + `his period clock, and his n and s rather than the frozen 1.10 and 1.40 used on I-405. The ratio column is the duration `
      + `branch divided by the conservation route on the same link and period.`;
  }

  function caveats() {
    $('caveats').innerHTML = [
      ['The counts here are not measurements',
        'count_total_15min in the handoff is speed-derived. Across 1,564 bins it is a single-valued unimodal function of speed peaking at the cutoff, no bin exceeds capacity (max 99.64%), an S3 inversion reproduces it to 2.73%, and every link reports one lane. Any comparison against it is a self-consistency check.'],
      ['The conservation queue is delay-based',
        'It converts excess travel time into vehicles rather than counting them. Against the counted queue on the PeMS case it correlates 0.485 with peaks 60 minutes apart, so its level is an order of magnitude. The accumulation test above survives that imprecision: the delay queue would have to be wrong by 6.8× to rescue the AM figure.'],
      ['n ≈ 1 is the signature, not the cause',
        'With n = 1.0101 in AM the exponent 1/n is essentially 1, so D/C ≈ P/f_d — duration in hours wearing a ratio’s units. corr(x̂, P/f_d) = 0.9926. That is what circular calibration returns: in the advisor’s table D/C is already a linear rescaling of P (R² = 0.966).'],
      ['One corridor, one average weekday',
        'I-395 NB only, 23 links, the 2025-10-06 to 10-10 average weekday. Nothing here supports a claim about I-66, I-395 SB, or any individual day. The advisor’s parameters were calibrated on this corridor, so applying them elsewhere is a further assumption.'],
    ].map((c) => `<article><h3>${c[0]}</h3><p>${c[1]}</p></article>`).join('');
  }

  falsifyChart(); queueChart(); convergeChart(); linkTable(); caveats();
  window.addEventListener('resize', () => { falsifyChart(); queueChart(); convergeChart(); });
})();
