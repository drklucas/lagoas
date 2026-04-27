/**
 * Orquestração principal — inicializa tudo e gerencia interações.
 */

import { getWaterQuality, getImageSeries, getCurrentStatus, getWorkerStatus } from './api.js';
import { classifyNdci, fmtNdci, fmtNum } from './utils.js';
import {
  buildSeriesChart,
  buildIndicesChart,
  buildSeasonalChart,
  buildDistributionChart,
  buildScatterChart,
  buildCompareChart,
} from './charts.js';
import { DataTable } from './table.js';
import { initChartActions } from './chart-actions.js';
import { initMap } from './map.js';
import { initAnalytics, loadAnalytics } from './analytics.js';
import { exportHTML } from './export-html.js';

let charts      = {};
const table     = new DataTable();

let allData      = {};
let imageData    = {};   // cache: lagoa → dados por imagem
let lagoas       = [];
let activeLagoa  = null;
let viewMode     = 'mensal';   // 'mensal' | 'imagem'

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initTabs();
  initViewToggle();
  await Promise.all([loadStatusBar(), loadData()]);
  setInterval(loadStatusBar, 30_000);
}

// ── Toggle mensal / por imagem ────────────────────────────────────────────────
function initViewToggle() {
  const toggle = document.getElementById('view-toggle');
  if (!toggle) return;
  toggle.addEventListener('change', async () => {
    viewMode = toggle.checked ? 'imagem' : 'mensal';
    await renderSeriesChart();
  });
}

// ── Filtro de data para a série temporal ──────────────────────────────────────
function getDateFilter() {
  const from = document.getElementById('series-date-from')?.value ?? '';
  const to   = document.getElementById('series-date-to')?.value   ?? '';
  return { from, to };
}

function filterDataByDateRange(data, from, to) {
  if (!from && !to) return data;
  const labels = data.datas ?? data.periodos ?? [];

  // Normaliza qualquer label para YYYY-MM para comparar com os inputs month
  const norm = d => (d && d.length > 7 ? d.slice(0, 7) : d);

  const indices = [];
  labels.forEach((label, i) => {
    const n = norm(label);
    if (from && n < from) return;
    if (to   && n > to)   return;
    indices.push(i);
  });

  const pick = arr => (arr?.length ? indices.map(i => arr[i]) : arr ?? []);

  return {
    ...data,
    datas:     data.datas     ? pick(data.datas)     : undefined,
    periodos:  data.periodos  ? pick(data.periodos)  : undefined,
    ndci_mean: pick(data.ndci_mean),
    ndci_p90:  pick(data.ndci_p90),
    ndci_p10:  pick(data.ndci_p10),
    turbidez:  pick(data.turbidez),
    ndwi_mean: pick(data.ndwi_mean),
    n_pixels:  pick(data.n_pixels),
  };
}

async function renderSeriesChart() {
  destroyChart('series');
  hidePointDetail();

  const { from, to } = getDateFilter();

  if (viewMode === 'imagem') {
    if (!imageData[activeLagoa]) {
      try {
        imageData[activeLagoa] = await getImageSeries(activeLagoa);
      } catch {
        // fallback para mensal se não houver dados por imagem
        imageData[activeLagoa] = null;
      }
    }
    const raw = imageData[activeLagoa];
    if (raw && raw.datas?.length) {
      const d = filterDataByDateRange(raw, from, to);
      charts.series = buildSeriesChart('chart-series', activeLagoa, d, onSeriesPointClick);
      return;
    }
  }

  // fallback: mensal
  const raw = allData[activeLagoa];
  if (raw) {
    const d = filterDataByDateRange(raw, from, to);
    charts.series = buildSeriesChart('chart-series', activeLagoa, d, onSeriesPointClick);
  }
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tab = btn.dataset.tab;

      document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b === btn)
      );
      document.getElementById('tab-dashboard').style.display =
        tab === 'dashboard' ? 'flex' : 'none';
      document.getElementById('tab-table').style.display =
        tab === 'table' ? 'flex' : 'none';
      document.getElementById('tab-map').style.display =
        tab === 'map' ? 'flex' : 'none';
      document.getElementById('tab-analytics').style.display =
        tab === 'analytics' ? 'flex' : 'none';

      if (tab === 'map') {
        await initMap();
      }
      if (tab === 'analytics') {
        await loadAnalytics();
      }
    });
  });
}

// ── Status bar ────────────────────────────────────────────────────────────────
async function loadStatusBar() {
  try {
    const s = await getWorkerStatus();
    document.getElementById('db-status').textContent =
      `${s.water_quality.total_records.toLocaleString()} registros · ${s.water_quality.lagoas_com_dados} lagoas`;
  } catch { /* silencia */ }
}

// ── Data load ─────────────────────────────────────────────────────────────────
async function loadData() {
  showLoading(true);
  try {
    allData = await getWaterQuality();
    lagoas  = Object.keys(allData).sort();

    if (lagoas.length === 0) {
      showLoading(false);
      showEmpty();
      return;
    }

    populateLagoaSelectors();
    activeLagoa = lagoas[0];
    document.getElementById('lagoa-select').value = activeLagoa;

    await Promise.all([renderKPIs(), renderCharts()]);
    initChartActions();
    table.load(allData);
    updateLagoaTag(activeLagoa);
    initAnalytics(lagoas);
    showLoading(false);
  } catch (err) {
    showLoading(false);
    console.error('Erro ao carregar dados:', err);
  }
}

// ── KPI cards ─────────────────────────────────────────────────────────────────
async function renderKPIs() {
  const current = await getCurrentStatus();
  const grid = document.getElementById('kpi-grid');

  grid.innerHTML = lagoas.map(lg => {
    const c   = current[lg];
    const cls = classifyNdci(c?.ndci_mean);
    const total = allData[lg]?.periodos.length ?? 0;

    return `
      <div class="kpi" data-status="${cls.status}">
        <div class="kpi-top">
          <span class="label">Lagoa</span>
        </div>
        <span class="lagoa-name">${lg.replace('Lagoa ', '')}</span>
        <span class="periodo">${c?.periodo ?? '—'} · ${total} meses</span>
        <span class="ndci-value" style="color:${cls.color}">${fmtNdci(c?.ndci_mean)}</span>
        <div class="kpi-bottom">
          <span class="badge badge-${cls.status}">${cls.label}</span>
          ${c?.n_pixels ? `<span style="font-size:.68rem;color:var(--muted)">${c.n_pixels.toLocaleString()} px</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ── Charts ────────────────────────────────────────────────────────────────────
async function renderCharts() {
  ['series', 'indices', 'compare', 'seasonal', 'distribution', 'scatter']
    .forEach(k => destroyChart(k));
  hidePointDetail();

  const d = allData[activeLagoa];
  if (!d) return;

  await renderSeriesChart();
  charts.indices      = buildIndicesChart('chart-indices',   d);
  charts.compare      = buildCompareChart('chart-compare',   allData);
  charts.seasonal     = buildSeasonalChart('chart-seasonal', allData);
  charts.distribution = buildDistributionChart('chart-dist', allData);
  charts.scatter      = buildScatterChart('chart-scatter',   allData);
}

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

// ── Lagoa selector ────────────────────────────────────────────────────────────
function populateLagoaSelectors() {
  document.querySelectorAll('.lagoa-select').forEach(sel => {
    sel.innerHTML = lagoas.map(lg =>
      `<option value="${lg}">${lg}</option>`
    ).join('');
  });
}

async function onLagoaChange(e) {
  activeLagoa = e.target.value;
  document.querySelectorAll('.lagoa-select').forEach(s => { s.value = activeLagoa; });
  updateLagoaTag(activeLagoa);
  destroyChart('series');
  destroyChart('indices');
  hidePointDetail();
  await renderSeriesChart();
  charts.indices = buildIndicesChart('chart-indices', allData[activeLagoa]);
}

function updateLagoaTag(name) {
  const tag = document.getElementById('series-lagoa-tag');
  if (tag) tag.textContent = name ?? '—';
}

// ── Point detail panel ────────────────────────────────────────────────────────
function onSeriesPointClick(idx, data) {
  const periodo  = data.datas?.[idx] ?? data.periodos?.[idx] ?? '—';
  const ndci     = data.ndci_mean?.[idx];
  const ndci_p90 = data.ndci_p90?.[idx]  ?? null;
  const turbidez = data.turbidez?.[idx]  ?? null;
  const ndwi     = data.ndwi_mean?.[idx] ?? null;
  const n_pixels = data.n_pixels?.[idx]  ?? null;
  const cls      = classifyNdci(ndci);

  const panel = document.getElementById('point-detail');
  panel.dataset.status = cls.status;
  panel.className = 'point-detail visible';
  panel.innerHTML = `
    <div class="pd-status-bar"></div>
    <div class="pd-content">
      <div class="pd-left">
        <span class="pd-period">${periodo}</span>
        <span class="badge badge-${cls.status}">${cls.label}</span>
      </div>
      <div class="pd-stats">
        <div class="pd-stat">
          <span class="pd-label">NDCI médio</span>
          <span class="pd-value" style="color:${cls.color}">${fmtNdci(ndci)}</span>
        </div>
        ${ndci_p90 != null ? `<div class="pd-stat"><span class="pd-label">P90</span><span class="pd-value">${fmtNdci(ndci_p90)}</span></div>` : ''}
        ${turbidez != null ? `<div class="pd-stat"><span class="pd-label">Turbidez (NDTI)</span><span class="pd-value">${fmtNum(turbidez, 4)}</span></div>` : ''}
        ${ndwi     != null ? `<div class="pd-stat"><span class="pd-label">NDWI</span><span class="pd-value">${fmtNum(ndwi, 4)}</span></div>` : ''}
        ${n_pixels != null ? `<div class="pd-stat"><span class="pd-label">Pixels válidos</span><span class="pd-value">${n_pixels.toLocaleString('pt-BR')}</span></div>` : ''}
      </div>
      <button class="pd-close" title="Fechar">✕</button>
    </div>
  `;
  panel.querySelector('.pd-close').addEventListener('click', hidePointDetail);
}

function hidePointDetail() {
  const panel = document.getElementById('point-detail');
  if (panel) panel.className = 'point-detail';
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showLoading(on) {
  document.getElementById('loading').style.display  = on ? 'flex'  : 'none';
  document.getElementById('content').style.display  = on ? 'none'  : 'block';
}

function showEmpty() {
  document.getElementById('content').style.display  = 'block';
  document.getElementById('empty-msg').style.display = 'flex';
}

// ── Event listeners ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('lagoa-select')?.addEventListener('change', onLagoaChange);
  document.getElementById('reload-btn')?.addEventListener('click', loadData);
  document.getElementById('export-html-btn')?.addEventListener('click', exportHTML);

  const onDateFilterChange = async () => {
    destroyChart('series');
    hidePointDetail();
    await renderSeriesChart();
  };
  document.getElementById('series-date-from')?.addEventListener('change', onDateFilterChange);
  document.getElementById('series-date-to')?.addEventListener('change', onDateFilterChange);

  init();
});
