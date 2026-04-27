/**
 * Exporta a página atual como HTML autossuficiente.
 * Captura gráficos como imagens base64, clona KPIs e resultados analíticos.
 */

// ── Captura de canvas ─────────────────────────────────────────────────────────

function _canvasToDataUrl(id) {
  const canvas = document.getElementById(id);
  if (!canvas || canvas.width === 0) return null;
  const tmp = document.createElement('canvas');
  tmp.width  = canvas.width;
  tmp.height = canvas.height;
  const ctx = tmp.getContext('2d');
  ctx.fillStyle = '#161b22';
  ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(canvas, 0, 0);
  return tmp.toDataURL('image/png');
}

function _chartImg(id, alt) {
  const src = _canvasToDataUrl(id);
  if (!src) return '';
  return `<img src="${src}" alt="${alt}" class="chart-img" />`;
}

// ── Clones de DOM ─────────────────────────────────────────────────────────────

function _cloneHtml(id) {
  const el = document.getElementById(id);
  return el ? el.innerHTML : '';
}

function _activeTabLabel() {
  const btn = document.querySelector('.tab-btn.active');
  return btn?.textContent?.trim() ?? 'Dashboard';
}

// ── Construção do HTML ────────────────────────────────────────────────────────

function _buildHtml({ lagoaAtiva, dataExport, kpiHtml, chartsHtml, analyticsHtml }) {
  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>NDCI — Lagoas do Litoral Norte RS — ${dataExport}</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--surface:#161b22;--surface2:#1c2330;--surface3:#21262d;
  --border:#30363d;--border2:#444c56;--text:#e6edf3;--text2:#c9d1d9;
  --muted:#7d8590;--accent:#2188ff;
  --bom:#3fb950;--moderado:#d29922;--elevado:#f85149;--critico:#b91c1c;
  --sem-dados:#484f58;--radius:10px;--radius-sm:6px;
}
html{font-size:14px}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5}
/* Header */
.hdr{background:var(--surface);border-bottom:1px solid var(--border);
  padding:14px 32px;display:flex;align-items:center;justify-content:space-between}
.hdr h1{font-size:1rem;font-weight:600}
.hdr .sub{font-size:.72rem;color:var(--muted)}
.hdr .meta{font-size:.72rem;color:var(--muted);text-align:right;line-height:1.7}
/* Layout */
.page{max-width:1280px;margin:0 auto;padding:28px 32px 60px;
  display:flex;flex-direction:column;gap:24px}
/* Cards */
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px 24px}
.card-title{font-size:.82rem;font-weight:600;color:var(--text2)}
.section-label{font-size:.7rem;font-weight:600;color:var(--muted);
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
/* KPI grid */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.kpi{background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:14px 16px;display:flex;
  flex-direction:column;gap:5px}
.kpi .label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.lagoa-name{font-size:.88rem;font-weight:600;color:var(--text)}
.periodo{font-size:.68rem;color:var(--muted)}
.ndci-value{font-size:1.4rem;font-weight:700;font-variant-numeric:tabular-nums}
.kpi-bottom{display:flex;align-items:center;gap:8px;margin-top:2px}
/* Badges */
.badge{display:inline-flex;align-items:center;font-size:.65rem;font-weight:600;
  padding:2px 9px;border-radius:20px;border:1px solid;text-transform:uppercase;letter-spacing:.05em}
.badge-bom{color:var(--bom);border-color:rgba(63,185,80,.4);background:rgba(63,185,80,.1)}
.badge-moderado{color:var(--moderado);border-color:rgba(210,153,34,.4);background:rgba(210,153,34,.1)}
.badge-elevado{color:var(--elevado);border-color:rgba(248,81,73,.4);background:rgba(248,81,73,.1)}
.badge-critico{color:var(--critico);border-color:rgba(185,28,28,.4);background:rgba(185,28,28,.1)}
.badge-sem_dados{color:var(--sem-dados);border-color:var(--border);background:var(--surface3)}
/* Charts */
.chart-img{width:100%;border-radius:var(--radius-sm);display:block}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.chart-wrap{background:var(--surface2);border-radius:var(--radius-sm);padding:14px}
.chart-label{font-size:.75rem;font-weight:600;color:var(--text2);margin-bottom:10px}
/* Analytics — MK cards */
.mk-cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px;margin-top:10px}
.mk-card{background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.mk-card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.mk-index-label{font-size:.8rem;font-weight:600;color:var(--text2)}
.trend-badge{font-size:.68rem;font-weight:600;padding:3px 10px;border-radius:20px;border:1px solid;white-space:nowrap}
.trend-up{color:var(--elevado);border-color:rgba(248,81,73,.35);background:rgba(248,81,73,.08)}
.trend-down{color:var(--bom);border-color:rgba(63,185,80,.35);background:rgba(63,185,80,.08)}
.trend-neutral{color:var(--muted);border-color:var(--border);background:var(--surface3)}
.mk-stats-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sig-badge{font-size:.66rem;font-weight:700;padding:2px 8px;border-radius:20px;border:1px solid;white-space:nowrap}
.sig-yes{color:var(--elevado);border-color:rgba(248,81,73,.4);background:rgba(248,81,73,.08)}
.sig-no{color:var(--muted);border-color:var(--border);background:transparent}
.mk-stat{font-size:.73rem;color:var(--text2);font-variant-numeric:tabular-nums;white-space:nowrap}
.mk-meta-row{display:flex;gap:10px;flex-wrap:wrap}
.mk-meta{font-size:.67rem;color:var(--muted);font-variant-numeric:tabular-nums}
/* CUSUM alarms */
.cusum-params-line{font-size:.68rem;color:var(--muted);margin:8px 0;font-variant-numeric:tabular-nums}
.cusum-no-alarm{font-size:.78rem;color:var(--bom);padding:8px 0}
.cusum-alarm-list{display:flex;flex-direction:column;gap:6px;margin-top:6px}
.cusum-alarm-item{display:flex;align-items:flex-start;gap:10px;padding:10px 14px;border-radius:var(--radius-sm);border:1px solid}
.cusum-alarm-elevacao{background:rgba(248,81,73,.06);border-color:rgba(248,81,73,.25)}
.cusum-alarm-queda{background:rgba(63,185,80,.06);border-color:rgba(63,185,80,.25)}
.alarm-icon{font-size:1rem;line-height:1.4;flex-shrink:0}
.cusum-alarm-elevacao .alarm-icon{color:var(--elevado)}
.cusum-alarm-queda .alarm-icon{color:var(--bom)}
.alarm-body{display:flex;flex-direction:column;gap:2px}
.alarm-tipo{font-size:.78rem;font-weight:600;color:var(--text2)}
.alarm-detail,.alarm-shift{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums}
.alarm-detail strong{color:var(--text2);font-weight:500}
/* Analytics ref */
.analytics-ref{font-size:.68rem;color:var(--muted);font-style:italic;margin:4px 0 12px}
.analytics-empty{color:var(--muted);font-size:.82rem;padding:12px 0}
/* Footer */
.footer{text-align:center;font-size:.68rem;color:var(--muted);
  padding:20px 0;border-top:1px solid var(--border);margin-top:8px}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr}.kpi-grid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<header class="hdr">
  <div>
    <h1>NDCI — Qualidade da Água · Lagoas do Litoral Norte RS</h1>
    <div class="sub">Sentinel-2 / Google Earth Engine · ${lagoaAtiva ? 'Lagoa selecionada: ' + lagoaAtiva : 'Todas as lagoas'}</div>
  </div>
  <div class="meta">
    Exportado em<br><strong>${dataExport}</strong>
  </div>
</header>

<div class="page">

  <!-- KPIs -->
  <section class="card">
    <div class="section-label">Status atual por lagoa</div>
    <div class="kpi-grid">${kpiHtml}</div>
  </section>

  ${chartsHtml}

  ${analyticsHtml}

  <div class="footer">
    Gerado automaticamente pelo sistema NDCI/Sentinel-2 · Metodologia: Pi &amp; Guasselli (SBSR 2025)
    · Mann-Kendall Sazonal: Hirsch et al. (1982) · CUSUM: Page (1954)
  </div>
</div>
</body>
</html>`;
}

// ── Seção de gráficos ─────────────────────────────────────────────────────────

function _buildChartsSection() {
  const series    = _chartImg('chart-series',   'Série temporal NDCI');
  const indices   = _chartImg('chart-indices',  'Turbidez e NDWI');
  const compare   = _chartImg('chart-compare',  'Comparação entre lagoas');
  const seasonal  = _chartImg('chart-seasonal', 'Sazonalidade');
  const dist      = _chartImg('chart-dist',     'Distribuição por faixa');
  const scatter   = _chartImg('chart-scatter',  'Correlação NDCI × NDTI');

  const hasAny = [series, indices, compare, seasonal, dist, scatter].some(Boolean);
  if (!hasAny) return '';

  return `
  <section class="card">
    <div class="section-label" style="margin-bottom:16px">Série temporal — NDCI</div>
    ${series ? `<div class="chart-wrap">${series}</div>` : ''}
  </section>

  <div class="chart-grid">
    ${indices  ? `<div class="card"><div class="chart-label">Turbidez (NDTI) e Disponib. Hídrica (NDWI)</div><div class="chart-wrap">${indices}</div></div>`  : ''}
    ${compare  ? `<div class="card"><div class="chart-label">Comparação entre lagoas — NDCI</div><div class="chart-wrap">${compare}</div></div>`  : ''}
    ${seasonal ? `<div class="card"><div class="chart-label">Sazonalidade — NDCI médio por mês</div><div class="chart-wrap">${seasonal}</div></div>` : ''}
    ${dist     ? `<div class="card"><div class="chart-label">Distribuição por faixa de alerta</div><div class="chart-wrap">${dist}</div></div>`     : ''}
  </div>

  ${scatter ? `
  <section class="card">
    <div class="chart-label">NDCI × Turbidez (NDTI) — Correlação por lagoa</div>
    <div class="chart-wrap">${scatter}</div>
  </section>` : ''}`;
}

// ── Seção de análises estatísticas ────────────────────────────────────────────

function _buildAnalyticsSection() {
  const mkCards   = _cloneHtml('mk-cards');
  const alarms    = _cloneHtml('cusum-alarms');
  const cusumSeries = _chartImg('cusum-series-chart', 'CUSUM série');
  const cusumStat   = _chartImg('cusum-stat-chart',   'CUSUM estatística');

  const hasMK    = mkCards && !mkCards.includes('analytics-empty');
  const hasCusum = cusumSeries || cusumStat || alarms;
  if (!hasMK && !hasCusum) return '';

  return `
  <section class="card">
    <div class="card-title" style="margin-bottom:4px">Tendências de Longo Prazo — Mann-Kendall Sazonal</div>
    <p class="analytics-ref">Hirsch et al. (1982) · Sen (1968) · α = 0.05 · dados mensais 2017–atual</p>
    ${hasMK ? `<div class="mk-cards-grid">${mkCards}</div>` : '<p class="analytics-empty">Aba Tendências não foi carregada nesta sessão.</p>'}
  </section>

  ${hasCusum ? `
  <section class="card">
    <div class="card-title" style="margin-bottom:4px">Detecção de Quebra de Regime — CUSUM</div>
    <p class="analytics-ref">Page (1954) · k = 0.5σ · h = 4σ · linha de base: primeiros 24 obs.</p>
    ${cusumSeries ? `<div class="chart-wrap" style="margin-bottom:8px">${cusumSeries}</div>` : ''}
    ${cusumStat   ? `<div class="chart-wrap">${cusumStat}</div>` : ''}
    ${alarms ? `<div style="margin-top:12px">${alarms}</div>` : ''}
  </section>` : ''}`;
}

// ── Export principal ──────────────────────────────────────────────────────────

export function exportHTML() {
  const now = new Date();
  const dataExport = now.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });

  const lagoaAtiva = document.getElementById('series-lagoa-tag')?.textContent?.trim()
    ?? document.getElementById('lagoa-select')?.value ?? '';

  const kpiHtml       = _cloneHtml('kpi-grid');
  const chartsHtml    = _buildChartsSection();
  const analyticsHtml = _buildAnalyticsSection();

  const html = _buildHtml({ lagoaAtiva, dataExport, kpiHtml, chartsHtml, analyticsHtml });

  const safeName = `ndci-lagoas-${now.toISOString().slice(0, 10)}`;
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `${safeName}.html`;
  a.click();
  URL.revokeObjectURL(url);
}
