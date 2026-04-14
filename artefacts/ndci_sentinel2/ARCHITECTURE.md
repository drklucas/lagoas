# Arquitetura — NDCI/Sentinel-2

Sistema desacoplado de monitoramento de qualidade da água em lagoas costeiras
via Normalized Difference Chlorophyll Index (Sentinel-2, GEE).

Extraído do eyefish (eyefish/backend/) com todos os problemas identificados
no `relatorio_ndci.md` corrigidos.

---

## Estrutura de diretórios

```
ndci_sentinel2/
│
├── config.py                        # Lagoas, polígonos, vis_params, alertas
│
├── core/                            # Abstrações puras — zero deps de DB/GEE
│   ├── satellite_registry.py        # SatelliteConfig + SATELLITES dict
│   └── index_registry.py           # IndexConfig + INDICES dict
│
├── storage/                         # Camada de persistência standalone
│   ├── database.py                  # engine + SessionLocal (lê DATABASE_URL)
│   ├── models.py                    # WaterQualityRecord + MapTileRecord
│   └── repositories/
│       ├── water_quality.py         # CRUD + série temporal
│       └── map_tiles.py            # CRUD + cache de map_id em memória
│
├── migrations/
│   ├── 001_water_quality.sql        # DDL: ndci_water_quality
│   └── 002_map_tiles.sql           # DDL: ndci_map_tiles
│
├── ingestion/
│   ├── gee_auth.py                  # Auth GEE standalone (SA key / ADC)
│   └── sentinel2/
│       ├── cloud_mask.py           # SCL cloud masking
│       ├── band_math.py            # NDCI, NDTI, NDWI + water mask
│       ├── tiles_worker.py         # Gera tile URLs visuais
│       ├── stats_worker.py         # ← WORKER AUSENTE DO EYEFISH — implementado
│       └── refresh_worker.py       # Refresh de tiles prestes a expirar
│
├── ml/
│   ├── features.py                  # load_ndci_features() — pipeline de features
│   └── predictor.py                # NdciPredictor — RandomForest walk-forward CV
│
├── api/
│   ├── main.py                      # FastAPI app + startup
│   └── routers/
│       ├── water_quality.py         # GET /api/water-quality
│       ├── tiles.py                 # GET /api/tiles + proxy GEE
│       ├── predictions.py           # GET /api/predictions/ndci/{lagoa}
│       └── workers.py              # POST /api/workers/*
│
└── requirements.txt
```

---

## Fluxo de dados

```
[Sentinel-2 GEE — COPERNICUS/S2_SR_HARMONIZED]
          │
          ├── cloud_mask_s2()          SCL: remove nuvens (classe 3, 8, 9, 10)
          ├── add_water_indices()      NDCI=(B5-B4)/(B5+B4), NDTI, NDWI por pixel
          ├── .filterDate(d0, d1)      Filtra mês específico
          ├── .filterBounds(geom)      Filtra polígono da lagoa
          ├── .median()                Composite mediana (robusto a nuvens residuais)
          └── water_mask(NDWI > -0.1)  Descarta pixels de terra
                    │
                    ├── tiles_worker.py
                    │   getMapId(vis_params)
                    │   └── ndci_map_tiles (tile_url + map_id, TTL 23h)
                    │       └── GET /api/tiles/lagoa/ndci
                    │           └── GET /api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>
                    │
                    └── stats_worker.py          ← WORKER AUSENTE — IMPLEMENTADO AQUI
                        reduceRegion(mean + p90)
                        └── ndci_water_quality (ndci_mean, ndci_p90, ndti_mean, ...)
                            ├── GET /api/water-quality
                            └── ml/features.py → NdciPredictor → GET /api/predictions/ndci/{lagoa}
```

---

## Duas camadas de dados

| Camada | Tabela | Conteúdo | Usado por |
|--------|--------|----------|-----------|
| **Tiles visuais** | `ndci_map_tiles` | URLs XYZ pixel-level (20 m), TTL 23 h | Leaflet / Mapbox no frontend |
| **Estatísticas** | `ndci_water_quality` | Valores numéricos agregados por lagoa/mês | API série temporal + modelo ML |

---

## Modelos de dados

### `ndci_water_quality`
```sql
satellite   VARCHAR(50)   -- 'sentinel2' (extensível)
lagoa       VARCHAR(100)
ano         SMALLINT
mes         SMALLINT       -- 1..12
ndci_mean   FLOAT          -- NDCI médio — TARGET do ML
ndci_p90    FLOAT          -- percentil 90 (pior pixel)
ndti_mean   FLOAT          -- turbidez
fai_mean    FLOAT          -- Floating Algae Index
ndwi_mean   FLOAT          -- disponibilidade hídrica
n_pixels    INTEGER        -- pixels válidos (< 100 = dado pouco confiável)
```

### `ndci_map_tiles`
```sql
satellite   VARCHAR(50)   -- 'sentinel2'
index_key   VARCHAR(50)   -- 'ndci' | 'ndti'
ano         SMALLINT
mes         SMALLINT
lagoa       VARCHAR(100)
tile_url    VARCHAR(700)   -- URL template {z}/{x}/{y}
map_id      VARCHAR(400)   -- GEE Map Resource ID (expira ~24h)
expires_at  TIMESTAMP      -- TTL conservador: 23h
```

A coluna `satellite` em ambas as tabelas é o ponto de extensão para novos satélites.

---

## Escalas de alerta NDCI

| NDCI        | Status    | Interpretação                    |
|-------------|-----------|----------------------------------|
| < 0.02      | `bom`     | Águas claras, sem bloom          |
| 0.02 – 0.10 | `moderado`| Presença moderada de algas       |
| 0.10 – 0.20 | `elevado` | Floração em desenvolvimento      |
| > 0.20      | `critico` | Floração intensa — risco à saúde |

---

## Endpoints da API

### Qualidade da água (série temporal)
```
GET  /api/water-quality                 → Série completa por lagoa
GET  /api/water-quality?lagoa=X        → Série de uma lagoa
GET  /api/water-quality/current        → Último mês disponível + status de alerta
GET  /api/water-quality/lagoas         → Lagoas com dados no banco
```

### Tiles visuais
```
GET  /api/tiles/lagoa/ndci?lagoa=X&ano=2023&mes=8  → tile_url para Leaflet
GET  /api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>    → Proxy autenticado GEE
GET  /api/tiles/lagoas                             → Lagoas + bounding boxes
GET  /api/tiles/availability                       → Cobertura temporal por índice
```

### Previsão ML
```
GET  /api/predictions/ndci/{lagoa}?horizonte_meses=2  → Previsão RandomForest
```

### Workers (disparo manual)
```
POST /api/workers/collect-stats?ano_inicio=2017        → ← Worker ausente, implementado
POST /api/workers/generate-tiles?ano_inicio=2017       → Gera tiles visuais
POST /api/workers/refresh-tiles?window_hours=6         → Refresh de tiles expirados
```

---

## Como adicionar um novo satélite

1. **Registrar** em `core/satellite_registry.py`:
   ```python
   SATELLITES["landsat8"] = SatelliteConfig(
       key="landsat8",
       collection="LANDSAT/LC08/C02/T1_L2",
       bands={"RED": "SR_B4", "NIR": "SR_B5", ...},
       cloud_mask_fn="landsat_qa",
       compatible_indices=["ndvi"],
       start_year=2013,
   )
   ```

2. **Criar módulo** `ingestion/landsat8/` com `cloud_mask.py`, `band_math.py`, `tiles_worker.py`, `stats_worker.py`.

3. **Instanciar workers** com o novo satélite — os repositórios já aceitam `satellite="landsat8"`.

---

## Como adicionar um novo índice

1. **Registrar** em `core/index_registry.py`:
   ```python
   INDICES["ndvi"] = IndexConfig(
       key="ndvi",
       bands=("NIR", "RED"),
       formula="(NIR - RED) / (NIR + RED)",
       domain="land",
       vis_params={"min": -0.1, "max": 0.9, "palette": [...]},
   )
   ```

2. **Adicionar cálculo** no `band_math.py` do satélite correspondente.

3. Nenhuma outra mudança necessária — os workers iteram sobre `INDICES` por domínio.

---

## Correções em relação ao eyefish

| Problema (relatorio_ndci.md) | Correção neste sistema |
|------------------------------|------------------------|
| Worker `ingest_gee_qualidade_agua` ausente | Implementado em `stats_worker.py` com `reduceRegion()` |
| Lagoas divergentes entre tiles e stats | Unificadas em `config.py` com mesmo polígono para ambas |
| Nenhum tratamento de n_pixels baixo | `n_pixels` exposto na API — consumidor pode filtrar |
| Docstring desatualizado (Barros, Horácio) | Configuração única em `config.py` — sem duplicação |

---

## Setup rápido

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar variáveis de ambiente
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost/ndci_db
export GEE_SERVICE_ACCOUNT_KEY=/path/to/gee-key.json
export GEE_PROJECT=seu-projeto-gee

# 3. Criar tabelas
python -c "from storage.database import create_all_tables; create_all_tables()"

# 4. Backfill histórico (2017–hoje, todas as lagoas)
# Estatísticas (preenche ndci_water_quality):
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2017"

# Tiles visuais (preenche ndci_map_tiles):
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2017"

# 5. Iniciar API
uvicorn api.main:app --host 0.0.0.0 --port 8001
```
