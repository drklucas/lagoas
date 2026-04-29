/**
 * API client — modo estático para GitHub Pages.
 * Carrega dados de arquivos JSON pré-gerados em ./data/
 * Interface idêntica a api.js — app.js não precisa saber a diferença.
 */

const DATA_BASE = './data';

async function _load(path) {
  const res = await fetch(DATA_BASE + path);
  if (!res.ok) throw new Error(`Arquivo não encontrado: ${DATA_BASE}${path}`);
  return res.json();
}

// Cache de slugs para não recarregar a cada chamada de getImageSeries
let _slugs = null;
async function _getSlug(lagoa) {
  if (!_slugs) _slugs = await _load('/slugs.json');
  return _slugs[lagoa] ?? lagoa.toLowerCase().replace(/\s+/g, '-');
}

/** { "Lagoa X": { periodos, ndci_mean, ndci_p90, turbidez, ... } } */
export const getWaterQuality = () => _load('/water_quality.json');

/** { lagoa, datas, ndci_mean, ndci_p90, ndci_p10, n_pixels, ... } */
export const getImageSeries = async (lagoa) => {
  const slug = await _getSlug(lagoa);
  return _load(`/images/${slug}.json`);
};

/** { "Lagoa X": { periodo, ndci_mean, status, ... } } */
export const getCurrentStatus = () => _load('/current.json');

/** { lagoas: [...] } */
export const getLagoas = async () => {
  const meta = await _load('/meta.json');
  return { lagoas: meta.lagoas };
};

/**
 * Em modo estático não há worker — retorna metadados do build.
 * O status bar mostrará "N registros · M lagoas (exportado em …)".
 */
export const getWorkerStatus = async () => {
  const meta = await _load('/meta.json');
  return {
    water_quality: {
      total_records:    meta.total_records,
      lagoas_com_dados: meta.lagoas_com_dados,
    },
    map_tiles: { total_tiles: 0 },
  };
};

/** Tiles não disponíveis em modo estático (requer proxy GEE). */
export const getTileAvailability = async () => { throw new Error('static'); };
export const getTileLagoa        = async () => { throw new Error('static'); };

/**
 * fetchJSON — compatível com analytics.js que importa esta função diretamente.
 * Mapeia as rotas de /api/analytics/* para os JSONs pré-gerados em data/analytics/.
 */
export async function fetchJSON(path) {
  if (!_slugs) _slugs = await _load('/slugs.json');

  // /api/analytics/{lagoa}/trend
  const trendMatch = path.match(/\/api\/analytics\/([^/?]+)\/trend/);
  if (trendMatch) {
    const lagoa = decodeURIComponent(trendMatch[1]);
    const slug  = _slugs[lagoa] ?? lagoa.toLowerCase().replace(/\s+/g, '-');
    return _load(`/analytics/${slug}/trend.json`);
  }

  // /api/analytics/{lagoa}/changepoint?index=X&use_images=Y
  const cpMatch = path.match(/\/api\/analytics\/([^/?]+)\/changepoint/);
  if (cpMatch) {
    const lagoa    = decodeURIComponent(cpMatch[1]);
    const slug     = _slugs[lagoa] ?? lagoa.toLowerCase().replace(/\s+/g, '-');
    const qs       = path.includes('?') ? path.split('?')[1] : '';
    const params   = new URLSearchParams(qs);
    const index    = params.get('index')     ?? 'ndci';
    const useImg   = params.get('use_images') ?? 'true';
    return _load(`/analytics/${slug}/changepoint-${index}-${useImg}.json`);
  }

  throw new Error(`fetchJSON não suportado em modo estático: ${path}`);
}
