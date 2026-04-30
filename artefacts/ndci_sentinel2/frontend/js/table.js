/**
 * DataTable — tabela com filtros múltiplos, ordenação e paginação.
 *
 * Auto-conecta aos elementos fixos do HTML:
 *   #table-body, #table-head, #record-count, #pg-info, #pagination
 *   #table-search, #filter-lagoa, #filter-status, #filter-zona
 *   #filter-ano-de, #filter-ano-ate, #page-size, #clear-filters
 *
 * Callback externo (gerenciado pelo app.js):
 *   this.onZonaChange(zona) — chamado quando o filtro de zona muda.
 *   O chamador é responsável por buscar novos dados e chamar load() novamente.
 */

import { classifyNdci, fmtNdci, fmtNum } from './utils.js';

export class DataTable {
  constructor() {
    this._tbody      = document.getElementById('table-body');
    this._countBadge = document.getElementById('record-count');
    this._pgInfo     = document.getElementById('pg-info');
    this._pgContainer = document.getElementById('pagination');

    this._rows         = [];   // todos os registros
    this._filteredRows = [];   // após filtros + ordenação

    this._sort    = { key: 'periodo', dir: 'desc' };
    this._page    = 1;
    this._pageSize = 25;

    this._filters = {
      search: '',
      lagoa:  '',
      status: '',
      anoMin: null,
      anoMax: null,
    };

    /** Callback externo: (zona: string) => void */
    this.onZonaChange = null;

    this._bindEvents();
  }

  // ── Carga de dados ──────────────────────────────────────────────────────────

  /** Carrega registros por imagem individual (fonte primária da tabela). */
  loadImages(allData, zona = 'total') {
    this._rows = [];
    for (const [lagoa, d] of Object.entries(allData)) {
      (d.datas ?? []).forEach((data, i) => {
        this._rows.push({
          lagoa,
          zona,
          data,
          ndci_mean: d.ndci_mean[i],
          ndci_p90:  d.ndci_p90?.[i]  ?? null,
          ndci_p10:  d.ndci_p10?.[i]  ?? null,
          turbidez:  d.ndti_mean?.[i] ?? null,
          ndwi_mean: d.ndwi_mean?.[i] ?? null,
          n_pixels:  d.n_pixels?.[i]  ?? null,
          cloud_pct: d.cloud_pct?.[i] ?? null,
          status:    classifyNdci(d.ndci_mean[i]).status,
        });
      });
    }
    this._sort = { key: 'data', dir: 'desc' };
    this._populateLagoaFilter();
    this._applyFilters();
  }

  /** @deprecated use loadImages() — mantido para compatibilidade temporária */
  load(allData, zona = 'total') {
    this.loadImages(allData, zona);
  }

  /** Atualiza as opções do select #filter-zona com as zonas disponíveis. */
  setZonaOptions(zones) {
    const sel = document.getElementById('filter-zona');
    if (!sel) return;
    const current = sel.value;
    const LABELS = { total: 'Zona: total', margem: 'Margem', medio: 'Médio', nucleo: 'Núcleo' };
    sel.innerHTML = zones.map(z =>
      `<option value="${z}">${LABELS[z] ?? z}</option>`
    ).join('');
    if (zones.includes(current)) sel.value = current;
  }

  // ── Eventos ────────────────────────────────────────────────────────────────

  _bindEvents() {
    const on = (id, evt, fn) => document.getElementById(id)?.addEventListener(evt, fn);

    on('table-search', 'input', e => {
      this._filters.search = e.target.value.toLowerCase().trim();
      this._applyFilters();
    });
    on('filter-lagoa', 'change', e => {
      this._filters.lagoa = e.target.value;
      this._applyFilters();
    });
    on('filter-status', 'change', e => {
      this._filters.status = e.target.value;
      this._applyFilters();
    });
    on('filter-zona', 'change', e => {
      // zona muda a fonte de dados — delega ao app.js via callback
      this.onZonaChange?.(e.target.value);
    });
    on('filter-ano-de', 'input', e => {
      this._filters.anoMin = e.target.value ? parseInt(e.target.value) : null;
      this._applyFilters();
    });
    on('filter-ano-ate', 'input', e => {
      this._filters.anoMax = e.target.value ? parseInt(e.target.value) : null;
      this._applyFilters();
    });
    on('page-size', 'change', e => {
      this._pageSize = parseInt(e.target.value);
      this._page = 1;
      this._render();
    });
    on('clear-filters', 'click', () => this._clearFilters());
    on('export-csv',    'click', () => this._exportCsv());
    on('table-head', 'click', e => {
      const col = e.target.closest('th')?.dataset.col;
      if (col) this._setSort(col);
    });
  }

  // ── Filtros ────────────────────────────────────────────────────────────────

  _populateLagoaFilter() {
    const sel = document.getElementById('filter-lagoa');
    if (!sel) return;
    const lagoas = [...new Set(this._rows.map(r => r.lagoa))].sort();
    sel.innerHTML = '<option value="">Todas as lagoas</option>' +
      lagoas.map(l => `<option value="${l}">${l}</option>`).join('');
  }

  _clearFilters() {
    this._filters = { search: '', lagoa: '', status: '', anoMin: null, anoMax: null };
    ['table-search', 'filter-lagoa', 'filter-status', 'filter-ano-de', 'filter-ano-ate']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    // Reseta zona para 'total' via callback (recarrega dados)
    const zonaSel = document.getElementById('filter-zona');
    if (zonaSel && zonaSel.value !== 'total') {
      zonaSel.value = 'total';
      this.onZonaChange?.('total');
    } else {
      this._applyFilters();
    }
  }

  _applyFilters() {
    const { search, lagoa, status, anoMin, anoMax } = this._filters;

    this._filteredRows = this._rows.filter(r => {
      if (lagoa  && r.lagoa  !== lagoa)  return false;
      if (status && r.status !== status) return false;

      if (anoMin !== null || anoMax !== null) {
        const ano = parseInt((r.data ?? '').substring(0, 4));
        if (anoMin !== null && ano < anoMin) return false;
        if (anoMax !== null && ano > anoMax) return false;
      }

      if (search) {
        return (
          r.lagoa.toLowerCase().includes(search) ||
          (r.data ?? '').includes(search)         ||
          r.status.includes(search)               ||
          r.zona.toLowerCase().includes(search)
        );
      }
      return true;
    });

    this._page = 1;
    this._applySort();
  }

  // ── Ordenação ──────────────────────────────────────────────────────────────

  _setSort(key) {
    this._sort = this._sort.key === key
      ? { key, dir: this._sort.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'asc' };
    this._updateSortHeaders();
    this._applySort();
  }

  _applySort() {
    const { key, dir } = this._sort;
    this._filteredRows.sort((a, b) => {
      const va = a[key] ?? (dir === 'asc' ? Infinity : -Infinity);
      const vb = b[key] ?? (dir === 'asc' ? Infinity : -Infinity);
      const cmp = typeof va === 'string' ? va.localeCompare(vb) : va - vb;
      return dir === 'asc' ? cmp : -cmp;
    });
    this._render();
  }

  _updateSortHeaders() {
    document.querySelectorAll('thead th[data-col]').forEach(th => {
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.col === this._sort.key) {
        th.classList.add(this._sort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
      }
    });
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  _render() {
    const total = this._filteredRows.length;
    const start = (this._page - 1) * this._pageSize;
    const end   = Math.min(start + this._pageSize, total);
    const page  = this._filteredRows.slice(start, end);

    // Rows
    if (page.length === 0) {
      this._tbody.innerHTML = `
        <tr class="table-empty-row">
          <td colspan="8">Nenhum registro encontrado para os filtros aplicados.</td>
        </tr>`;
    } else {
      this._tbody.innerHTML = page.map(r => `
        <tr>
          <td>${r.lagoa}</td>
          <td><span class="zona-badge${r.zona === 'total' ? ' zona-total' : ''}">${r.zona}</span></td>
          <td class="td-date">${r.data ?? '—'}</td>
          <td>${fmtNdci(r.ndci_mean)}</td>
          <td class="${r.ndci_p90 == null ? 'null' : ''}">${fmtNdci(r.ndci_p90)}</td>
          <td class="${r.ndci_p10 == null ? 'null' : ''}">${fmtNdci(r.ndci_p10)}</td>
          <td>${fmtNum(r.turbidez, 4)}</td>
          <td>${fmtNum(r.ndwi_mean, 4)}</td>
          <td>${r.n_pixels?.toLocaleString() ?? '<span class="null">—</span>'}</td>
          <td class="${r.cloud_pct == null ? 'null' : ''}">${r.cloud_pct != null ? r.cloud_pct.toFixed(1) + '%' : '—'}</td>
          <td><span class="badge badge-${r.status}">${r.status.replace('_', ' ')}</span></td>
        </tr>`).join('');
    }

    // Count badge
    if (this._countBadge) {
      const all = this._rows.length;
      this._countBadge.textContent = total < all
        ? `${total.toLocaleString()} de ${all.toLocaleString()} registros`
        : `${all.toLocaleString()} registros`;
    }

    // Pagination info + controls
    const s = start + 1, e = end;
    if (this._pgInfo) {
      this._pgInfo.textContent = total > 0 ? `${s}–${e} de ${total.toLocaleString()}` : '';
    }
    this._renderPagination(total);
  }

  // ── Export CSV ─────────────────────────────────────────────────────────────

  _exportCsv() {
    const headers = ['Lagoa', 'Zona', 'Data', 'NDCI médio', 'NDCI P90', 'NDCI P10', 'Turbidez (NDTI)', 'NDWI', 'Pixels válidos', 'Nuvens (%)', 'Status'];
    const data    = this._filteredRows.map(r => [
      r.lagoa,
      r.zona,
      r.data       ?? '',
      r.ndci_mean  ?? '',
      r.ndci_p90   ?? '',
      r.ndci_p10   ?? '',
      r.turbidez   ?? '',
      r.ndwi_mean  ?? '',
      r.n_pixels   ?? '',
      r.cloud_pct  ?? '',
      r.status,
    ]);

    const esc  = v => `"${String(v).replace(/"/g, '""')}"`;
    const csv  = [headers, ...data].map(row => row.map(esc).join(',')).join('\r\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });

    const lagoa    = this._filters.lagoa ? `_${this._filters.lagoa.replace(/\s+/g, '-')}` : '';
    const filename = `ndci${lagoa}_${new Date().toISOString().slice(0, 10)}.csv`;

    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  _renderPagination(total) {
    if (!this._pgContainer) return;

    const totalPages = Math.ceil(total / this._pageSize);

    if (totalPages <= 1) {
      this._pgContainer.innerHTML = '';
      return;
    }

    const page = this._page;

    // Pages to show (always: 1, last, current ± 2)
    const visible = new Set(
      [1, totalPages, page, page - 1, page + 1, page - 2, page + 2]
        .filter(p => p >= 1 && p <= totalPages)
    );
    const sorted = [...visible].sort((a, b) => a - b);

    const mkBtn = (label, p, disabled = false, active = false) =>
      `<button class="pg-btn${active ? ' active' : ''}" data-page="${p}"${disabled ? ' disabled' : ''}>${label}</button>`;

    const parts = [];
    parts.push(mkBtn('«', 1,            page === 1));
    parts.push(mkBtn('‹', page - 1,     page === 1));

    let prev = 0;
    for (const p of sorted) {
      if (p - prev > 1) parts.push(`<span class="pg-ellipsis">…</span>`);
      parts.push(mkBtn(p, p, false, p === page));
      prev = p;
    }

    parts.push(mkBtn('›', page + 1,     page === totalPages));
    parts.push(mkBtn('»', totalPages,   page === totalPages));

    this._pgContainer.innerHTML = parts.join('');

    // Bind clicks
    this._pgContainer.querySelectorAll('.pg-btn:not(:disabled)').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = parseInt(btn.dataset.page);
        if (p !== this._page) {
          this._page = p;
          this._render();
          this._tbody.closest('.table-wrap')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    });
  }
}
