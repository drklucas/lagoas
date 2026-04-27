/**
 * Aba de Análises Estatísticas — Mann-Kendall Sazonal + CUSUM.
 *
 * Referências:
 *   Hirsch et al. (1982) — Seasonal Mann-Kendall
 *   Page (1954)          — CUSUM change-point detection
 */

import { fetchJSON } from './api.js';
import { fmtNum } from './utils.js';

// ── API calls ─────────────────────────────────────────────────────────────────

const _trend      = (lagoa, alpha) =>
  fetchJSON(`/api/analytics/${encodeURIComponent(lagoa)}/trend?alpha=${alpha}`);

const _changepoint = (lagoa, index, useImages) =>
  fetchJSON(
    `/api/analytics/${encodeURIComponent(lagoa)}/changepoint` +
    `?index=${index}&use_images=${useImages}`
  );

// ── Constants ─────────────────────────────────────────────────────────────────

const INDEX_LABELS = {
  ndci: 'NDCI — Clorofila',
  ndti: 'NDTI — Turbidez',
  ndwi: 'NDWI — Corpo d\'Água',
  fai:  'FAI — Algas Flutuantes',
};

const TREND_CFG = {
  crescente:     { label: 'Crescente',     cls: 'trend-up',      arrow: '↑' },
  decrescente:   { label: 'Decrescente',   cls: 'trend-down',    arrow: '↓' },
  sem_tendencia: { label: 'Sem Tendência', cls: 'trend-neutral', arrow: '→' },
};

// ── Module state ──────────────────────────────────────────────────────────────

let _lagoas          = [];
let _activeLagoa     = null;
let _activeCusumIdx  = 'ndci';
let _useImages       = true;
let _cusumSeriesChart = null;
let _cusumStatChart   = null;
let _initialized     = false;

// ── Public API ────────────────────────────────────────────────────────────────

export function initAnalytics(lagoas) {
  _lagoas = lagoas ?? [];
  if (!_lagoas.length) return;
  _activeLagoa = _lagoas[0];

  _buildLagoaSelector();
  _buildCusumControls();
  _initialized = true;
}

export async function loadAnalytics() {
  if (!_initialized || !_activeLagoa) return;
  _setStatus('Carregando análises…');
  try {
    const [trend, cusum] = await Promise.all([
      _trend(_activeLagoa, 0.05),
      _changepoint(_activeLagoa, _activeCusumIdx, _useImages),
    ]);
    _renderMKCards(trend);
    _renderCusum(cusum);
    _setStatus('');
  } catch (err) {
    _setStatus(`Erro ao carregar: ${err.message}`);
    console.error('[analytics]', err);
  }
}

// ── Selectors ─────────────────────────────────────────────────────────────────

function _buildLagoaSelector() {
  const sel = document.getElementById('analytics-lagoa-select');
  if (!sel) return;
  sel.innerHTML = _lagoas
    .map(lg => `<option value="${lg}">${lg}</option>`)
    .join('');
  sel.addEventListener('change', () => {
    _activeLagoa = sel.value;
    loadAnalytics();
  });
}

function _buildCusumControls() {
  const sel = document.getElementById('cusum-index-select');
  if (!sel) return;
  sel.innerHTML = Object.entries(INDEX_LABELS)
    .map(([k, v]) => `<option value="${k}">${v}</option>`)
    .join('');
  sel.addEventListener('change', async () => {
    _activeCusumIdx = sel.value;
    await _reloadCusum();
  });

  const toggle = document.getElementById('cusum-granularity-toggle');
  if (toggle) {
    toggle.addEventListener('change', async () => {
      _useImages = toggle.checked;
      await _reloadCusum();
    });
  }
}

async function _reloadCusum() {
  _setStatus('Carregando CUSUM…');
  try {
    const cusum = await _changepoint(_activeLagoa, _activeCusumIdx, _useImages);
    _renderCusum(cusum);
    _setStatus('');
  } catch (err) {
    _setStatus(`Erro CUSUM: ${err.message}`);
  }
}

function _setStatus(msg) {
  const el = document.getElementById('analytics-status');
  if (el) el.textContent = msg;
}

// ── Mann-Kendall cards ────────────────────────────────────────────────────────

function _renderMKCards(trend) {
  const container = document.getElementById('mk-cards');
  if (!container) return;

  if (trend.erro || !trend.indices) {
    container.innerHTML = `<p class="analytics-empty">${trend.erro ?? 'Sem dados'}</p>`;
    return;
  }

  container.innerHTML = Object.entries(trend.indices).map(([, r]) => {
    const cfg = TREND_CFG[r.trend] ?? TREND_CFG.sem_tendencia;
    const pStr = r.p_value < 0.001 ? '<0.001' : r.p_value.toFixed(3);
    const sigTag = r.significativo
      ? `<span class="sig-badge sig-yes">p = ${pStr}</span>`
      : `<span class="sig-badge sig-no">p = ${pStr} n.s.</span>`;
    const slopeSign = r.sen_slope_ano >= 0 ? '+' : '';
    const slopeStr  = r.sen_slope_ano !== 0
      ? `${slopeSign}${r.sen_slope_ano.toExponential(2)} /ano`
      : '≈ 0';

    return `
      <div class="mk-card">
        <div class="mk-card-top">
          <span class="mk-index-label">${r.label}</span>
          <span class="trend-badge ${cfg.cls}">${cfg.arrow} ${cfg.label}</span>
        </div>
        <div class="mk-stats-row">
          ${sigTag}
          <span class="mk-stat" title="Estatística Z de Mann-Kendall">Z = ${r.z_score >= 0 ? '+' : ''}${r.z_score.toFixed(2)}</span>
          <span class="mk-stat" title="Inclinação de Sen (taxa de variação anual)">β = ${slopeStr}</span>
        </div>
        <div class="mk-meta-row">
          <span class="mk-meta">n = ${r.n_obs} obs</span>
          <span class="mk-meta">${r.periodo_inicio} → ${r.periodo_fim}</span>
          ${r.erro ? `<span class="mk-meta mk-warn">${r.erro}</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ── CUSUM charts ──────────────────────────────────────────────────────────────

function _destroyCusum() {
  if (_cusumSeriesChart) { _cusumSeriesChart.destroy(); _cusumSeriesChart = null; }
  if (_cusumStatChart)   { _cusumStatChart.destroy();   _cusumStatChart   = null; }
}

function _renderCusum(data) {
  _destroyCusum();
  const alarmsEl = document.getElementById('cusum-alarms');

  if (data.erro || !data.series?.periodos?.length) {
    if (alarmsEl) alarmsEl.innerHTML = `<p class="analytics-empty">${data.erro ?? 'Sem dados'}</p>`;
    return;
  }

  const { periodos, valores, cusum_pos, cusum_neg, h, baseline_mean } = data.series;
  const alarmSet = new Set(data.alarmes.map(a => a.periodo));

  // ── Série bruta ────────────────────────────────────────────────────────────
  const seriesCtx = document.getElementById('cusum-series-chart');
  if (seriesCtx) {
    _cusumSeriesChart = new Chart(seriesCtx, {
      type: 'line',
      data: {
        labels: periodos,
        datasets: [
          {
            label: data.index_label ?? data.index,
            data: valores,
            borderColor: '#2188ff',
            backgroundColor: 'rgba(33,136,255,0.07)',
            borderWidth: 1.5,
            pointRadius: periodos.map(p => alarmSet.has(p) ? 6 : 1.5),
            pointBackgroundColor: periodos.map(p =>
              alarmSet.has(p) ? '#f85149' : '#2188ff'
            ),
            pointBorderColor: periodos.map(p =>
              alarmSet.has(p) ? '#f85149' : 'transparent'
            ),
            tension: 0.3,
            spanGaps: true,
            fill: true,
          },
          {
            label: `Média baseline (${fmtNum(baseline_mean, 4)})`,
            data: Array(periodos.length).fill(baseline_mean),
            borderColor: 'rgba(210,153,34,0.65)',
            borderDash: [6, 4],
            borderWidth: 1.2,
            pointRadius: 0,
          },
        ],
      },
      options: _chartOpts(data.index_label ?? data.index, false),
    });
  }

  // ── Estatística CUSUM ──────────────────────────────────────────────────────
  const statCtx = document.getElementById('cusum-stat-chart');
  if (statCtx) {
    _cusumStatChart = new Chart(statCtx, {
      type: 'line',
      data: {
        labels: periodos,
        datasets: [
          {
            label: 'CUSUM⁺ (elevação)',
            data: cusum_pos,
            borderColor: '#f85149',
            backgroundColor: 'rgba(248,81,73,0.07)',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
          {
            label: 'CUSUM⁻ (queda)',
            data: cusum_neg,
            borderColor: '#3fb950',
            backgroundColor: 'rgba(63,185,80,0.07)',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
          {
            label: `Limiar h = ${fmtNum(h, 4)}`,
            data: Array(periodos.length).fill(h),
            borderColor: 'rgba(248,81,73,0.6)',
            borderDash: [8, 4],
            borderWidth: 1.5,
            pointRadius: 0,
          },
        ],
      },
      options: _chartOpts('CUSUM', true),
    });
  }

  // ── Alarmes ────────────────────────────────────────────────────────────────
  if (!alarmsEl) return;

  const paramsLine = [
    `Baseline: ${data.baseline.periodo} (n=${data.baseline.n_obs})`,
    `μ₀ = ${fmtNum(data.baseline.mean, 4)}`,
    `σ₀ = ${fmtNum(data.baseline.std, 4)}`,
    `k = ${fmtNum(data.parametros.k, 4)}`,
    `h = ${fmtNum(data.parametros.h, 4)}`,
  ].join(' · ');

  if (!data.alarmes.length) {
    alarmsEl.innerHTML = `
      <div class="cusum-params-line">${paramsLine}</div>
      <p class="cusum-no-alarm">Nenhuma quebra de regime detectada no período analisado.</p>
    `;
    return;
  }

  alarmsEl.innerHTML = `
    <div class="cusum-params-line">${paramsLine}</div>
    <div class="cusum-alarm-list">
      ${data.alarmes.map(a => `
        <div class="cusum-alarm-item cusum-alarm-${a.tipo}">
          <span class="alarm-icon">${a.tipo === 'elevacao' ? '▲' : '▼'}</span>
          <div class="alarm-body">
            <span class="alarm-tipo">${a.tipo === 'elevacao' ? 'Elevação detectada' : 'Queda detectada'}</span>
            <span class="alarm-detail">em <strong>${a.periodo}</strong> · CUSUM = ${fmtNum(a.cusum_value, 4)}</span>
            <span class="alarm-shift">Início estimado do desvio: ${a.data_inicio_shift ?? '—'}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

// ── Chart options ─────────────────────────────────────────────────────────────

function _chartOpts(yLabel, isCusum) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: { color: '#7d8590', font: { size: 11 }, boxWidth: 16, padding: 10 },
      },
      tooltip: {
        backgroundColor: '#1c2330',
        borderColor: '#30363d',
        borderWidth: 1,
        titleColor: '#7d8590',
        bodyColor: '#c9d1d9',
        callbacks: {
          label: ctx => ` ${ctx.dataset.label}: ${fmtNum(ctx.parsed.y, 5)}`,
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#7d8590',
          font: { size: 10 },
          maxTicksLimit: isCusum ? 14 : 16,
          maxRotation: 0,
        },
        grid: { color: 'rgba(48,54,61,0.45)' },
      },
      y: {
        ticks: { color: '#7d8590', font: { size: 10 } },
        grid: { color: 'rgba(48,54,61,0.45)' },
        title: {
          display: true,
          text: yLabel,
          color: '#7d8590',
          font: { size: 10 },
        },
      },
    },
  };
}
