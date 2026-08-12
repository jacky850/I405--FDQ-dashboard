(() => {
  const payload = window.FULL_DAY_RESIDUAL;
  const summary = payload.summary;
  const rows = payload.series;
  const episode = payload.episodes[0];
  const byId = (id) => document.getElementById(id);
  const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const isoMinute = (iso) => {
    const match = String(iso).match(/T(\d\d):(\d\d)/);
    return Number(match[1]) * 60 + Number(match[2]);
  };
  const clock = (minute) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;

  const t0 = isoMinute(episode.t0_la);
  const t2 = isoMinute(episode.t2_la);
  const t3 = isoMinute(episode.t3_la);
  const handoff = 600;
  const qAtHandoff = summary.count_reference_queue_at_period_boundaries_veh['10:00'];
  const firstZeroAfterT3 = rows.find((row) => row.minute > t3 && row.queue_ref <= 0.5);
  const clearMinute = firstZeroAfterT3 ? firstZeroAfterT3.minute : t3 + 5;
  const windowStart = Math.max(0, t0 - 25);
  const windowEnd = Math.min(1440, clearMinute + 25);

  byId('metrics').innerHTML = [
    ['Queue formation', clock(t0), 'T0 from observed speed'],
    ['Maximum queue', `${number.format(summary.count_reference_maximum_queue_veh)} veh`, `at ${summary.count_reference_maximum_queue_time_la.slice(11, 16)}`, 'accent'],
    ['Queue at handoff', `${number.format(qAtHandoff)} veh`, '10:00 AM → MD', 'teal'],
    ['Queue dissipation', clock(clearMinute), `${episode.duration_min}-min speed episode`]
  ].map((item) => `<article><span>${item[0]}</span><strong class="${item[3] || ''}">${item[1]}</strong><small>${item[2]}</small></article>`).join('');

  byId('boundarySentence').textContent = `${number.format(qAtHandoff)} vehicles remain. Q(t) continues into MD instead of resetting to zero.`;

  const margin = { left: 62, right: 24, top: 42, bottom: 42 };

  function scales(element, low, high) {
    const width = element.clientWidth || 1000;
    const height = element.clientHeight || 360;
    const x = (minute) => margin.left + ((minute - windowStart) / (windowEnd - windowStart)) * (width - margin.left - margin.right);
    const y = (value) => height - margin.bottom - ((value - low) / (high - low || 1)) * (height - margin.top - margin.bottom);
    return { width, height, x, y };
  }

  function ticks(start, end, step) {
    const values = [];
    let current = Math.ceil(start / step) * step;
    while (current <= end) { values.push(current); current += step; }
    return values;
  }

  function periodBands(x, top, bottom) {
    const periods = [
      { start: 360, end: 600, className: 'am-band', label: 'AM · 06:00–10:00' },
      { start: 600, end: 900, className: 'md-band', label: 'MD · 10:00–15:00' }
    ];
    return periods.map((period) => {
      const start = Math.max(windowStart, period.start);
      const end = Math.min(windowEnd, period.end);
      if (end <= start) return '';
      return `<rect class="${period.className}" x="${x(start)}" y="${top}" width="${x(end) - x(start)}" height="${bottom - top}"/><text class="axis-label" x="${(x(start) + x(end)) / 2}" y="${top + 16}" text-anchor="middle">${period.label}</text>`;
    }).join('');
  }

  function pathFor(filteredRows, valueKey, x, y) {
    return filteredRows.map((row, index) => `${index ? 'L' : 'M'}${x(row.minute).toFixed(1)},${y(row[valueKey]).toFixed(1)}`).join(' ');
  }

  function attachTooltip(element, filteredRows, formatter) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `position:absolute;left:${margin.left}px;right:${margin.right}px;top:${margin.top}px;bottom:${margin.bottom}px;cursor:crosshair`;
    element.appendChild(overlay);
    overlay.addEventListener('mousemove', (event) => {
      const rect = overlay.getBoundingClientRect();
      const minute = windowStart + ((event.clientX - rect.left) / rect.width) * (windowEnd - windowStart);
      const row = filteredRows.reduce((best, candidate) => Math.abs(candidate.minute - minute) < Math.abs(best.minute - minute) ? candidate : best, filteredRows[0]);
      const tip = byId('tooltip');
      tip.innerHTML = formatter(row);
      tip.style.display = 'block';
      tip.style.left = `${event.clientX + 14}px`;
      tip.style.top = `${event.clientY + 14}px`;
    });
    overlay.addEventListener('mouseleave', () => { byId('tooltip').style.display = 'none'; });
  }

  function renderQueue() {
    const element = byId('queueChart');
    const visible = rows.filter((row) => row.minute >= windowStart && row.minute <= windowEnd);
    const maxQueue = Math.max(...visible.map((row) => row.queue_ref));
    const { width, height, x, y } = scales(element, 0, maxQueue * 1.18);
    const plotBottom = height - margin.bottom;
    const linePath = pathFor(visible, 'queue_ref', x, y);
    const areaPath = `${linePath} L${x(visible[visible.length - 1].minute)},${y(0)} L${x(visible[0].minute)},${y(0)} Z`;
    const handoffRow = visible.reduce((best, row) => Math.abs(row.minute - handoff) < Math.abs(best.minute - handoff) ? row : best, visible[0]);
    const yTicks = [0, Math.round(maxQueue / 2), Math.round(maxQueue)];
    let svg = `<svg viewBox="0 0 ${width} ${height}"><defs><linearGradient id="queueGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ec7541" stop-opacity=".34"/><stop offset="100%" stop-color="#ec7541" stop-opacity=".04"/></linearGradient></defs>`;
    svg += periodBands(x, margin.top, plotBottom);
    svg += yTicks.map((value) => `<line class="grid" x1="${margin.left}" x2="${width - margin.right}" y1="${y(value)}" y2="${y(value)}"/><text class="axis" x="${margin.left - 9}" y="${y(value) + 3}" text-anchor="end">${number.format(value)}</text>`).join('');
    svg += ticks(windowStart, windowEnd, 30).map((value) => `<text class="axis" x="${x(value)}" y="${height - 15}" text-anchor="middle">${clock(value)}</text>`).join('');
    svg += `<path class="queue-area" d="${areaPath}"/><path class="queue-line" d="${linePath}"/>`;
    svg += `<line class="boundary-line" x1="${x(handoff)}" x2="${x(handoff)}" y1="${margin.top}" y2="${plotBottom}"/><circle class="handoff-dot" cx="${x(handoff)}" cy="${y(handoffRow.queue_ref)}" r="6"/><text class="marker-label" x="${x(handoff) + 8}" y="${y(handoffRow.queue_ref) - 11}">${number.format(handoffRow.queue_ref)} veh carried into MD</text>`;
    svg += `<line class="marker-line" x1="${x(t0)}" x2="${x(t0)}" y1="${margin.top}" y2="${plotBottom}"/><text class="marker-label" x="${x(t0) + 6}" y="${plotBottom - 9}">T0</text>`;
    svg += `<line class="marker-line" x1="${x(clearMinute)}" x2="${x(clearMinute)}" y1="${margin.top}" y2="${plotBottom}"/><text class="marker-label" x="${x(clearMinute) - 6}" y="${plotBottom - 9}" text-anchor="end">queue cleared</text></svg>`;
    element.innerHTML = svg;
    attachTooltip(element, visible, (row) => `<b>${row.time} · ${row.period}</b><br>Residual queue: ${number.format(row.queue_ref)} vehicles`);
  }

  function renderSpeed() {
    const element = byId('speedChart');
    const visible = rows.filter((row) => row.minute >= windowStart && row.minute <= windowEnd);
    const values = visible.map((row) => row.speed);
    const low = Math.max(0, Math.min(...values) - 5);
    const high = Math.max(...values) + 8;
    const { width, height, x, y } = scales(element, low, high);
    const plotBottom = height - margin.bottom;
    const rowAt = (minute) => visible.reduce((best, row) => Math.abs(row.minute - minute) < Math.abs(best.minute - minute) ? row : best, visible[0]);
    const markers = [
      { minute: t0, label: 'T0', color: '#ec7541', row: rowAt(t0) },
      { minute: t2, label: 'T2', color: '#d6534c', row: rowAt(t2) },
      { minute: t3, label: 'T3', color: '#118b81', row: rowAt(t3) }
    ];
    const yTicks = [Math.round(low), Math.round((low + high) / 2), Math.round(high)];
    let svg = `<svg viewBox="0 0 ${width} ${height}">`;
    svg += periodBands(x, margin.top, plotBottom);
    svg += `<rect class="event-band" x="${x(t0)}" y="${margin.top}" width="${x(t3) - x(t0)}" height="${plotBottom - margin.top}"/>`;
    svg += yTicks.map((value) => `<line class="grid" x1="${margin.left}" x2="${width - margin.right}" y1="${y(value)}" y2="${y(value)}"/><text class="axis" x="${margin.left - 9}" y="${y(value) + 3}" text-anchor="end">${value}</text>`).join('');
    svg += ticks(windowStart, windowEnd, 30).map((value) => `<text class="axis" x="${x(value)}" y="${height - 15}" text-anchor="middle">${clock(value)}</text>`).join('');
    svg += `<line class="p-bracket" x1="${x(t0)}" x2="${x(t3)}" y1="${margin.top + 25}" y2="${margin.top + 25}"/><line class="p-bracket" x1="${x(t0)}" x2="${x(t0)}" y1="${margin.top + 19}" y2="${margin.top + 31}"/><line class="p-bracket" x1="${x(t3)}" x2="${x(t3)}" y1="${margin.top + 19}" y2="${margin.top + 31}"/><text class="p-label" x="${(x(t0) + x(t3)) / 2}" y="${margin.top + 18}" text-anchor="middle">P = ${episode.duration_min} min</text>`;
    svg += `<path class="speed-line" d="${pathFor(visible, 'speed', x, y)}"/>`;
    svg += markers.map((marker) => `<line class="marker-line" x1="${x(marker.minute)}" x2="${x(marker.minute)}" y1="${margin.top}" y2="${plotBottom}"/><circle class="marker-dot" cx="${x(marker.minute)}" cy="${y(marker.row.speed)}" r="5" fill="${marker.color}"/><text class="marker-label" x="${x(marker.minute)}" y="${y(marker.row.speed) - 12}" text-anchor="middle">${marker.label} · ${clock(marker.minute)}</text>`).join('');
    svg += `</svg>`;
    element.innerHTML = svg;
    attachTooltip(element, visible, (row) => `<b>${row.time} · ${row.period}</b><br>Observed speed: ${row.speed.toFixed(1)} mph`);
  }

  function render() { renderQueue(); renderSpeed(); }
  render();
  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(render, 120);
  });
})();
