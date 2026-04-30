/**
 * Factory functions para cada chart Chart.js.
 * Usa chartjs-plugin-annotation para faixas e linhas de referência — sem
 * datasets fantasma que poluem a legenda.
 */

import { classifyNdci, rgba, lagoaColor, seasonalMeans } from './utils.js';

const FONT  = "'Segoe UI', system-ui, sans-serif";
const TEXT  = '#e6edf3';
const MUTED = '#7d8590';
const GRID  = 'rgba(48,54,61,0.6)';

// ── Opções base ────────────────────────────────────────────────────────────────
function base(extraPlugins = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: {
        labels: {
          color: MUTED,
          font: { family: FONT, size: 11 },
          boxWidth: 12,
          padding: 16,
          usePointStyle: true,
          pointStyleWidth: 12,
        },
      },
      tooltip: {
        backgroundColor: '#1c2330',
        borderColor: '#30363d',
        borderWidth: 1,
        titleColor: TEXT,
        bodyColor: MUTED,
        padding: 10,
        cornerRadius: 6,
        boxPadding: 4,
      },
      ...extraPlugins,
    },
    scales: {
      x: {
        ticks: { color: MUTED, font: { family: FONT, size: 10 }, maxRotation: 45 },
        grid:  { color: GRID },
        border: { color: GRID },
      },
      y: {
        ticks: { color: MUTED, font: { family: FONT, size: 10 } },
        grid:  { color: GRID },
        border: { color: GRID },
      },
    },
  };
}

// ── Anotações de faixas de alerta ──────────────────────────────────────────────
function alertAnnotations(yMin, yMax) {
  const clip = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  return {
    bom_box: {
      type: 'box',
      yMin: clip(-1,   yMin, yMax),
      yMax: clip(0.02, yMin, yMax),
      backgroundColor: 'rgba(63,185,80,0.09)',
      borderWidth: 0,
    },
    mod_box: {
      type: 'box',
      yMin: clip(0.02, yMin, yMax),
      yMax: clip(0.10, yMin, yMax),
      backgroundColor: 'rgba(210,153,34,0.10)',
      borderWidth: 0,
    },
    ele_box: {
      type: 'box',
      yMin: clip(0.10, yMin, yMax),
      yMax: clip(0.20, yMin, yMax),
      backgroundColor: 'rgba(248,81,73,0.12)',
      borderWidth: 0,
    },
    cri_box: {
      type: 'box',
      yMin: clip(0.20, yMin, yMax),
      yMax: clip(1,    yMin, yMax),
      backgroundColor: 'rgba(185,28,28,0.14)',
      borderWidth: 0,
    },
    bloom_line: {
      type: 'line', yMin: 0, yMax: 0,
      borderColor: 'rgba(163,113,247,0.70)',
      borderWidth: 1.5, borderDash: [6, 3],
      label: {
        display: true, content: 'Eflorescência (~14 µg/L)',
        position: 'start', color: 'rgba(163,113,247,0.90)',
        font: { size: 9, family: FONT },
        backgroundColor: 'rgba(13,17,23,0.80)',
        padding: { x: 6, y: 3 },
        borderRadius: 3,
      },
    },
    line_mod: {
      type: 'line', yMin: 0.02, yMax: 0.02,
      borderColor: 'rgba(210,153,34,0.45)',
      borderWidth: 1, borderDash: [4, 4],
      label: {
        display: true, content: '0.02', position: 'end',
        color: 'rgba(210,153,34,0.65)',
        font: { size: 9, family: FONT },
        backgroundColor: 'transparent', padding: 0,
      },
    },
    line_ele: {
      type: 'line', yMin: 0.10, yMax: 0.10,
      borderColor: 'rgba(248,81,73,0.45)',
      borderWidth: 1, borderDash: [4, 4],
      label: {
        display: true, content: '0.10', position: 'end',
        color: 'rgba(248,81,73,0.65)',
        font: { size: 9, family: FONT },
        backgroundColor: 'transparent', padding: 0,
      },
    },
    line_cri: {
      type: 'line', yMin: 0.20, yMax: 0.20,
      borderColor: 'rgba(185,28,28,0.45)',
      borderWidth: 1, borderDash: [4, 4],
      label: {
        display: true, content: '0.20', position: 'end',
        color: 'rgba(185,28,28,0.65)',
        font: { size: 9, family: FONT },
        backgroundColor: 'transparent', padding: 0,
      },
    },
  };
}

// ── Formata label do eixo X ────────────────────────────────────────────────────
function fmtXLabel(label) {
  if (!label) return '';
  const MONTHS = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  if (label.length === 7) {
    // Mensal: "2023-05" → "Mai 23" / "Jan 23"
    const [y, m] = label.split('-');
    return `${MONTHS[parseInt(m, 10) - 1]} '${y.slice(2)}`;
  }
  if (label.length === 10) {
    // Por imagem: "2023-05-15" → "15 Mai"
    const [, m, d] = label.split('-');
    return `${parseInt(d, 10)} ${MONTHS[parseInt(m, 10) - 1]}`;
  }
  return label;
}

function fmtDateBR(label) {
  if (!label || label.length !== 10) return label ?? '';
  const [y, m, d] = label.split('-');
  return `${d}/${m}/${y}`;
}

// ── Ticks sub-amostrados para eixo X legível ───────────────────────────────────
function sparseXTicks(labels, maxVisible = 18) {
  const step = Math.max(1, Math.ceil(labels.length / maxVisible));
  return (_, i) => (i % step === 0 ? labels[i] : '');
}

// ── Calcula range Y com padding a partir dos dados ────────────────────────────
function computeYRange(values, paddingFactor = 0.15) {
  const vals = values.filter(v => v != null);
  if (!vals.length) return { yMin: -0.05, yMax: 0.30 };
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 0.1;
  const pad  = span * paddingFactor;
  return {
    yMin: Math.floor((lo - pad) * 100) / 100,
    yMax: Math.ceil( (hi + pad) * 100) / 100,
  };
}

/* ── 1. Série temporal NDCI ────────────────────────────────────────────────── */

/**
 * buildSeriesChart — plota série NDCI com banda P10-P90 opcional.
 *
 * Aceita dois formatos de data:
 *   - Série mensal (legado): data.periodos = ["2023-01", ...], data.ndci_mean = [...]
 *   - Série por imagem:      data.datas = ["2023-01-15", ...], data.ndci_mean = [...]
 *
 * Quando ndci_p10 e ndci_p90 estão presentes, exibe banda sombreada de
 * variabilidade intra-mensal / por imagem (Pi & Guasselli SBSR 2025).
 */
export function buildSeriesChart(canvasId, lagoa, data, onPointClick = null) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const labels   = data.datas ?? data.periodos ?? [];
  const meanVals = data.ndci_mean ?? [];
  const p90Vals  = data.ndci_p90  ?? [];
  const p10Vals  = data.ndci_p10  ?? [];
  const nPixVals = data.n_pixels  ?? [];

  const hasBand      = p90Vals.some(v => v != null) && p10Vals.some(v => v != null);
  const isImageSeries = Boolean(data.datas);
  // ordem dos datasets quando hasBand: [P90=0, P10=1, mean=2]
  const meanDatasetIdx = hasBand ? 2 : 0;

  const allVals = [...meanVals, ...(hasBand ? [...p90Vals, ...p10Vals] : [])];
  const { yMin, yMax } = computeYRange(allVals);

  // ── Tooltip HTML externo ─────────────────────────────────────────────────────
  const externalTooltip = ({ chart, tooltip }) => {
    const wrap = chart.canvas.parentNode;
    let el = wrap.querySelector('.s-tip');
    if (!el) {
      el = document.createElement('div');
      el.className = 's-tip';
      wrap.appendChild(el);
    }
    if (!tooltip.opacity) { el.style.opacity = '0'; return; }

    const dp = tooltip.dataPoints?.find(p => p.dataset.label === 'NDCI médio');
    if (!dp) { el.style.opacity = '0'; return; }

    const idx    = dp.dataIndex;
    const v      = dp.parsed.y;
    if (v == null) { el.style.opacity = '0'; return; }

    const cls    = classifyNdci(v);
    const period = fmtXLabel(labels[idx] ?? '');
    const p90    = p90Vals[idx];
    const p10    = p10Vals[idx];
    const npx    = nPixVals[idx];

    el.innerHTML = `
      <div class="s-tip-head">
        <span class="s-tip-period">${labels[idx] ?? ''}</span>
        <span class="s-tip-dot" style="background:${cls.color}"></span>
      </div>
      <div class="s-tip-ndci" style="color:${cls.color}">${v.toFixed(4)}</div>
      <span class="s-tip-badge" style="color:${cls.color};border-color:${rgba(cls.color,0.35)};background:${rgba(cls.color,0.12)}">${cls.label}</span>
      ${p90  != null ? `<div class="s-tip-row"><span>P90</span><span>${p90.toFixed(4)}</span></div>` : ''}
      ${p10  != null ? `<div class="s-tip-row"><span>P10</span><span>${p10.toFixed(4)}</span></div>` : ''}
      ${npx  != null ? `<div class="s-tip-row"><span>Pixels</span><span>${npx.toLocaleString('pt-BR')}</span></div>` : ''}
    `;
    el.style.opacity = '1';

    const cw   = chart.canvas.offsetWidth;
    const tipW = 160;
    const x    = tooltip.caretX;
    const y    = tooltip.caretY;
    el.style.left = `${x + 14 + tipW > cw ? x - tipW - 10 : x + 14}px`;
    el.style.top  = `${Math.max(6, y - 28)}px`;
  };

  const options = base({
    annotation: { annotations: alertAnnotations(yMin, yMax) },
    legend: hasBand
      ? {
          display: true,
          labels: {
            color: MUTED,
            font: { family: FONT, size: 11 },
            boxWidth: 12,
            padding: 14,
            usePointStyle: true,
            pointStyleWidth: 10,
          },
        }
      : { display: false },
    tooltip: { enabled: false, external: externalTooltip, mode: 'index', intersect: false },
  });

  options.interaction       = { mode: 'index', intersect: false };
  options.scales.x.grid.color  = 'rgba(48,54,61,0.4)';
  options.scales.y.grid.color  = 'rgba(48,54,61,0.4)';
  options.scales.x.ticks.callback = (_, i) => {
    const step = Math.max(1, Math.ceil(labels.length / 18));
    return i % step === 0 ? fmtXLabel(labels[i]) : '';
  };
  options.scales.y.min   = yMin;
  options.scales.y.max   = yMax;
  options.scales.y.title = {
    display: true,
    text: isImageSeries ? 'NDCI (por imagem)' : 'NDCI',
    color: MUTED, font: { size: 10, family: FONT },
  };

  if (onPointClick) {
    options.onClick = (event, elements) => {
      if (!elements.length) return;
      const el = elements.find(e => e.datasetIndex === meanDatasetIdx) ?? elements[0];
      if (!el) return;
      onPointClick(el.index, data);
    };
    options.onHover = (event, elements) => {
      ctx.style.cursor = elements.some(e => e.datasetIndex === meanDatasetIdx)
        ? 'pointer' : 'default';
    };
  }

  const datasets = [];

  const ptRadius   = labels.length > 80 ? 1 : labels.length > 40 ? 2 : 3;
  const P90_COLOR  = 'rgba(248,81,73,0.85)';    // vermelho — limite superior
  const P10_COLOR  = 'rgba(63,185,80,0.85)';    // verde — limite inferior
  const BAND_FILL  = 'rgba(248,81,73,0.06)';

  // Ordem quando hasBand: [P90, P10, mean]
  // P90 com fill:'+1' preenche exatamente até P10 (próximo dataset)
  if (hasBand) {
    datasets.push({
      label: 'P90',
      data: p90Vals,
      borderColor: P90_COLOR,
      backgroundColor: BAND_FILL,
      fill: '+1',
      tension: 0.4,
      pointRadius: ptRadius,
      pointHoverRadius: 5,
      pointStyle: 'circle',
      pointBackgroundColor: P90_COLOR,
      pointBorderColor: 'transparent',
      borderWidth: 1.5,
      borderDash: [5, 4],
      spanGaps: false,
    });

    datasets.push({
      label: 'P10',
      data: p10Vals,
      borderColor: P10_COLOR,
      backgroundColor: 'transparent',
      fill: false,
      tension: 0.4,
      pointRadius: ptRadius,
      pointHoverRadius: 5,
      pointStyle: 'circle',
      pointBackgroundColor: P10_COLOR,
      pointBorderColor: 'transparent',
      borderWidth: 1.5,
      borderDash: [5, 4],
      spanGaps: false,
    });
  }

  // Linha principal — sempre por último para ficar acima da banda
  datasets.push({
    label: 'NDCI médio',
    data: meanVals,
    borderColor: '#2188ff',
    backgroundColor: hasBand ? 'transparent' : rgba('#2188ff', 0.07),
    fill: !hasBand,
    tension: 0.4,
    pointRadius: labels.length > 80 ? 2 : labels.length > 40 ? 3 : 5,
    pointHoverRadius: 7,
    pointBackgroundColor: meanVals.map(v => classifyNdci(v).color),
    pointBorderColor: 'transparent',
    pointHoverBorderColor: '#ffffff',
    pointHoverBorderWidth: 2,
    pointHoverBackgroundColor: meanVals.map(v => classifyNdci(v).color),
    borderWidth: 2.5,
    spanGaps: false,
  });

  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options,
  });
}

/* ── 2. Índices complementares ─────────────────────────────────────────────── */
export function buildIndicesChart(canvasId, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const { periodos, turbidez, ndwi_mean } = data;
  const options = base();
  options.scales.x.ticks.callback = sparseXTicks(periodos);
  options.scales.y.title = { display: true, text: 'Índice', color: MUTED, font: { size: 10, family: FONT } };

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: periodos,
      datasets: [
        {
          label: 'Turbidez (NDTI)',
          data: turbidez,
          borderColor: '#d29922',
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2,
        },
        {
          label: 'NDWI',
          data: ndwi_mean,
          borderColor: '#79c0ff',
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2,
        },
      ],
    },
    options,
  });
}

/* ── 3. Comparação multi-lagoa ─────────────────────────────────────────────── */
export function buildCompareChart(canvasId, allData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const allPeriods = [...new Set(
    Object.values(allData).flatMap(d => d.periodos)
  )].sort();

  const datasets = Object.entries(allData).map(([lagoa, d], i) => {
    const map = {};
    d.periodos.forEach((p, j) => { map[p] = d.ndci_mean[j]; });
    const color = lagoaColor(lagoa, i);
    return {
      label: lagoa.replace('Lagoa ', ''),
      data: allPeriods.map(p => map[p] ?? null),
      borderColor: color,
      backgroundColor: 'transparent',
      fill: false,
      tension: 0.35,
      pointRadius: 0,
      pointHoverRadius: 4,
      borderWidth: 2,
      spanGaps: false,
    };
  });

  const options = base();
  options.scales.x.ticks.callback = sparseXTicks(allPeriods);
  options.scales.y.title = { display: true, text: 'NDCI', color: MUTED, font: { size: 10, family: FONT } };

  return new Chart(ctx, {
    type: 'line',
    data: { labels: allPeriods, datasets },
    options,
  });
}

/* ── 4. Sazonalidade ───────────────────────────────────────────────────────── */
export function buildSeasonalChart(canvasId, allData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const MONTHS = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];

  const datasets = Object.entries(allData).map(([lagoa, d], i) => {
    const color = lagoaColor(lagoa, i);
    return {
      label: lagoa.replace('Lagoa ', ''),
      data: seasonalMeans(d.periodos, d.ndci_mean),
      backgroundColor: rgba(color, 0.65),
      borderColor: color,
      borderWidth: 1,
      borderRadius: 3,
    };
  });

  const options = base();
  options.scales.y.title = { display: true, text: 'NDCI médio', color: MUTED, font: { size: 10, family: FONT } };

  return new Chart(ctx, {
    type: 'bar',
    data: { labels: MONTHS, datasets },
    options,
  });
}

/* ── 5. Distribuição por faixa de alerta ───────────────────────────────────── */
export function buildDistributionChart(canvasId, allData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const labels = ['Bom\n(<0.02)', 'Moderado\n(0.02–0.10)', 'Elevado\n(0.10–0.20)', 'Crítico\n(>0.20)'];

  const datasets = Object.entries(allData).map(([lagoa, d], i) => {
    const vals = d.ndci_mean.filter(v => v != null);
    const color = lagoaColor(lagoa, i);
    return {
      label: lagoa.replace('Lagoa ', ''),
      data: [
        vals.filter(v => v < 0.02).length,
        vals.filter(v => v >= 0.02 && v < 0.10).length,
        vals.filter(v => v >= 0.10 && v < 0.20).length,
        vals.filter(v => v >= 0.20).length,
      ],
      backgroundColor: rgba(color, 0.65),
      borderColor: color,
      borderWidth: 1,
      borderRadius: 3,
    };
  });

  const options = base();
  options.scales.y.title = { display: true, text: 'Nº de meses', color: MUTED, font: { size: 10, family: FONT } };

  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options,
  });
}

/* ── 6. Scatter NDCI × Turbidez ────────────────────────────────────────────── */
export function buildScatterChart(canvasId, allData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const datasets = Object.entries(allData).map(([lagoa, d], i) => ({
    label: lagoa.replace('Lagoa ', ''),
    data: d.periodos.map((_, j) => {
      const x = d.ndci_mean[j];
      const y = d.turbidez[j];
      return (x != null && y != null) ? { x, y } : null;
    }).filter(Boolean),
    backgroundColor: rgba(lagoaColor(lagoa, i), 0.5),
    pointRadius: 4,
    pointHoverRadius: 6,
    pointHoverBorderColor: '#fff',
    pointHoverBorderWidth: 1,
  }));

  const options = base();
  options.scales.x.title = { display: true, text: 'NDCI', color: MUTED, font: { size: 10, family: FONT } };
  options.scales.y.title = { display: true, text: 'NDTI (Turbidez)', color: MUTED, font: { size: 10, family: FONT } };
  options.plugins.tooltip = {
    ...options.plugins.tooltip,
    callbacks: {
      label: ctx => {
        const { x, y } = ctx.parsed;
        const cls = classifyNdci(x);
        return ` ${ctx.dataset.label}  NDCI: ${x.toFixed(4)} [${cls.label}]  NDTI: ${y.toFixed(4)}`;
      },
    },
  };

  return new Chart(ctx, {
    type: 'scatter',
    data: { datasets },
    options,
  });
}

/* ── 7. NDCI por zona espacial ────────────────────────────────────────────── */

const ZONE_STYLES = {
  margem: { color: 'rgba(247,147,26,0.90)',  fill: 'rgba(247,147,26,0.08)' },
  medio:  { color: 'rgba(88,166,255,0.90)',  fill: 'rgba(88,166,255,0.08)' },
  nucleo: { color: 'rgba(63,185,80,0.90)',   fill: 'rgba(63,185,80,0.08)'  },
};

const ZONE_LABELS = { margem: 'Margem', medio: 'Médio', nucleo: 'Núcleo' };

/**
 * buildZoneChart — plota NDCI médio por zona espacial (margem / médio / núcleo).
 *
 * @param {string} canvasId
 * @param {string} lagoa
 * @param {object} zonesData  resposta de /api/water-quality/{lagoa}/zones
 */
export function buildZoneChart(canvasId, lagoa, zonesData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const zonas = zonesData.zonas ?? {};
  if (Object.keys(zonas).length === 0) return null;

  const allPeriods = [...new Set(
    Object.values(zonas).flatMap(z => z.periodos ?? [])
  )].sort();

  const allVals = Object.values(zonas).flatMap(z => z.ndci_mean ?? []);
  const { yMin, yMax } = computeYRange(allVals);

  const datasets = Object.entries(zonas).map(([nome, d]) => {
    const style = ZONE_STYLES[nome] ?? { color: '#ccc', fill: 'transparent' };
    const map = {};
    (d.periodos ?? []).forEach((p, i) => { map[p] = (d.ndci_mean ?? [])[i]; });
    return {
      label: ZONE_LABELS[nome] ?? nome,
      data: allPeriods.map(p => map[p] ?? null),
      borderColor: style.color,
      backgroundColor: style.fill,
      fill: true,
      tension: 0.35,
      pointRadius: 0,
      pointHoverRadius: 5,
      borderWidth: 2,
      spanGaps: false,
    };
  });

  const annotations = alertAnnotations(yMin, yMax);
  const options = base({ annotation: { annotations } });
  options.scales.x.ticks.callback = sparseXTicks(allPeriods, 18);
  options.scales.y.min = yMin;
  options.scales.y.max = yMax;
  options.scales.y.title = {
    display: true, text: 'NDCI', color: MUTED, font: { size: 10, family: FONT },
  };
  options.plugins.tooltip = {
    ...options.plugins.tooltip,
    callbacks: {
      title: ([{ label }]) => fmtXLabel(label),
      label: ({ dataset, raw }) =>
        raw != null ? `${dataset.label}: ${raw.toFixed(4)}` : null,
    },
  };

  return new Chart(ctx, {
    type: 'line',
    data: { labels: allPeriods, datasets },
    options,
  });
}

/* ── 8. Foco em zona única — NDCI (eixo esq.) + NDTI (eixo dir.) ──────────── */

/**
 * buildZoneFocusChart — dual-eixo para uma zona selecionada.
 *
 * Aceita dados mensais (periodos + turbidez) ou por imagem (datas + ndti_mean).
 *
 * @param {string} canvasId
 * @param {object} zoneData   objeto com periodos|datas, ndci_mean, ndci_p90, turbidez|ndti_mean
 */
export function buildZoneFocusChart(canvasId, zoneData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const periodos = zoneData.datas    ?? zoneData.periodos  ?? [];
  const isImageSeries = Boolean(zoneData.datas);
  const ndciMean = zoneData.ndci_mean ?? [];
  const ndciP90  = zoneData.ndci_p90  ?? [];
  const turbidez = zoneData.turbidez  ?? zoneData.ndti_mean ?? [];

  const hasP90 = ndciP90.some(v => v != null);
  const allNdci = [...ndciMean, ...(hasP90 ? ndciP90 : [])];
  const { yMin, yMax } = computeYRange(allNdci);

  const datasets = [];

  if (hasP90) {
    datasets.push({
      label: 'NDCI P90',
      data: ndciP90,
      borderColor: 'rgba(248,81,73,0.70)',
      backgroundColor: 'transparent',
      fill: false,
      tension: 0.4,
      pointRadius: 0,
      pointHoverRadius: 4,
      borderWidth: 1.5,
      borderDash: [5, 4],
      yAxisID: 'y',
      spanGaps: false,
    });
  }

  datasets.push({
    label: 'NDCI médio',
    data: ndciMean,
    borderColor: '#2188ff',
    backgroundColor: 'rgba(33,136,255,0.07)',
    fill: !hasP90,
    tension: 0.4,
    pointRadius: periodos.length > 60 ? 1 : 3,
    pointHoverRadius: 6,
    pointBackgroundColor: ndciMean.map(v => classifyNdci(v).color),
    pointBorderColor: 'transparent',
    pointHoverBorderColor: '#ffffff',
    pointHoverBorderWidth: 2,
    borderWidth: 2.5,
    yAxisID: 'y',
    spanGaps: false,
  });

  datasets.push({
    label: 'NDTI (Turbidez)',
    data: turbidez,
    borderColor: 'rgba(210,153,34,0.85)',
    backgroundColor: 'transparent',
    fill: false,
    tension: 0.35,
    pointRadius: 0,
    pointHoverRadius: 4,
    borderWidth: 2,
    borderDash: [4, 3],
    yAxisID: 'y2',
    spanGaps: false,
  });

  const options = base({
    annotation: { annotations: alertAnnotations(yMin, yMax) },
    tooltip: {
      backgroundColor: '#1c2330',
      borderColor: '#30363d',
      borderWidth: 1,
      titleColor: TEXT,
      bodyColor: MUTED,
      padding: 10,
      cornerRadius: 6,
      callbacks: {
        title: ([{ label }]) => (isImageSeries ? fmtDateBR(label) : fmtXLabel(label)),
        label: ({ dataset, raw }) =>
          raw != null ? `${dataset.label}: ${raw.toFixed(4)}` : null,
      },
    },
  });

  options.interaction = { mode: 'index', intersect: false };
  const _step = Math.max(1, Math.ceil(periodos.length / 18));
  options.scales.x.ticks.callback = (_, i) => {
    if (i % _step !== 0) return '';
    const label = periodos[i] ?? '';
    return isImageSeries ? fmtDateBR(label) : fmtXLabel(label);
  };

  options.scales.y = {
    position: 'left',
    min: yMin,
    max: yMax,
    ticks: { color: MUTED, font: { family: FONT, size: 10 } },
    grid:  { color: GRID },
    border: { color: GRID },
    title: { display: true, text: 'NDCI', color: MUTED, font: { size: 10, family: FONT } },
  };
  options.scales.y2 = {
    position: 'right',
    ticks: { color: 'rgba(210,153,34,0.80)', font: { family: FONT, size: 10 } },
    grid:  { drawOnChartArea: false, color: GRID },
    border: { color: GRID },
    title: {
      display: true,
      text: 'NDTI',
      color: 'rgba(210,153,34,0.80)',
      font: { size: 10, family: FONT },
    },
  };

  return new Chart(ctx, {
    type: 'line',
    data: { labels: periodos, datasets },
    options,
  });
}

// ── NDVI — anel de vegetação terrestre ────────────────────────────────────────
const GREEN      = 'rgba(63, 185, 80, 1)';
const GREEN_SOFT = 'rgba(63, 185, 80, 0.18)';

export function buildNdviChart(canvasId, lagoa, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  const labels = data.periodos ?? data.datas ?? [];
  const mean   = data.ndvi_mean ?? [];
  const p90    = data.ndvi_p90  ?? [];
  const p10    = data.ndvi_p10  ?? [];
  const nPixVals = data.n_pixels ?? [];

  const hasBand = p90.some(v => v != null) && p10.some(v => v != null);
  // índice do dataset principal (mean) depende de hasBand
  const meanIdx = hasBand ? 2 : 0;

  const MONTHS_PT = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const fmtPeriod = (label) => {
    if (!label) return '';
    if (label.length === 7) {          // "2023-05" → "Mai 2023"
      const [y, m] = label.split('-');
      return `${MONTHS_PT[parseInt(m, 10) - 1]} ${y}`;
    }
    if (label.length === 10) {         // "2023-05-15" → "15 Mai 2023"
      const [y, m, d] = label.split('-');
      return `${parseInt(d, 10)} ${MONTHS_PT[parseInt(m, 10) - 1]} ${y}`;
    }
    return label;
  };

  // ── Tooltip externo (mesmo padrão de buildSeriesChart) ─────────────────────
  const externalTooltip = ({ chart, tooltip }) => {
    const wrap = chart.canvas.parentNode;
    let el = wrap.querySelector('.s-tip');
    if (!el) {
      el = document.createElement('div');
      el.className = 's-tip';
      wrap.appendChild(el);
    }
    if (!tooltip.opacity) { el.style.opacity = '0'; return; }

    const dp = tooltip.dataPoints?.find(p => p.datasetIndex === meanIdx);
    if (!dp) { el.style.opacity = '0'; return; }

    const idx = dp.dataIndex;
    const v   = dp.parsed.y;
    if (v == null) { el.style.opacity = '0'; return; }

    const period = fmtPeriod(labels[idx] ?? '');
    const vp90   = p90[idx];
    const vp10   = p10[idx];
    const npx    = nPixVals[idx];
    const color  = v >= 0.5 ? '#3fb950' : v >= 0.2 ? '#d29922' : '#f85149';

    el.innerHTML = `
      <div class="s-tip-head">
        <span class="s-tip-period">${period}</span>
        <span class="s-tip-dot" style="background:${color}"></span>
      </div>
      <div class="s-tip-ndci" style="color:${color}">${v.toFixed(4)}</div>
      ${vp90 != null ? `<div class="s-tip-row"><span>P90</span><span>${vp90.toFixed(4)}</span></div>` : ''}
      ${vp10 != null ? `<div class="s-tip-row"><span>P10</span><span>${vp10.toFixed(4)}</span></div>` : ''}
      ${npx  != null ? `<div class="s-tip-row"><span>Pixels</span><span>${npx.toLocaleString('pt-BR')}</span></div>` : ''}
    `;
    el.style.opacity = '1';

    const cw   = chart.canvas.offsetWidth;
    const tipW = 160;
    const x    = tooltip.caretX;
    const y    = tooltip.caretY;
    el.style.left = `${x + 14 + tipW > cw ? x - tipW - 10 : x + 14}px`;
    el.style.top  = `${Math.max(6, y - 28)}px`;
  };

  const options = base({
    annotation: {
      annotations: {
        healthy_line: {
          type: 'line', yMin: 0.5, yMax: 0.5,
          borderColor: 'rgba(63,185,80,0.50)',
          borderWidth: 1.5, borderDash: [6, 3],
          label: {
            display: true, content: 'Vegetação densa (NDVI ≥ 0.5)',
            position: 'start', color: 'rgba(63,185,80,0.80)',
            font: { size: 9, family: FONT },
            backgroundColor: 'rgba(13,17,23,0.80)',
            padding: { x: 6, y: 3 }, borderRadius: 3,
          },
        },
        sparse_line: {
          type: 'line', yMin: 0.2, yMax: 0.2,
          borderColor: 'rgba(210,153,34,0.45)',
          borderWidth: 1, borderDash: [4, 4],
          label: {
            display: true, content: 'Vegetação esparsa (0.2)',
            position: 'end', color: 'rgba(210,153,34,0.65)',
            font: { size: 9, family: FONT },
            backgroundColor: 'transparent', padding: 0,
          },
        },
      },
    },
    tooltip: { enabled: false, external: externalTooltip, mode: 'index', intersect: false },
  });

  options.scales.y.min = 0;
  options.scales.y.max = 1;
  options.scales.y.title = {
    display: true, text: 'NDVI', color: MUTED, font: { size: 10, family: FONT },
  };
  options.scales.x.ticks.callback = sparseXTicks(labels, 18);

  const datasets = [];

  if (hasBand) {
    datasets.push({
      label: 'P10–P90',
      data:  p90,
      fill: '+1',
      backgroundColor: GREEN_SOFT,
      borderColor: 'transparent',
      pointRadius: 0,
      tension: 0.35,
    });
    datasets.push({
      label: 'P10',
      data:  p10,
      fill: false,
      borderColor: 'rgba(63,185,80,0.25)',
      borderWidth: 1,
      borderDash: [3, 3],
      pointRadius: 0,
      tension: 0.35,
    });
  }

  datasets.push({
    label: 'NDVI médio',
    data: mean,
    borderColor: GREEN,
    borderWidth: 2,
    pointRadius: 3,
    pointHoverRadius: 6,
    pointBackgroundColor: GREEN,
    tension: 0.35,
    fill: false,
  });

  return new Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options,
  });
}
