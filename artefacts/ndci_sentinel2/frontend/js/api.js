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
export const getWaterQuality = (lagoa) =>
  fetchJSON('/api/water-quality' + (lagoa ? `?lagoa=${encodeURIComponent(lagoa)}` : ''));

/** Retorna { lagoa, datas, ndci_mean, ndci_p90, ndci_p10, n_pixels, cloud_pct, ... } */
export const getImageSeries = (lagoa) =>
  fetchJSON(`/api/water-quality/${encodeURIComponent(lagoa)}/images`);

/** Retorna { "Lagoa X": { periodo, ndci_mean, status, ... } } */
export const getCurrentStatus = () =>
  fetchJSON('/api/water-quality/current');

/** Retorna { lagoas: ["Lagoa do Peixoto", ...] } */
export const getLagoas = () =>
  fetchJSON('/api/water-quality/lagoas');

/** Retorna { water_quality: { total_records, lagoas_com_dados }, map_tiles: { ... } } */
export const getWorkerStatus = () =>
  fetchJSON('/api/workers/status');

/** Retorna { ndci: { lagoas, periodos_mensais, total_tiles, tiles_validos }, ndti: … } */
export const getTileAvailability = () =>
  fetchJSON('/api/tiles/availability');

/** Retorna { tile_url, bounds, vis_min, vis_max, palette, valid, … } */
export const getTileLagoa = (indexKey, lagoa, ano, mes) =>
  fetchJSON(`/api/tiles/lagoa/${encodeURIComponent(indexKey)}?lagoa=${encodeURIComponent(lagoa)}&ano=${ano}&mes=${mes}`);
