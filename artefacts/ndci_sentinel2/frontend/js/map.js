/**
 * map.js — aba Mapa com tiles XYZ do GEE via Leaflet.
 *
 * Deps externas (CDN, carregadas antes deste módulo):
 *   window.L  ← leaflet@1.9
 */

import { getTileAvailability, getTileLagoa } from './api.js';
import { initRegions } from './regions.js';

// Estado interno
let _map       = null;
let _tileLayer = null;
let _avail     = {};   // index_key → { lagoas, periodos_mensais, ... }
let _ready     = false;

// ── Entry point ────────────────────────────────────────────────────────────────
export async function initMap() {
  if (_ready) {
    // Já iniciado: força resize pois o container estava oculto (display:none)
    setTimeout(() => _map?.invalidateSize(), 50);
    return;
  }
  _ready = true;

  // ── Leaflet map ──
  _map = L.map('map-container', {
    center: [-29.65, -50.15],   // Litoral Norte RS
    zoom: 10,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
    opacity: 0.55,
  }).addTo(_map);

  // ── Regiões desenhadas (painel lateral) ──
  initRegions(_map);

  // ── Carrega disponibilidade de tiles ──
  try {
    _avail = await getTileAvailability();
  } catch {
    _showStatus('Tiles disponíveis apenas com a API rodando localmente.', true);
    return;
  }

  const indices = Object.keys(_avail);
  if (!indices.length) {
    _showStatus('Nenhum tile gerado ainda. Execute POST /api/workers/generate-tiles.', true);
    return;
  }

  _populateIndexSelect(indices);
  _onIndexChange();   // popula lagoa + período com base no índice padrão
  _bindControls();
}

// ── Controles ──────────────────────────────────────────────────────────────────

function _populateIndexSelect(indices) {
  const sel = document.getElementById('map-index');
  if (!sel) return;
  const LABELS = {
    ndci: 'NDCI — Clorofila',
    ndti: 'NDTI — Turbidez',
    ndwi: 'NDWI — Disponib. Hídrica',
  };
  sel.innerHTML = indices
    .map(k => `<option value="${k}">${LABELS[k] ?? k.toUpperCase()}</option>`)
    .join('');
}

function _onIndexChange() {
  const idx  = _selVal('map-index');
  const info = _avail[idx];
  if (!info) return;

  // Repopula lagoas para este índice
  const lagoaSel = document.getElementById('map-lagoa');
  if (lagoaSel) {
    lagoaSel.innerHTML = (info.lagoas ?? [])
      .sort()
      .map(l => `<option value="${l}">${l}</option>`)
      .join('');
  }

  _onLagoaChange();
}

function _onLagoaChange() {
  const idx   = _selVal('map-index');
  const lagoa = _selVal('map-lagoa');
  const info  = _avail[idx];
  if (!info) return;

  // Datas para a lagoa selecionada, mais recente primeiro
  const datas = (info.datas_por_lagoa?.[lagoa] ?? []).slice().sort().reverse();

  const perSel = document.getElementById('map-period');
  if (perSel) {
    // Agrupa por ano-mês para facilitar navegação (optgroup)
    const grupos = {};
    for (const d of datas) {
      const ym = d.slice(0, 7);   // "YYYY-MM"
      if (!grupos[ym]) grupos[ym] = [];
      grupos[ym].push(d);
    }
    perSel.innerHTML = Object.entries(grupos)
      .map(([ym, ds]) =>
        `<optgroup label="${ym}">` +
        ds.map(d => `<option value="${d}">${d}</option>`).join('') +
        `</optgroup>`
      )
      .join('');
  }

  _loadTile();
}

function _bindControls() {
  document.getElementById('map-index')?.addEventListener('change',  _onIndexChange);
  document.getElementById('map-lagoa')?.addEventListener('change',  _onLagoaChange);
  document.getElementById('map-period')?.addEventListener('change', _loadTile);
}

// ── Tile loading ───────────────────────────────────────────────────────────────

async function _loadTile() {
  const idx   = _selVal('map-index');
  const lagoa = _selVal('map-lagoa');
  const data  = _selVal('map-period');   // YYYY-MM-DD
  if (!idx || !lagoa || !data) return;

  _showStatus('Carregando…');

  try {
    const tile = await getTileLagoa(idx, lagoa, data);

    // Troca camada
    if (_tileLayer) { _map.removeLayer(_tileLayer); _tileLayer = null; }

    _tileLayer = L.tileLayer(tile.tile_url, {
      opacity: 0.88,
      maxZoom: 14,
      tms: false,
      attribution: 'Google Earth Engine / Sentinel-2',
    }).addTo(_map);

    // Encaixa mapa na lagoa [west, south, east, north]
    if (Array.isArray(tile.bounds) && tile.bounds.length === 4) {
      const [w, s, e, n] = tile.bounds;
      _map.fitBounds([[s, w], [n, e]], { padding: [36, 36], maxZoom: 13 });
    }

    _renderLegend(tile, idx);
    _showStatus('');
  } catch {
    _showStatus(`Tile não encontrado para ${lagoa} ${data}.`, true);
    if (_tileLayer) { _map.removeLayer(_tileLayer); _tileLayer = null; }
    _hideLegend();
  }
}

// ── Legenda ────────────────────────────────────────────────────────────────────

function _renderLegend(tile, idx) {
  const wrap = document.getElementById('map-legend');
  if (!wrap) return;

  const palette  = Array.isArray(tile.palette) && tile.palette.length
    ? tile.palette : ['#1a237e', '#42a5f5', '#a5d6a7', '#fff176', '#ef5350', '#b71c1c'];
  const min = tile.vis_min ?? 0;
  const max = tile.vis_max ?? 0.5;
  const mid = ((min + max) / 2).toFixed(3);
  const gradient = palette.join(', ');

  const LABELS = { ndci: 'NDCI', ndti: 'NDTI', ndwi: 'NDWI' };
  const label = LABELS[idx] ?? idx.toUpperCase();

  wrap.innerHTML = `
    <div class="ml-title">${label}</div>
    <div class="ml-bar" style="background:linear-gradient(to right,${gradient})"></div>
    <div class="ml-ticks">
      <span>${min.toFixed(3)}</span>
      <span>${mid}</span>
      <span>${max.toFixed(3)}</span>
    </div>
  `;
  wrap.style.display = 'block';
}

function _hideLegend() {
  const wrap = document.getElementById('map-legend');
  if (wrap) wrap.style.display = 'none';
}

// ── Status overlay ─────────────────────────────────────────────────────────────

function _showStatus(msg, isError = false) {
  const el = document.getElementById('map-status-msg');
  if (!el) return;
  el.textContent  = msg;
  el.style.display = msg ? 'block' : 'none';
  el.className = 'map-status-msg' + (isError ? ' map-status-error' : '');
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const _selVal = id => document.getElementById(id)?.value ?? '';
