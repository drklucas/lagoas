/**
 * API client — thin fetch wrapper sobre os endpoints FastAPI.
 * Centraliza a base URL e o tratamento de erros.
 */

const API_BASE = '';   // mesma origem — servido pelo FastAPI

export async function fetchJSON(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
  return res.json();
}

/** Retorna { "Lagoa X": { periodos, ndci_mean, ndci_p90, turbidez, fai_mean, ndwi_mean, n_pixels } } */
export const getWaterQuality = (lagoa, zona = 'total') => {
  const params = new URLSearchParams({ zona });
  if (lagoa) params.set('lagoa', lagoa);
  return fetchJSON('/api/water-quality?' + params.toString());
};

/** Retorna { zones: ["total", "margem", "medio", "nucleo", ...] } */
export const getAvailableZones = () =>
  fetchJSON('/api/water-quality/zones/available');

/** Retorna { lagoa, datas, ndci_mean, ndci_p90, ndci_p10, n_pixels, cloud_pct, ... } */
export const getImageSeries = (lagoa, zona = 'total') =>
  fetchJSON(`/api/water-quality/${encodeURIComponent(lagoa)}/images?zona=${encodeURIComponent(zona)}`);

/** Retorna { "Lagoa X": { datas, ndci_mean, ndci_p90, ndci_p10, ndti_mean, ndwi_mean, n_pixels, cloud_pct } } */
export const getAllImageSeries = (lagoa, zona = 'total') => {
  const params = new URLSearchParams({ zona });
  if (lagoa) params.set('lagoa', lagoa);
  return fetchJSON('/api/water-quality/images?' + params.toString());
};

/** Retorna { "Lagoa X": { periodo, ndci_mean, status, ... } } */
export const getCurrentStatus = () =>
  fetchJSON('/api/water-quality/current');

/** Retorna { lagoas: ["Lagoa do Peixoto", ...] } */
export const getLagoas = () =>
  fetchJSON('/api/water-quality/lagoas');

/** Retorna { water_quality: { total_records, lagoas_com_dados }, map_tiles: { ... } } */
export const getWorkerStatus = () =>
  fetchJSON('/api/workers/status');

/** Retorna { ndci: { lagoas, datas_por_lagoa, total_tiles, tiles_validos }, ndti: … } */
export const getTileAvailability = () =>
  fetchJSON('/api/tiles/availability');

/** Retorna { lagoa, satellite, zonas: { margem: {...}, medio: {...}, nucleo: {...} } } */
export const getZoneSeries = (lagoa) =>
  fetchJSON(`/api/water-quality/${encodeURIComponent(lagoa)}/zones`);

/** Retorna { tile_url, bounds, vis_min, vis_max, palette, valid, data, … }
 *  @param {string} data - data no formato YYYY-MM-DD */
export const getTileLagoa = (indexKey, lagoa, data) =>
  fetchJSON(`/api/tiles/lagoa/${encodeURIComponent(indexKey)}?lagoa=${encodeURIComponent(lagoa)}&data=${data}`);

/** Retorna { "Lagoa X": { periodos, ndvi_mean, ndvi_p90, ndvi_p10, n_pixels } } */
export const getVegetation = (lagoa) =>
  fetchJSON('/api/vegetation' + (lagoa ? `?lagoa=${encodeURIComponent(lagoa)}` : ''));

/** Retorna { lagoa, satellite, n_images, datas, ndvi_mean, ndvi_p90, ndvi_p10, n_pixels, cloud_pct } */
export const getVegetationImages = (lagoa) =>
  fetchJSON(`/api/vegetation/${encodeURIComponent(lagoa)}/images`);

/** Retorna { lagoas: ["Lagoa dos Barros", ...] } — todas as lagoas do config */
export const getAllLagoas = () =>
  fetchJSON('/api/regions/lagoas');

/** Retorna lista de regiões, filtrada opcionalmente por lagoa */
export const getRegions = (lagoa) =>
  fetchJSON('/api/regions' + (lagoa ? `?lagoa=${encodeURIComponent(lagoa)}` : ''));

/** Cria uma nova região. payload: { nome, descricao, polygon, lagoa, categoria, ativo } */
export async function createRegion(payload) {
  const res = await fetch('/api/regions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Atualiza campos de uma região existente */
export async function updateRegion(id, payload) {
  const res = await fetch(`/api/regions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Remove uma região */
export async function deleteRegion(id) {
  const res = await fetch(`/api/regions/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}
