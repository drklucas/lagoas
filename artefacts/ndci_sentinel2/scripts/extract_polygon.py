"""
Extrai o polígono de uma lagoa diretamente do GEE e imprime no formato
pronto para colar em config.py.

Uso (da raiz do projeto):
    python -m scripts.extract_polygon --nome "Lagoa Caconde" --lat -29.867 --lon -50.200

Fontes consultadas (em ordem de preferência):
  1. HydroLAKES — polígonos catalogados globalmente
  2. JRC Global Surface Water — vetorizado a partir de ocorrência de água >= 50%

Requer:
    GEE_SERVICE_ACCOUNT_KEY=credentials/gee-key.json  (ou ADC configurado)
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Permite rodar como `python -m scripts.extract_polygon` a partir da raiz
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.gee_auth import init_ee


def _buscar_hydrolakes(ponto, nome: str):
    import ee
    lakes = ee.FeatureCollection("projects/sat-io/open-datasets/HydroLakes/lake_poly_v10")
    resultado = lakes.filterBounds(ponto)
    n = resultado.size().getInfo()
    if n == 0:
        print(f"  [HydroLAKES] nenhum lago encontrado para '{nome}'")
        return None
    feat = resultado.first()
    geom = feat.geometry().simplify(maxError=30)
    coords = geom.coordinates().getInfo()
    print(f"  [HydroLAKES] encontrado! ({n} feição(ões))")
    return coords[0]  # anel externo


def _buscar_gsw(ponto, buffer_m: int = 5000):
    import ee
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    agua = gsw.gt(50).selfMask()
    regiao = ponto.buffer(buffer_m)
    vetores = agua.reduceToVectors(
        geometry=regiao,
        scale=30,
        geometryType="polygon",
        eightConnected=True,
        reducer=ee.Reducer.countEvery(),
        maxPixels=1e7,
    )
    resultado = vetores.filterBounds(ponto)
    n = resultado.size().getInfo()
    if n == 0:
        print(f"  [GSW] nenhuma feição de água encontrada no buffer de {buffer_m} m")
        return None
    # Escolhe a feição com maior área (o lago principal)
    feat = resultado.sort("count", ascending=False).first()
    geom = feat.geometry().simplify(maxError=30)
    coords = geom.coordinates().getInfo()
    print(f"  [GSW] encontrado! ({n} feição(ões))")
    return coords[0]


def _calcular_bbox(coords: list[list[float]]) -> list[float]:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [min(lons), min(lats), max(lons), max(lats)]


def _formatar_para_config(nome: str, coords: list[list[float]], municipio: int | None) -> str:
    bbox = _calcular_bbox(coords)
    linhas_poly = ",\n".join(f"            [{c[0]:.6f}, {c[1]:.6f}]" for c in coords)
    mun_str = f"{municipio}," if municipio else "0,  # preencher código IBGE"
    return (
        f'    "{nome}": {{\n'
        f"        \"polygon\": [\n{linhas_poly},\n        ],\n"
        f"        \"bbox\": [{bbox[0]:.3f}, {bbox[1]:.3f}, {bbox[2]:.3f}, {bbox[3]:.3f}],\n"
        f"        \"municipio\": {mun_str}\n"
        f"    }},"
    )


def main():
    parser = argparse.ArgumentParser(description="Extrai polígono de lagoa do GEE")
    parser.add_argument("--nome",     default="Lagoa Caconde", help="Nome da lagoa")
    parser.add_argument("--lat",      type=float, default=-29.867, help="Latitude do centro")
    parser.add_argument("--lon",      type=float, default=-50.200, help="Longitude do centro")
    parser.add_argument("--buffer",   type=int,   default=5000,   help="Buffer GSW em metros (default 5000)")
    parser.add_argument("--municipio",type=int,   default=None,   help="Código IBGE do município")
    parser.add_argument("--saida",    default=None, help="Arquivo JSON para salvar as coordenadas brutas")
    args = parser.parse_args()

    print(f"\nExtraindo polígono: {args.nome}")
    print(f"  Centro: lat={args.lat}, lon={args.lon}")
    print()

    if not init_ee():
        print("ERRO: não foi possível inicializar o GEE. Verifique GEE_SERVICE_ACCOUNT_KEY.")
        sys.exit(1)

    import ee
    ponto = ee.Geometry.Point([args.lon, args.lat])

    print("1. Tentando HydroLAKES...")
    coords = _buscar_hydrolakes(ponto, args.nome)

    if coords is None:
        print("2. Tentando JRC Global Surface Water...")
        coords = _buscar_gsw(ponto, args.buffer)

    if coords is None:
        print("\nNenhuma fonte retornou resultado. Sugestões:")
        print("  - Aumente --buffer (ex.: --buffer 8000)")
        print("  - Verifique se as coordenadas estão corretas")
        sys.exit(1)

    print(f"\n  {len(coords)} vértices extraídos")

    if args.saida:
        with open(args.saida, "w") as f:
            json.dump({"nome": args.nome, "coordinates": coords}, f, indent=2)
        print(f"  Coordenadas brutas salvas em: {args.saida}")

    print("\n" + "─" * 60)
    print("Cole em config.py (LAGOAS dict):\n")
    print(_formatar_para_config(args.nome, coords, args.municipio))
    print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
