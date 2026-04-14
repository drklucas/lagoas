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
      backgroundColor: 'rgba(63,185,80,0.07)',
      borderWidth: 0,
    },
    mod_box: {
      type: 'box',
      yMin: clip(0.02, yMin, yMax),
      yMax: clip(0.10, yMin, yMax),
      backgroundColor: 'rgba(210,153,34,0.08)',
      borderWidth: 0,
    },
    ele_box: {
      type: 'box',
      yMin: clip(0.10, yMin, yMax),
      yMax: clip(0.20, yMin, yMax),
      backgroundColor: 'rgba(248,81,73,0.09)',
      borderWidth: 0,
    },
    cri_box: {
      type: 'box',
      yMin: clip(0.20, yMin, yMax),
      yMax: clip(1,    yMin, yMax),
      backgroundColor: 'rgba(185,28,28,0.11)',
      borderWidth: 0,
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
export function buildSeriesChart(canvasId, lagoa, data, onPointClick = null) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const { periodos, ndci_mean } = data;
  const { yMin, yMax } = computeYRange(ndci_mean);

  const options = base({
    annotation: { annotations: alertAnnotations(yMin, yMax) },
    legend: { display: false },
    tooltip: {
      backgroundColor: '#1c2330',
      borderColor: '#30363d',
      borderWidth: 1,
      titleColor: TEXT,
      bodyColor: MUTED,
      padding: 10,
      cornerRadius: 6,
      boxPadding: 4,
      callbacks: {
        label: ctx => {
          const v = ctx.parsed.y;
          if (v == null) return null;
          const cls = classifyNdci(v);
          return ` NDCI: ${v.toFixed(4)}  [${cls.label}]`;
        },
      },
    },
  });

  options.scales.x.ticks.callback = sparseXTicks(periodos);
  options.scales.y.min = yMin;
  options.scales.y.max = yMax;
  options.scales.y.title = { display: true, text: 'NDCI', color: MUTED, font: { size: 10, family: FONT } };

  if (onPointClick) {
    options.onClick = (event, elements) => {
      if (!elements.length) return;
      const idx = elements[0].index;
      onPointClick(idx, data);
    };
    options.onHover = (event, elements) => {
      ctx.style.cursor = elements.length ? 'pointer' : 'default';
    };
  }

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: periodos,
      datasets: [{
        label: 'NDCI médio',
        data: ndci_mean,
        borderColor: '#2188ff',
        backgroundColor: rgba('#2188ff', 0.07),
        fill: true,
        tension: 0.35,
        pointRadius: periodos.length > 60 ? 2 : 4,
        pointHoverRadius: 6,
        pointBackgroundColor: ndci_mean.map(v => classifyNdci(v).color),
        pointBorderColor: 'transparent',
        pointHoverBorderColor: '#fff',
        pointHoverBorderWidth: 2,
        borderWidth: 2,
        spanGaps: false,
      }],
    },
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
