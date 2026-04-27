# CLAUDE.md — Guia do Projeto lagoas/ndci_sentinel2

## O que é este projeto

Sistema standalone de monitoramento de qualidade da água em **7 lagoas costeiras do Litoral Norte do RS** via **NDCI (Normalized Difference Chlorophyll Index)** calculado sobre imagens Sentinel-2 do Google Earth Engine (GEE).

Metodologia alinhada com **Pi & Guasselli (SBSR 2025)**: processamento por imagem individual, buffer negativo de borda, máscara NDWI/FAI e percentis P10/P90 por cena.

Todo o código vive em `artefacts/ndci_sentinel2/`. O `dist/` na raiz é build estático para GitHub Pages.

---

## Stack

| Camada | Tecnologia |
|---|---|
| **API** | FastAPI + Uvicorn, porta 8001 |
| **DB** | PostgreSQL 16 (Docker) ou SQLite (dev local) |
| **ORM** | SQLAlchemy 2.x + DeclarativeBase |
| **Satélite** | Google Earth Engine Python API (earthengine-api) |
| **ML** | scikit-learn RandomForest (walk-forward CV) |
| **Frontend** | HTML/CSS/JS vanilla + Chart.js + chartjs-plugin-annotation + Leaflet |
| **Deploy estático** | GitHub Pages (branch `gh-pages`) via `scripts/build_static.py` |
| **Infra** | Docker Compose (serviços `db` + `api`) |
| **Python** | 3.11+ |

---

## Estrutura de diretórios

```
artefacts/ndci_sentinel2/
├── config.py                  # LAGOAS dict, polígonos GEE, ACTIVE_LAGOAS, TTLs
├── core/
│   ├── index_registry.py      # INDICES dict: IndexConfig + classify()
│   └── satellite_registry.py  # SATELLITES dict: SatelliteConfig
├── storage/
│   ├── database.py            # engine, SessionLocal, Base, get_db(), create_all_tables()
│   ├── models.py              # ImageRecord, WaterQualityRecord, MapTileRecord
│   └── repositories/
│       ├── image_records.py   # ImageRecordRepository (CRUD + upsert + get_monthly_aggregation)
│       ├── water_quality.py   # WaterQualityRepository (série temporal + upsert)
│       └── map_tiles.py       # MapTileRepository (cache tile_url + map_id)
├── ingestion/
│   ├── gee_auth.py            # init_ee() — SA key ou ADC
│   └── sentinel2/
│       ├── band_math.py       # add_water_indices(), water_mask()
│       ├── cloud_mask.py      # cloud_mask_s2() — SCL classes 3/8/9/10
│       ├── stats_worker.py    # _sync_collect_stats() + collect_stats() (async wrapper)
│       ├── tiles_worker.py    # gera tile URLs XYZ via getMapId()
│       └── refresh_worker.py  # regenera tiles prestes a expirar
├── ml/
│   ├── features.py            # load_ndci_features() — pipeline de features
│   └── predictor.py           # NdciPredictor — RandomForest walk-forward CV
├── api/
│   ├── main.py                # FastAPI app, startup, static mount, routers
│   └── routers/
│       ├── water_quality.py   # /api/water-quality (série mensal + current + images)
│       ├── tiles.py           # /api/tiles (proxy XYZ + availability)
│       ├── predictions.py     # /api/predictions/ndci/{lagoa}
│       └── workers.py         # /api/workers (collect-stats, generate-tiles, status)
├── migrations/
│   ├── 001_water_quality.sql  # DDL ndci_water_quality
│   ├── 002_map_tiles.sql      # DDL ndci_map_tiles
│   └── 003_image_records.sql  # DDL ndci_image_records
├── scripts/
│   └── build_static.py        # build + deploy GitHub Pages
├── frontend/
│   ├── index.html
│   ├── css/app.css
│   └── js/
│       ├── app.js             # orquestração principal (init, tabs, KPIs, charts)
│       ├── api.js             # cliente HTTP (modo dinâmico)
│       ├── api.static.js      # cliente JSON estático (gh-pages)
│       ├── charts.js          # Chart.js: buildSeriesChart, buildIndicesChart, etc.
│       ├── chart-actions.js   # ações sobre gráficos (download, etc.)
│       ├── map.js             # Leaflet + tiles GEE
│       ├── table.js           # DataTable com exportar CSV
│       └── utils.js           # classifyNdci(), fmtNdci(), fmtNum()
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env                       # POSTGRES_DB/USER/PASSWORD, GEE_PROJECT, GEE_KEY_PATH
```

---

## Modelos de dados (tabelas)

### `ndci_image_records` — fonte primária
Uma linha por cena Sentinel-2 válida. UniqueConstraint: `(satellite, lagoa, data)`.
Campos: `satellite, lagoa, data, ano, mes, ndci_mean, ndci_p90, ndci_p10, ndti_mean, ndwi_mean, fai_mean, n_pixels, cloud_pct`

### `ndci_water_quality` — agregados mensais
Derivada dos image_records via GROUP BY. UniqueConstraint: `(satellite, lagoa, ano, mes)`.
Campos: `satellite, lagoa, ano, mes, ndci_mean, ndci_p90, ndti_mean, fai_mean, ndwi_mean, n_pixels`

### `ndci_map_tiles` — cache de tiles XYZ
TTL de 23 h (GEE map_ids expiram em ~24 h). UniqueConstraint: `(satellite, index_key, ano, mes, lagoa)`.
Campos: `satellite, index_key, ano, mes, lagoa, tile_url, map_id, vis_min, vis_max, palette, bounds, expires_at`

---

## Endpoints da API

```
GET  /api/water-quality                      → série mensal (todas as lagoas)
GET  /api/water-quality?lagoa=X             → série mensal filtrada
GET  /api/water-quality/current             → último período + classify() por lagoa
GET  /api/water-quality/lagoas              → lista de lagoas com dados
GET  /api/water-quality/{lagoa}/images      → série por imagem individual (Pi & Guasselli)
GET  /api/tiles/lagoa/ndci?lagoa=X&ano=Y&mes=M
GET  /api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>
GET  /api/tiles/lagoas                      → lagoas + bounding boxes
GET  /api/tiles/availability
GET  /api/predictions/ndci/{lagoa}?horizonte_meses=2
POST /api/workers/collect-stats?ano_inicio=2017[&ano_fim=Y][&force=true]
POST /api/workers/generate-tiles?ano_inicio=Y
POST /api/workers/refresh-tiles?window_hours=6
GET  /api/workers/status                    → contagem de registros por tabela
GET  /docs                                  → Swagger UI
```

---

## Comandos principais

```bash
# Subir ambiente Docker
cd artefacts/ndci_sentinel2
docker compose up -d
docker compose logs -f api

# Backfill histórico completo
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2017"
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2017"

# Status do banco
curl http://localhost:8001/api/workers/status

# Rodar API sem Docker
export DATABASE_URL=sqlite:///./ndci_sentinel2.db
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload

# Build estático GitHub Pages
python artefacts/ndci_sentinel2/scripts/build_static.py --deploy
# Apenas local:
python artefacts/ndci_sentinel2/scripts/build_static.py --out artefacts/ndci_sentinel2/dist
python -m http.server 3000 --directory artefacts/ndci_sentinel2/dist
```

---

## Padrões de código inegociáveis

**Python:**
- `from __future__ import annotations` em todo arquivo Python
- Imports de módulo interno: caminho relativo ao root do pacote (ex: `from config import LAGOAS`, `from storage.database import get_db`)
- SQLAlchemy: `get_db()` como dependência FastAPI via `Depends()`; repositories como classes com `self.db`
- Workers GEE: lógica síncrona em `_sync_*` + wrapper `async` via `loop.run_in_executor(None, lambda: ...)`
- GEE calls custosas (reduceRegion, getInfo) SEMPRE dentro de try/except com fallback None
- `_safe_float(val)` para qualquer valor vindo do GEE antes de salvar no banco

**JavaScript (frontend):**
- ES modules (`import/export`) — sem bundler, direto no browser
- `async/await` + `Promise.all()` para chamadas paralelas
- Chart.js: sempre `chart.destroy()` antes de recriar (evita canvas leak)
- Dois modos de API: `api.js` (dinâmico, fetch para localhost:8001) e `api.static.js` (JSON estático, gh-pages)

**SQL/Migrations:**
- Migrações em arquivos SQL numerados (`001_`, `002_`, ...) em `migrations/`
- `UniqueConstraint` nomeada em todos os modelos para suportar upsert idempotente
- A coluna `satellite` em todos os modelos é o ponto de extensão para novos satélites

---

## Lagoas monitoradas

| Lagoa | buffer_negativo_m | min_pixels |
|---|---|---|
| Lagoa dos Barros | 100 m | 2 000 |
| Lagoa dos Quadros | 200 m | 3 000 |
| Lagoa Itapeva | 200 m | 2 000 |
| Lagoa de Tramandaí | 100 m | 1 000 |
| Lagoa do Armazém | 100 m | 1 000 |
| Lagoa do Peixoto | **30 m** | 300 |
| Lagoa Caconde | 30 m | 100 |

Para ativar apenas algumas: `ACTIVE_LAGOAS = ["Lagoa dos Barros", ...]` em `config.py`.

---

## Escalas de alerta NDCI

| NDCI | Status | Cor |
|---|---|---|
| < 0.02 | `bom` | azul |
| 0.02–0.10 | `moderado` | amarelo |
| 0.10–0.20 | `elevado` | laranja |
| > 0.20 | `critico` | vermelho |

Limiar de eflorescência ≈ 14 µg/L (linha de referência no gráfico).
Classificação via `core/index_registry.py → classify("ndci", value)`.

---

## Como estender

**Novo satélite:**
1. `core/satellite_registry.py` → adicionar `SATELLITES["novo"]`
2. Criar `ingestion/novo/cloud_mask.py`, `band_math.py`, `stats_worker.py`, `tiles_worker.py`
3. Os repositories já aceitam `satellite="novo"` — nenhuma mudança necessária

**Novo índice:**
1. `core/index_registry.py` → adicionar em `INDICES`
2. `ingestion/sentinel2/band_math.py` → adicionar cálculo da banda
3. Workers iteram sobre `INDICES` por domínio — automático

## Regras de Terminal e Leitura de Arquivos (Uso Obrigatório do RTK)

Para economizar tokens de contexto, este projeto utiliza o RTK (Rust Token Killer). O RTK intercepta comandos de terminal (Bash) e otimiza a saída. Para que isso funcione, você DEVE seguir estas regras:

1. **NUNCA** use as suas ferramentas embutidas nativas como `Read`, `Grep` ou `Glob`.
2. **SEMPRE** use a ferramenta `Bash` (terminal) para ler arquivos, buscar textos ou listar diretórios.
3. Use os seguintes comandos explicitamente no terminal:
   - Para ler arquivos: use `rtk read <nome_do_arquivo>`
   - Para buscar texto (grep): use `rtk grep "padrao" .`
   - Para listar ou buscar arquivos: use `rtk ls` ou `rtk find "*.ext" .`

Aja como se as ferramentas nativas de leitura e busca não existissem e dependa 100% do terminal (Bash).
