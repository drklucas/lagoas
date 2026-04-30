/**
 * Orquestração principal — inicializa tudo e gerencia interações.
 */

import { getWaterQuality, getAvailableZones, getAllImageSeries, getImageSeries, getZoneSeries, getRegions, getCurrentStatus, getWorkerStatus, getVegetation, getVegetationImages } from './api.js';
import { classifyNdci, fmtNdci, fmtNum, lagoaColor, rgba } from './utils.js';
import {
  buildSeriesChart,
  buildIndicesChart,
  buildSeasonalChart,
  buildDistributionChart,
  buildScatterChart,
  buildCompareChart,
  buildZoneChart,
  buildZoneFocusChart,
  buildNdviChart,
} from './charts.js';
import { DataTable } from './table.js';
import { initChartActions } from './chart-actions.js';
import { initMap } from './map.js';
import { initAnalytics, loadAnalytics } from './analytics.js';
import { exportHTML } from './export-html.js';

let charts      = {};
const table     = new DataTable();

let allData       = {};
let imageData     = {};   // cache: lagoa → dados por imagem (zona=total)
let zoneData      = {};   // cache: lagoa → dados mensais por zona
let zoneImageData = {};   // cache: `${lagoa}:${zona}` → dados por imagem para zona
let geoRegionData = {};   // cache: lagoa → lista de geo_regions
let vegData       = {};   // cache: série mensal de NDVI por lagoa
let vegImageData  = {};   // cache: NDVI por imagem individual
let lagoas        = [];
let activeLagoa   = null;
let vegLagoa      = null;
let viewMode      = 'mensal';   // 'mensal' | 'imagem' | 'zonas'
let vegViewMode   = 'mensal';   // 'mensal' | 'imagem'

const ZONE_DISPLAY = { margem: 'Margem', medio: 'Médio', nucleo: 'Núcleo' };

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initTabs();
  initViewToggle();
  initVegViewToggle();
  await Promise.all([loadStatusBar(), loadData()]);
  setInterval(loadStatusBar, 30_000);
}

// ── Toggle mensal / por imagem / zonas ───────────────────────────────────────
function initViewToggle() {
  const toggle    = document.getElementById('view-toggle');
  const zoneBtn   = document.getElementById('zone-toggle-btn');

  toggle?.addEventListener('change', async () => {
    if (toggle.checked) {
      viewMode = 'imagem';
      zoneBtn?.classList.remove('active');
    } else {
      viewMode = 'mensal';
    }
    await Promise.all([renderSeriesChart(), renderZonesCard(), renderGeoRegionsCard()]);
  });

  zoneBtn?.addEventListener('click', async () => {
    if (viewMode === 'zonas') {
      viewMode = 'mensal';
      zoneBtn.classList.remove('active');
    } else {
      viewMode = 'zonas';
      zoneBtn.classList.add('active');
      if (toggle) { toggle.checked = false; }
    }
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
    ndti_mean: pick(data.ndti_mean),
    fai_mean:  pick(data.fai_mean),
    ndwi_mean: pick(data.ndwi_mean),
    n_pixels:  pick(data.n_pixels),
  };
}

async function renderSeriesChart() {
  destroyChart('series');
  hidePointDetail();

  const { from, to } = getDateFilter();

  if (viewMode === 'zonas') {
    if (!zoneData[activeLagoa]) {
      try {
        zoneData[activeLagoa] = await getZoneSeries(activeLagoa);
      } catch {
        zoneData[activeLagoa] = null;
      }
    }
    const raw = zoneData[activeLagoa];
    if (raw && Object.keys(raw.zonas ?? {}).length > 0) {
      charts.series = buildZoneChart('chart-series', activeLagoa, raw);
      return;
    }
    // sem dados por zona — cai no mensal com aviso
    viewMode = 'mensal';
    document.getElementById('zone-toggle-btn')?.classList.remove('active');
  }

  if (viewMode === 'imagem') {
    if (!imageData[activeLagoa]) {
      try {
        imageData[activeLagoa] = await getImageSeries(activeLagoa);
      } catch {
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

// ── Zonas — helpers compartilhados ────────────────────────────────────────────

/** Garante que zoneData e geoRegionData estejam populados para activeLagoa. */
async function _ensureZoneCache() {
  if (!zoneData[activeLagoa]) {
    try { zoneData[activeLagoa] = await getZoneSeries(activeLagoa); }
    catch { zoneData[activeLagoa] = null; }
  }
  if (!geoRegionData[activeLagoa]) {
    try { geoRegionData[activeLagoa] = await getRegions(activeLagoa); }
    catch { geoRegionData[activeLagoa] = []; }
  }
}

/** Garante cache por imagem para as zonas informadas da lagoa ativa. */
async function _ensureZoneImageCache(zoneNames = []) {
  if (viewMode !== 'imagem' || !zoneNames.length) return;

  await Promise.all(zoneNames.map(async (zona) => {
    const key = `${activeLagoa}:${zona}`;
    if (zoneImageData[key] !== undefined) return;
    try {
      zoneImageData[key] = await getImageSeries(activeLagoa, zona);
    } catch {
      zoneImageData[key] = null;
    }
  }));
}

/** Separa zonas do config (margem/médio/núcleo) das regiões desenhadas pelo user. */
function _splitZonas(zonas, geoRegions) {
  const drawnNames = new Set((geoRegions ?? []).map(r => r.nome));
  const config = {}, drawn = {};
  for (const [nome, data] of Object.entries(zonas)) {
    if (drawnNames.has(nome)) drawn[nome] = data;
    else                      config[nome] = data;
  }
  return { config, drawn };
}

/** Renderiza seletor de pills + gráfico para um subconjunto de zonas.
 *  imageDataMap — dict opcional: zona → dados por imagem (quando viewMode='imagem')
 *  fetchImageData — callback opcional para buscar dados por imagem sob demanda
 */
function _renderZoneCard({
  cardId, tagId, selectorId, chartId, chartKey, zonas, label, imageDataMap = {}, fetchImageData = null,
}) {
  const card = document.getElementById(cardId);
  if (!card) return;

  const zoneNames = Object.keys(zonas);
  if (!zoneNames.length) { card.style.display = 'none'; return; }

  card.style.display = '';
  const tag = document.getElementById(tagId);
  if (tag) tag.textContent = activeLagoa;

  const selector = document.getElementById(selectorId);
  if (!selector) return;

  let active = selector.querySelector('.zone-pill.active')?.dataset.zona;
  if (!active || !zonas[active]) active = zoneNames[0];

  selector.innerHTML = zoneNames.map(z =>
    `<button class="zone-pill${z === active ? ' active' : ''}" data-zona="${z}">${label(z)}</button>`
  ).join('');

  let renderSeq = 0;
  const renderZoneChart = async (zona) => {
    const seq = ++renderSeq;
    destroyChart(chartKey);
    let rawImageData = imageDataMap[zona];
    if (viewMode === 'imagem' && (rawImageData === undefined || rawImageData === null) && fetchImageData) {
      rawImageData = await fetchImageData(zona);
      imageDataMap[zona] = rawImageData;
    }
    if (seq !== renderSeq) return;

    // Modo imagem deve usar exclusivamente dados por imagem (sem fallback mensal).
    const rawData = viewMode === 'imagem'
      ? rawImageData
      : zonas[zona];
    if (!rawData) return;
    const { from, to } = getDateFilter();
    const filtered = filterDataByDateRange(rawData, from, to);
    if (seq !== renderSeq) return;
    charts[chartKey] = buildZoneFocusChart(chartId, filtered);
  };

  selector.querySelectorAll('.zone-pill').forEach(btn => {
    btn.addEventListener('click', async () => {
      selector.querySelectorAll('.zone-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      await renderZoneChart(btn.dataset.zona);
    });
  });

  void renderZoneChart(active);
}

// ── Card 2: zonas de config (anéis concêntricos) ─────────────────────────────

async function renderZonesCard() {
  await _ensureZoneCache();
  const zonas = zoneData[activeLagoa]?.zonas ?? {};
  const { config } = _splitZonas(zonas, geoRegionData[activeLagoa]);
  await _ensureZoneImageCache(Object.keys(config));
  const imageDataMap = Object.fromEntries(
    Object.keys(config).map(z => [z, zoneImageData[`${activeLagoa}:${z}`]])
  );
  _renderZoneCard({
    cardId:    'zones-card',
    tagId:     'zones-lagoa-tag',
    selectorId:'zones-selector',
    chartId:   'chart-zones-focus',
    chartKey:  'zonesFocus',
    zonas:     config,
    imageDataMap,
    fetchImageData: async (zona) => {
      const key = `${activeLagoa}:${zona}`;
      if (zoneImageData[key] === undefined) {
        try { zoneImageData[key] = await getImageSeries(activeLagoa, zona); }
        catch { zoneImageData[key] = null; }
      }
      return zoneImageData[key];
    },
    label:     z => ZONE_DISPLAY[z] ?? z,
  });
}

// ── Card 3: regiões desenhadas pelo usuário ───────────────────────────────────

async function renderGeoRegionsCard() {
  await _ensureZoneCache();
  const zonas = zoneData[activeLagoa]?.zonas ?? {};
  const { drawn } = _splitZonas(zonas, geoRegionData[activeLagoa]);
  await _ensureZoneImageCache(Object.keys(drawn));
  const imageDataMap = Object.fromEntries(
    Object.keys(drawn).map(z => [z, zoneImageData[`${activeLagoa}:${z}`]])
  );
  _renderZoneCard({
    cardId:    'geo-regions-card',
    tagId:     'geo-regions-lagoa-tag',
    selectorId:'geo-regions-selector',
    chartId:   'chart-geo-regions-focus',
    chartKey:  'geoRegionsFocus',
    zonas:     drawn,
    imageDataMap,
    fetchImageData: async (zona) => {
      const key = `${activeLagoa}:${zona}`;
      if (zoneImageData[key] === undefined) {
        try { zoneImageData[key] = await getImageSeries(activeLagoa, zona); }
        catch { zoneImageData[key] = null; }
      }
      return zoneImageData[key];
    },
    label:     z => z,   // nomes livres — mostra como está
  });
}

// ── Vegetação ─────────────────────────────────────────────────────────────────
function initVegViewToggle() {
  document.getElementById('veg-view-toggle')?.addEventListener('change', async (e) => {
    vegViewMode = e.target.checked ? 'imagem' : 'mensal';
    await renderNdviChart();
  });
}

async function loadVegetationTab() {
  if (Object.keys(vegData).length === 0) {
    try { vegData = await getVegetation(); } catch { vegData = {}; }
  }

  const vegLagoas = Object.keys(vegData).sort();
  const sel = document.getElementById('veg-lagoa-select');

  if (sel) {
    const opts = vegLagoas.length ? vegLagoas : lagoas;
    sel.innerHTML = opts.map(lg => `<option value="${lg}">${lg}</option>`).join('');
    if (!sel.dataset.listenerBound) {
      sel.dataset.listenerBound = '1';
      sel.addEventListener('change', async (e) => {
        vegLagoa = e.target.value;
        document.getElementById('veg-lagoa-tag').textContent = vegLagoa ?? '—';
        await renderNdviChart();
      });
    }
  }

  if (!vegLagoa) vegLagoa = vegLagoas[0] ?? lagoas[0] ?? null;
  if (sel && vegLagoa) sel.value = vegLagoa;
  document.getElementById('veg-lagoa-tag').textContent = vegLagoa ?? '—';

  const hasData = vegLagoas.length > 0;
  document.getElementById('veg-empty').style.display = hasData ? 'none' : 'flex';

  await renderNdviChart();
  renderNdviCompare();
}

async function renderNdviChart() {
  if (charts.ndvi) { charts.ndvi.destroy(); delete charts.ndvi; }
  if (!vegLagoa) return;

  let data = null;

  if (vegViewMode === 'imagem') {
    if (!vegImageData[vegLagoa]) {
      try { vegImageData[vegLagoa] = await getVegetationImages(vegLagoa); }
      catch { vegImageData[vegLagoa] = null; }
    }
    data = vegImageData[vegLagoa];
    if (!data?.datas?.length) {
      vegViewMode = 'mensal';
      document.getElementById('veg-view-toggle').checked = false;
    }
  }

  if (!data || vegViewMode === 'mensal') {
    data = vegData[vegLagoa];
  }

  if (!data) return;
  charts.ndvi = buildNdviChart('chart-ndvi', vegLagoa, data);
}

function renderNdviCompare() {
  if (charts.ndviCompare) { charts.ndviCompare.destroy(); delete charts.ndviCompare; }
  if (!Object.keys(vegData).length) return;

  const canvas = document.getElementById('chart-ndvi-compare');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const lgs = Object.keys(vegData).sort();

  const values = lgs.map(lg => {
    const mean  = vegData[lg]?.ndvi_mean ?? [];
    const valid = mean.filter(v => v != null);
    return valid.length ? valid[valid.length - 1] : null;
  });

  charts.ndviCompare = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: lgs.map(lg => lg.replace('Lagoa ', '')),
      datasets: [{
        label: 'NDVI médio (último mês)',
        data: values,
        backgroundColor: lgs.map((lg, i) => rgba(lagoaColor(lg, i), 0.70)),
        borderColor:     lgs.map((lg, i) => lagoaColor(lg, i)),
        borderWidth: 1.5,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2330',
          borderColor: '#30363d',
          borderWidth: 1,
          callbacks: {
            label: ({ raw }) => raw != null ? `NDVI: ${raw.toFixed(4)}` : 'sem dados',
          },
        },
        annotation: {
          annotations: {
            healthy: {
              type: 'line', yMin: 0.5, yMax: 0.5,
              borderColor: 'rgba(63,185,80,0.50)',
              borderWidth: 1.5, borderDash: [5, 3],
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#7d8590', font: { size: 10 } },
          grid:  { color: 'rgba(48,54,61,0.6)' },
        },
        y: {
          min: 0, max: 1,
          ticks: { color: '#7d8590', font: { size: 10 } },
          grid:  { color: 'rgba(48,54,61,0.6)' },
          title: { display: true, text: 'NDVI', color: '#7d8590', font: { size: 10 } },
        },
      },
    },
  });
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
      document.getElementById('tab-vegetation').style.display =
        tab === 'vegetation' ? 'flex' : 'none';

      if (tab === 'map') {
        await initMap();
      }
      if (tab === 'analytics') {
        await loadAnalytics();
      }
      if (tab === 'vegetation') {
        await loadVegetationTab();
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

// ── Tabela — filtro de zona ────────────────────────────────────────────────────

async function _reloadTableForZona(zona) {
  try {
    const data = await getAllImageSeries(null, zona);
    table.loadImages(data, zona);
  } catch {
    const zonaSel = document.getElementById('filter-zona');
    if (zonaSel) zonaSel.value = 'total';
    const data = await getAllImageSeries(null, 'total').catch(() => ({}));
    table.loadImages(data, 'total');
  }
}

async function _initTableZonaFilter() {
  table.onZonaChange = _reloadTableForZona;
  try {
    const { zones } = await getAvailableZones();
    table.setZonaOptions(zones);
  } catch { /* mantém opção padrão 'total' */ }
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
    updateLagoaTag(activeLagoa);
    initAnalytics(lagoas);
    showLoading(false);
    // Carrega tabela com image records (em paralelo, não bloqueia a UI)
    _initTableZonaFilter();
    getAllImageSeries(null, 'total').then(d => table.loadImages(d, 'total')).catch(() => {});
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
  ['series', 'indices', 'compare', 'seasonal', 'distribution', 'scatter', 'zonesFocus', 'geoRegionsFocus']
    .forEach(k => destroyChart(k));
  hidePointDetail();

  const d = allData[activeLagoa];
  if (!d) return;

  await Promise.all([renderSeriesChart(), renderZonesCard(), renderGeoRegionsCard()]);
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
  destroyChart('zonesFocus');
  destroyChart('geoRegionsFocus');
  hidePointDetail();
  await Promise.all([renderSeriesChart(), renderZonesCard(), renderGeoRegionsCard()]);
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
    destroyChart('zonesFocus');
    destroyChart('geoRegionsFocus');
    hidePointDetail();
    await Promise.all([renderSeriesChart(), renderZonesCard(), renderGeoRegionsCard()]);
  };
  document.getElementById('series-date-from')?.addEventListener('change', onDateFilterChange);
  document.getElementById('series-date-to')?.addEventListener('change', onDateFilterChange);

  init();
});
