/**
 * Adiciona botões de tela cheia e exportar PDF a todos os gráficos.
 * Chame initChartActions() após os gráficos serem renderizados.
 * A função é idempotente — pode ser chamada múltiplas vezes com segurança.
 */

let _fsListenerAdded = false;

export function initChartActions() {
  document.querySelectorAll('.card').forEach(card => {
    const header = card.querySelector('.chart-header');
    const canvas = card.querySelector('canvas');
    if (!header || !canvas) return;
    if (header.querySelector('.chart-actions')) return; // já inicializado

    const title = header.querySelector('.card-title')?.textContent?.trim() ?? 'grafico';
    const actions = document.createElement('div');
    actions.className = 'chart-actions';

    const btnFs = _makeBtn('fullscreen', 'Tela cheia', ICON_FULLSCREEN, () => {
      if (document.fullscreenElement === card) {
        document.exitFullscreen();
      } else {
        card.requestFullscreen().catch(e => console.warn('Fullscreen bloqueado:', e));
      }
    });

    const btnPdf = _makeBtn('export', 'Exportar PDF', ICON_DOWNLOAD, () => _exportPdf(canvas, title));

    actions.append(btnFs, btnPdf);

    const controls = header.querySelector('.chart-controls');
    if (controls) {
      const sep = document.createElement('span');
      sep.className = 'chart-actions-sep';
      controls.append(sep, actions);
    } else {
      const wrap = document.createElement('div');
      wrap.className = 'chart-controls';
      wrap.appendChild(actions);
      header.appendChild(wrap);
    }
  });

  if (!_fsListenerAdded) {
    document.addEventListener('fullscreenchange', _onFsChange);
    _fsListenerAdded = true;
  }
}

/* ── Internos ─────────────────────────────────────────────────────────────── */

function _makeBtn(action, title, icon, onClick) {
  const btn = document.createElement('button');
  btn.className = 'chart-action-btn';
  btn.dataset.action = action;
  btn.title = title;
  btn.innerHTML = icon;
  btn.addEventListener('click', onClick);
  return btn;
}

function _onFsChange() {
  document.querySelectorAll('[data-action="fullscreen"]').forEach(btn => {
    const isFs = document.fullscreenElement === btn.closest('.card');
    btn.innerHTML = isFs ? ICON_EXIT_FULLSCREEN : ICON_FULLSCREEN;
    btn.title = isFs ? 'Sair da tela cheia' : 'Tela cheia';
  });
}

function _exportPdf(canvas, title) {
  if (!window.jspdf?.jsPDF) {
    console.error('jsPDF não disponível — verifique o CDN no index.html');
    return;
  }
  const { jsPDF } = window.jspdf;

  // Chart.js usa canvas transparente — renderiza sobre fundo escuro
  const tmp = document.createElement('canvas');
  tmp.width  = canvas.width;
  tmp.height = canvas.height;
  const tCtx = tmp.getContext('2d');
  tCtx.fillStyle = '#161b22';
  tCtx.fillRect(0, 0, tmp.width, tmp.height);
  tCtx.drawImage(canvas, 0, 0);

  const imgData = tmp.toDataURL('image/png');
  const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
  const W = pdf.internal.pageSize.getWidth();
  const H = pdf.internal.pageSize.getHeight();
  const m = 14;

  pdf.setFontSize(10);
  pdf.setTextColor(180, 190, 200);
  pdf.text(title, m, m);

  const imgW = W - m * 2;
  const imgH = Math.min((canvas.height / canvas.width) * imgW, H - m * 2 - 8);
  pdf.addImage(imgData, 'PNG', m, m + 6, imgW, imgH);

  const safeName = title
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/gi, '_').toLowerCase();
  pdf.save(`${safeName}.pdf`);
}

/* ── Ícones SVG (stroke-based, fáceis de verificar) ──────────────────────── */

const ICON_FULLSCREEN = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true">
  <polyline points="5,1 1,1 1,5"/>
  <polyline points="11,1 15,1 15,5"/>
  <polyline points="1,11 1,15 5,15"/>
  <polyline points="15,11 15,15 11,15"/>
</svg>`;

const ICON_EXIT_FULLSCREEN = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true">
  <polyline points="1,5 5,5 5,1"/>
  <polyline points="15,5 11,5 11,1"/>
  <polyline points="1,11 5,11 5,15"/>
  <polyline points="15,11 11,11 11,15"/>
</svg>`;

const ICON_DOWNLOAD = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <line x1="8" y1="2" x2="8" y2="11"/>
  <polyline points="4,8 8,12 12,8"/>
  <line x1="2" y1="14" x2="14" y2="14"/>
</svg>`;
