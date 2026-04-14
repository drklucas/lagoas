/**
 * Orquestração principal — inicializa tudo e gerencia interações.
 */

import { getWaterQuality, getCurrentStatus, getWorkerStatus } from './api.js';
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

let charts      = {};
const table     = new DataTable();

let allData     = {};
let lagoas      = [];
let activeLagoa = null;

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initTabs();
  await Promise.all([loadStatusBar(), loadData()]);
  setInterval(loadStatusBar, 30_000);
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;

      document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b === btn)
      );
      document.getElementById('tab-dashboard').style.display =
        tab === 'dashboard' ? 'flex' : 'none';
      document.getElementById('tab-table').style.display =
        tab === 'table' ? 'flex' : 'none';
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
function renderCharts() {
  ['series', 'indices', 'compare', 'seasonal', 'distribution', 'scatter']
    .forEach(k => destroyChart(k));
  hidePointDetail();

  const d = allData[activeLagoa];
  if (!d) return;

  charts.series       = buildSeriesChart('chart-series', activeLagoa, d, onSeriesPointClick);
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

function onLagoaChange(e) {
  activeLagoa = e.target.value;
  document.querySelectorAll('.lagoa-select').forEach(s => { s.value = activeLagoa; });
  destroyChart('series');
  destroyChart('indices');
  hidePointDetail();
  charts.series  = buildSeriesChart('chart-series',  activeLagoa, allData[activeLagoa], onSeriesPointClick);
  charts.indices = buildIndicesChart('chart-indices', allData[activeLagoa]);
}

// ── Point detail panel ────────────────────────────────────────────────────────
function onSeriesPointClick(idx, data) {
  const periodo  = data.periodos[idx];
  const ndci     = data.ndci_mean[idx];
  const ndci_p90 = data.ndci_p90?.[idx] ?? null;
  const turbidez = data.turbidez[idx];
  const ndwi     = data.ndwi_mean[idx];
  const n_pixels = data.n_pixels[idx];
  const cls      = classifyNdci(ndci);

  const panel = document.getElementById('point-detail');
  panel.className = 'point-detail visible';
  panel.innerHTML = `
    <span class="pd-period">${periodo}</span>
    <div class="pd-stats">
      <div class="pd-stat">
        <span class="pd-label">NDCI médio</span>
        <span class="pd-value" style="color:${cls.color}">${fmtNdci(ndci)}</span>
      </div>
      ${ndci_p90 != null ? `
      <div class="pd-stat">
        <span class="pd-label">NDCI p90</span>
        <span class="pd-value">${fmtNdci(ndci_p90)}</span>
      </div>` : ''}
      ${turbidez != null ? `
      <div class="pd-stat">
        <span class="pd-label">Turbidez (NDTI)</span>
        <span class="pd-value">${fmtNum(turbidez, 4)}</span>
      </div>` : ''}
      ${ndwi != null ? `
      <div class="pd-stat">
        <span class="pd-label">NDWI</span>
        <span class="pd-value">${fmtNum(ndwi, 4)}</span>
      </div>` : ''}
      ${n_pixels != null ? `
      <div class="pd-stat">
        <span class="pd-label">Pixels</span>
        <span class="pd-value">${n_pixels.toLocaleString()}</span>
      </div>` : ''}
      <div class="pd-stat">
        <span class="pd-label">Status</span>
        <span class="badge badge-${cls.status}">${cls.label}</span>
      </div>
    </div>
    <button class="pd-close" title="Fechar">✕</button>
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
  init();
});
