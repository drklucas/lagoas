/**
 * Utilitários: classificação, formatação, cores.
 */

export const THRESHOLDS = [
  { upper: 0.02,       status: 'bom',      label: 'Bom',      color: '#3fb950' },
  { upper: 0.10,       status: 'moderado', label: 'Moderado', color: '#d29922' },
  { upper: 0.20,       status: 'elevado',  label: 'Elevado',  color: '#f85149' },
  { upper: Infinity,   status: 'critico',  label: 'Crítico',  color: '#b91c1c' },
];

export function classifyNdci(v) {
  if (v == null) return { status: 'sem_dados', label: 'Sem dados', color: '#484f58' };
  return THRESHOLDS.find(t => v < t.upper) ?? THRESHOLDS.at(-1);
}

export function fmtNdci(v) {
  return v == null ? '—' : v.toFixed(4);
}

export function fmtNum(v, dec = 3) {
  return v == null ? '—' : v.toFixed(dec);
}

/** Agrupa array de valores por mês (1-12) — retorna médias mensais */
export function seasonalMeans(periodos, values) {
  const buckets = Array.from({ length: 12 }, () => []);
  periodos.forEach((p, i) => {
    const mes = parseInt(p.slice(5, 7), 10);
    if (values[i] != null) buckets[mes - 1].push(values[i]);
  });
  return buckets.map(b => b.length ? b.reduce((a, x) => a + x, 0) / b.length : null);
}

/** Cores Chart.js com alpha */
export function rgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Cor fixa por lagoa — garante consistência entre todos os gráficos. */
export const LAGOA_COLORS = {
  'Lagoa do Peixoto':   '#2188ff',   // azul
  'Lagoa dos Barros':   '#3fb950',   // verde
  'Lagoa de Tramandaí': '#d29922',   // âmbar
  'Lagoa do Armazém':   '#f85149',   // vermelho
  'Lagoa Itapeva':      '#a371f7',   // violeta
  'Lagoa dos Quadros':  '#79c0ff',   // azul-claro
  'Lagoa Caconde':      '#ffa657',   // laranja
};

/** Retorna a cor fixa da lagoa; cai no fallback se não mapeada. */
const PALETTE_FALLBACK = [
  '#2188ff', '#3fb950', '#d29922', '#f85149',
  '#a371f7', '#79c0ff', '#56d364', '#ffa657',
];
export function lagoaColor(nome, fallbackIndex = 0) {
  return LAGOA_COLORS[nome] ?? PALETTE_FALLBACK[fallbackIndex % PALETTE_FALLBACK.length];
}

/** @deprecated Use lagoaColor() em vez de indexar PALETTE diretamente. */
export const PALETTE = PALETTE_FALLBACK;
