"""
build_static.py — exporta dados da API e monta o site estático para GitHub Pages.

Uso:
  python scripts/build_static.py                  # apenas gera dist/
  python scripts/build_static.py --deploy         # gera e publica no gh-pages
  python scripts/build_static.py --api http://localhost:8001 --out dist --deploy

Pre-requisito: API rodando localmente (docker compose up -d).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # raiz do projeto ndci_sentinel2


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    name = name.lower()
    for src, dst in [
        ('aáâãä', 'a'), ('eéêë', 'e'), ('iíîï', 'i'),
        ('oóôõö', 'o'), ('uúûü', 'u'), ('c', 'c'),
    ]:
        for ch in src:
            name = name.replace(ch, dst)
    return re.sub(r'[^a-z0-9]+', '-', name).strip('-')


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    print(f"  OK {path.relative_to(path.parent.parent)}")


def run(cmd: list[str], cwd=None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  OK {dst.name}/")


# ── Build ─────────────────────────────────────────────────────────────────────

def build(api: str, out: Path) -> dict:
    """Gera o site estático em `out/`. Retorna o dict de meta."""

    print(f"\n{'='*54}")
    print(f"  Build  ->  {out}/")
    print(f"  API    ->  {api}")
    print(f"{'='*54}\n")

    # 1. Busca dados da API
    print("Buscando dados da API...")
    try:
        water_quality = fetch(f"{api}/api/water-quality")
    except Exception as e:
        print(f"\nERRO: nao foi possivel conectar a API em {api}\n  {e}", file=sys.stderr)
        sys.exit(1)

    current       = fetch(f"{api}/api/water-quality/current")
    worker_status = fetch(f"{api}/api/workers/status")
    lagoas        = sorted(water_quality.keys())
    print(f"  {len(lagoas)} lagoas: {', '.join(lagoas)}\n")

    images: dict[str, dict] = {}
    print("Buscando series por imagem...")
    for lagoa in lagoas:
        url = f"{api}/api/water-quality/{urllib.parse.quote(lagoa)}/images"
        try:
            images[lagoa] = fetch(url)
            print(f"  {lagoa}: {images[lagoa].get('n_images', '?')} imagens")
        except Exception:
            print(f"  {lagoa}: sem serie por imagem (ignorado)")

    _ANALYTICS_INDICES = ['ndci', 'ndti', 'ndwi', 'fai']
    analytics_trend:       dict[str, dict] = {}
    analytics_changepoint: dict[str, dict] = {}

    print("\nBuscando analises estatisticas (Mann-Kendall + CUSUM)...")
    for lagoa in lagoas:
        slug = slugify(lagoa)
        enc  = urllib.parse.quote(lagoa)

        try:
            analytics_trend[lagoa] = fetch(f"{api}/api/analytics/{enc}/trend")
            print(f"  {lagoa}: trend OK")
        except Exception as e:
            print(f"  {lagoa}: trend erro ({e})")

        for idx in _ANALYTICS_INDICES:
            for use_img in ('true', 'false'):
                key = f"{slug}/{idx}/{use_img}"
                url = (
                    f"{api}/api/analytics/{enc}/changepoint"
                    f"?index={idx}&use_images={use_img}"
                )
                try:
                    analytics_changepoint[key] = fetch(url)
                except Exception as e:
                    print(f"  {lagoa}/{idx}/use_images={use_img}: changepoint erro ({e})")

    # 2. Escreve JSONs
    print("\nEscrevendo data/...")
    write_json(out / 'data' / 'water_quality.json', water_quality)
    write_json(out / 'data' / 'current.json', current)
    for lagoa, series in images.items():
        write_json(out / 'data' / 'images' / f"{slugify(lagoa)}.json", series)
    write_json(out / 'data' / 'slugs.json', {lg: slugify(lg) for lg in lagoas})

    for lagoa, trend in analytics_trend.items():
        write_json(out / 'data' / 'analytics' / slugify(lagoa) / 'trend.json', trend)
    for key, cp in analytics_changepoint.items():
        slug, idx, use_img = key.split('/')
        write_json(
            out / 'data' / 'analytics' / slug / f'changepoint-{idx}-{use_img}.json',
            cp,
        )

    total_records = sum(len(v.get('periodos', [])) for v in water_quality.values())
    meta = {
        "generated_at":     datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "lagoas":           lagoas,
        "total_records":    total_records,
        "lagoas_com_dados": len(lagoas),
        "worker_status":    worker_status,
    }
    write_json(out / 'data' / 'meta.json', meta)

    # 3. Copia assets do frontend
    print("\nCopiando frontend...")
    frontend = ROOT / 'frontend'
    _copy_dir(frontend / 'css', out / 'css')

    (out / 'js').mkdir(parents=True, exist_ok=True)
    for f in (frontend / 'js').iterdir():
        if f.name not in ('api.js', 'api.static.js'):
            shutil.copy2(f, out / 'js' / f.name)
            print(f"  OK js/{f.name}")

    static_api = frontend / 'js' / 'api.static.js'
    if not static_api.exists():
        print("\nERRO: frontend/js/api.static.js nao encontrado.", file=sys.stderr)
        sys.exit(1)
    shutil.copy2(static_api, out / 'js' / 'api.js')
    print("  OK js/api.js  (versao estatica)")

    html = (frontend / 'index.html').read_text(encoding='utf-8')
    html = html.replace('href="/static/css/', 'href="./css/')
    html = html.replace('src="/static/js/',   'src="./js/')
    (out / 'index.html').write_text(html, encoding='utf-8')
    print("  OK index.html")

    (out / '.nojekyll').touch()
    print("  OK .nojekyll")

    print(f"\n{'='*54}")
    print(f"  Build concluido -> {out}/")
    print(f"  {len(lagoas)} lagoas | {total_records} registros mensais")
    print(f"  Gerado em: {meta['generated_at']}")
    print(f"{'='*54}\n")

    return meta


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy(out: Path, meta: dict) -> None:
    """Publica o conteudo de `out/` na branch gh-pages via git worktree."""

    print("Iniciando deploy para gh-pages...\n")

    # Descobre a raiz do repositorio git (pode ser diferente de ROOT)
    try:
        git_root = Path(run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT))
    except RuntimeError as e:
        print(f"ERRO: repositorio git nao encontrado.\n  {e}", file=sys.stderr)
        sys.exit(1)

    remote = run(['git', 'remote', 'get-url', 'origin'], cwd=git_root)
    print(f"  Remote: {remote}")

    worktree = Path(tempfile.mkdtemp(prefix='gh-pages-'))
    print(f"  Worktree: {worktree}\n")

    try:
        # Cria worktree: usa branch existente ou cria orphan
        existing = run(['git', 'branch', '--list', 'gh-pages'], cwd=git_root)
        if existing:
            run(['git', 'worktree', 'add', str(worktree), 'gh-pages'], cwd=git_root)
            # Limpa conteudo anterior mantendo o .git
            for item in worktree.iterdir():
                if item.name == '.git':
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        else:
            run(['git', 'worktree', 'add', '--orphan', '-b', 'gh-pages', str(worktree)], cwd=git_root)

        # Copia dist para o worktree
        shutil.copytree(out, worktree, dirs_exist_ok=True)

        # Commit
        msg = (
            f"deploy: {meta['generated_at']} | "
            f"{meta['lagoas_com_dados']} lagoas | "
            f"{meta['total_records']} registros"
        )
        run(['git', 'add', '-A'], cwd=worktree)

        try:
            run(['git', 'commit', '-m', msg], cwd=worktree)
        except RuntimeError:
            print("  Nenhuma alteracao — deploy ignorado (conteudo identico ao anterior).")
            return

        # Push
        print(f"  Commit: {msg}")
        run(['git', 'push', '-f', 'origin', 'gh-pages'], cwd=worktree)
        print("\n  Deploy concluido!")
        print(f"  Branch gh-pages atualizada em: {remote}")

    finally:
        run(['git', 'worktree', 'remove', '--force', str(worktree)], cwd=git_root)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build e deploy estatico NDCI")
    parser.add_argument('--api',    default='http://localhost:8001', help='URL base da API')
    parser.add_argument('--out',    default='dist',                  help='Pasta de saida')
    parser.add_argument('--deploy', action='store_true',             help='Publica no gh-pages apos o build')
    args = parser.parse_args()

    out  = Path(args.out)
    meta = build(api=args.api.rstrip('/'), out=out)

    if args.deploy:
        deploy(out=out, meta=meta)
    else:
        print("Para publicar no GitHub Pages:")
        print(f"  python scripts/build_static.py --deploy")
        print(f"\nPara testar localmente:")
        print(f"  python -m http.server 3000 --directory {out}\n")


if __name__ == '__main__':
    main()
