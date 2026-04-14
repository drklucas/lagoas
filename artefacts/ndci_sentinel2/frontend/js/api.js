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

/** Retorna { "Lagoa X": { periodo, ndci_mean, status, ... } } */
export const getCurrentStatus = () =>
  fetchJSON('/api/water-quality/current');

/** Retorna { lagoas: ["Lagoa do Peixoto", ...] } */
export const getLagoas = () =>
  fetchJSON('/api/water-quality/lagoas');

/** Retorna { water_quality: { total_records, lagoas_com_dados }, map_tiles: { ... } } */
export const getWorkerStatus = () =>
  fetchJSON('/api/workers/status');
