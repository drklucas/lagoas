/**
 * regions.js — gerenciamento de regiões geográficas no mapa.
 *
 * Requer leaflet-draw (window.L.Draw) carregado antes deste módulo.
 * Coordenadas internas: [lon, lat] (ordem GEE). Leaflet usa [lat, lng].
 */

import { getAllLagoas, getRegions, createRegion, updateRegion, deleteRegion } from './api.js';

// Cores por categoria
const CAT_COLORS = {
  setor_lagoa:  '#58a6ff',
  area_estudo:  '#3fb950',
  bacia:        '#f7931a',
  default:      '#8b949e',
};

const CAT_LABELS = {
  setor_lagoa: 'Setor da lagoa',
  area_estudo: 'Área de estudo',
  bacia:       'Bacia hidrográfica',
};

let _map           = null;
let _featureGroup  = null;   // overlays de regiões no mapa
let _drawHandler   = null;   // leaflet-draw polygon handler ativo
let _pendingLayer  = null;   // polígono desenhado aguardando formulário
let _currentLagoa  = null;

// ── Entry point ────────────────────────────────────────────────────────────────

export function initRegions(map) {
  _map = map;

  _featureGroup = new L.FeatureGroup();
  _map.addLayer(_featureGroup);

  // Evento disparado quando o usuário termina de desenhar o polígono
  _map.on(L.Draw.Event.CREATED, _onDrawCreated);

  document.getElementById('regions-toggle-btn')
    ?.addEventListener('click', _togglePanel);
  document.getElementById('regions-panel-close')
    ?.addEventListener('click', _closePanel);
  document.getElementById('regions-lagoa-select')
    ?.addEventListener('change', e => {
      _currentLagoa = e.target.value || null;
      _loadRegions();
    });
  document.getElementById('draw-region-btn')
    ?.addEventListener('click', _startDraw);
  document.getElementById('save-region-btn')
    ?.addEventListener('click', _saveRegion);
  document.getElementById('cancel-draw-btn')
    ?.addEventListener('click', _cancelDraw);
}

// ── Painel ─────────────────────────────────────────────────────────────────────

function _togglePanel() {
  const panel = document.getElementById('regions-panel');
  if (!panel) return;
  const opening = !panel.classList.contains('open');
  panel.classList.toggle('open', opening);
  document.getElementById('regions-toggle-btn')?.classList.toggle('active', opening);
  if (opening) _syncLagoaAndLoad();
}

function _closePanel() {
  _cancelDraw();
  document.getElementById('regions-panel')?.classList.remove('open');
  document.getElementById('regions-toggle-btn')?.classList.remove('active');
}

async function _syncLagoaAndLoad() {
  const sel = document.getElementById('regions-lagoa-select');
  if (!sel) return;

  // Popula select a partir do endpoint de config (todas as lagoas)
  try {
    const { lagoas } = await getAllLagoas();
    sel.innerHTML = '<option value="">— selecione —</option>' +
      lagoas.map(l => `<option value="${l}">${l}</option>`).join('');
  } catch {
    // Fallback: copia opções do select do mapa
    const mapSel = document.getElementById('map-lagoa');
    if (mapSel?.options.length > 1) {
      sel.innerHTML = '<option value="">— selecione —</option>' + mapSel.innerHTML;
    }
  }

  // Sincroniza com a lagoa selecionada no mapa
  const mapLagoa = document.getElementById('map-lagoa')?.value;
  if (mapLagoa) sel.value = mapLagoa;
  _currentLagoa = sel.value || null;
  await _loadRegions();
}

// ── Carregamento e renderização ────────────────────────────────────────────────

async function _loadRegions() {
  _featureGroup.clearLayers();
  const list = document.getElementById('regions-list');
  if (!list) return;

  if (!_currentLagoa) {
    list.innerHTML = '<p class="regions-empty">Selecione uma lagoa para ver suas regiões.</p>';
    return;
  }

  list.innerHTML = '<p class="regions-loading">Carregando…</p>';

  try {
    const regions = await getRegions(_currentLagoa);
    _renderList(regions);
    _renderOverlays(regions);
  } catch {
    list.innerHTML = '<p class="regions-error">Erro ao carregar regiões.</p>';
  }
}

function _renderList(regions) {
  const list = document.getElementById('regions-list');
  if (!list) return;

  if (!regions.length) {
    list.innerHTML = '<p class="regions-empty">Nenhuma região definida para esta lagoa.<br>Clique em "Desenhar região" para começar.</p>';
    return;
  }

  list.innerHTML = regions.map(r => {
    const color = CAT_COLORS[r.categoria] ?? CAT_COLORS.default;
    const label = CAT_LABELS[r.categoria] ?? r.categoria;
    return `
      <div class="region-item ${r.ativo ? '' : 'region-item--inactive'}" data-id="${r.id}">
        <span class="region-dot" style="background:${color}"></span>
        <div class="region-info">
          <span class="region-nome">${r.nome}</span>
          ${r.descricao ? `<span class="region-desc">${r.descricao}</span>` : ''}
          <span class="region-cat">${label}</span>
        </div>
        <div class="region-actions">
          <label class="region-toggle" title="${r.ativo ? 'Desativar' : 'Ativar'}">
            <input type="checkbox" class="region-ativo-chk" data-id="${r.id}" ${r.ativo ? 'checked' : ''} />
            <span class="region-toggle-track"><span class="region-toggle-thumb"></span></span>
          </label>
          <button class="btn-region-delete" data-id="${r.id}" title="Excluir">×</button>
        </div>
      </div>`;
  }).join('');

  list.querySelectorAll('.btn-region-delete').forEach(btn => {
    btn.addEventListener('click', async e => {
      const id = parseInt(e.currentTarget.dataset.id);
      if (!confirm('Excluir esta região permanentemente?')) return;
      try {
        await deleteRegion(id);
        await _loadRegions();
      } catch (err) {
        alert('Erro ao excluir: ' + err.message);
      }
    });
  });

  list.querySelectorAll('.region-ativo-chk').forEach(chk => {
    chk.addEventListener('change', async e => {
      const id    = parseInt(e.currentTarget.dataset.id);
      const ativo = e.currentTarget.checked;
      try {
        await updateRegion(id, { ativo });
        // Atualiza apenas a aparência sem recarregar tudo
        const item = list.querySelector(`.region-item[data-id="${id}"]`);
        item?.classList.toggle('region-item--inactive', !ativo);
        await _loadRegions();   // refresh overlays
      } catch (err) {
        alert('Erro ao atualizar: ' + err.message);
        e.currentTarget.checked = !ativo;   // reverte UI
      }
    });
  });
}

function _renderOverlays(regions) {
  _featureGroup.clearLayers();
  for (const r of regions) {
    if (!r.ativo || !r.polygon?.length) continue;
    const latlngs = r.polygon.map(([lon, lat]) => [lat, lon]);
    const color   = CAT_COLORS[r.categoria] ?? CAT_COLORS.default;
    const poly    = L.polygon(latlngs, {
      color,
      weight:      2,
      fillOpacity: 0.12,
      dashArray:   r.categoria === 'area_estudo' ? '5, 5' : null,
    });
    poly.bindTooltip(r.nome, { permanent: false, direction: 'center', className: 'region-tooltip' });
    _featureGroup.addLayer(poly);
  }
}

// ── Desenho ────────────────────────────────────────────────────────────────────

function _startDraw() {
  if (!window.L?.Draw) {
    alert('Plugin leaflet-draw não disponível.');
    return;
  }
  if (!_currentLagoa) {
    alert('Selecione uma lagoa antes de desenhar uma região.');
    return;
  }

  if (_drawHandler) { _drawHandler.disable(); _drawHandler = null; }

  _drawHandler = new L.Draw.Polygon(_map, {
    shapeOptions: { color: '#58a6ff', fillOpacity: 0.18, weight: 2 },
    showArea:     true,
    metric:       true,
  });
  _drawHandler.enable();

  _setDrawingState(true);
}

function _onDrawCreated(e) {
  if (_pendingLayer) _featureGroup.removeLayer(_pendingLayer);
  _pendingLayer = e.layer;
  _featureGroup.addLayer(_pendingLayer);
  _drawHandler = null;

  _showForm();
}

function _cancelDraw() {
  if (_drawHandler) { _drawHandler.disable(); _drawHandler = null; }
  if (_pendingLayer) { _featureGroup.removeLayer(_pendingLayer); _pendingLayer = null; }
  _setDrawingState(false);
  _hideForm();
}

async function _saveRegion() {
  const nome = document.getElementById('region-nome')?.value?.trim();
  if (!nome) {
    document.getElementById('region-nome')?.focus();
    return;
  }

  // Leaflet retorna array de LatLng → converter para [lon, lat] (GEE)
  const rawLatlngs = _pendingLayer.getLatLngs()[0];
  const polygon    = rawLatlngs.map(ll => [ll.lng, ll.lat]);
  // Fechar o anel se necessário
  const first = polygon[0], last = polygon[polygon.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) polygon.push(first);

  const payload = {
    nome,
    descricao:  document.getElementById('region-descricao')?.value?.trim() || null,
    polygon,
    lagoa:      _currentLagoa,
    categoria:  document.getElementById('region-categoria')?.value ?? 'setor_lagoa',
    ativo:      true,
  };

  const btn = document.getElementById('save-region-btn');
  if (btn) btn.disabled = true;

  try {
    await createRegion(payload);
    _pendingLayer = null;   // já está no featureGroup; será substituído no reload
    _hideForm();
    _setDrawingState(false);
    await _loadRegions();
  } catch (err) {
    alert('Erro ao salvar região: ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Helpers de estado UI ───────────────────────────────────────────────────────

function _showForm() {
  document.getElementById('regions-list').style.display = 'none';
  document.getElementById('regions-footer').style.display = 'none';
  document.getElementById('draw-form').style.display = 'flex';
  document.getElementById('region-nome').value = '';
  document.getElementById('region-descricao').value = '';
  document.getElementById('region-nome').focus();
}

function _hideForm() {
  document.getElementById('regions-list').style.display = '';
  document.getElementById('regions-footer').style.display = '';
  document.getElementById('draw-form').style.display = 'none';
}

function _setDrawingState(drawing) {
  const btn = document.getElementById('draw-region-btn');
  if (btn) btn.textContent = drawing ? 'Desenhando… (clique para cancelar)' : '+ Desenhar região';
  if (drawing) {
    btn?.addEventListener('click', _cancelDraw, { once: true });
  }
}
