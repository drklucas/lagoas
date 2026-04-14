# NDCI Sentinel-2 — Monitoramento de Qualidade da Água

Monitoramento contínuo de lagoas costeiras do Litoral Norte do RS via **Normalized Difference Chlorophyll Index (NDCI)** calculado sobre imagens Sentinel-2 do Google Earth Engine (GEE).

Metodologia alinhada com **Pi & Guasselli (SBSR 2025)**: processamento por imagem individual, buffer negativo de borda, máscara de água por NDWI/FAI e percentis P10/P90 por cena.

---

## Arquitetura

```
Sentinel-2 (GEE)
      │
      ▼
┌─────────────────────────────────┐
│  stats_worker.py                │  coleta por imagem → ndci_image_records
│  tiles_worker.py                │  tiles visuais XYZ → ndci_map_tiles
└──────────────┬──────────────────┘
               │
               ▼
        PostgreSQL (pg_data)
               │
               ▼
┌─────────────────────────────────┐
│  FastAPI  :8001                 │  /api/water-quality, /api/workers, /docs
│  frontend (HTML/CSS/JS)         │  Chart.js + chartjs-plugin-annotation
└──────────────┬──────────────────┘
               │
               ▼
      GitHub Pages (estático)
      build_static.py --deploy
```

---

## Lagoas monitoradas

| Lagoa | Município | Pixels mín. |
|---|---|---|
| Lagoa dos Barros | Osório | 2 000 |
| Lagoa do Peixoto | Osório | 300 |
| Lagoa Itapeva | Torres | 2 000 |
| Lagoa dos Quadros | Osório | 3 000 |
| Lagoa de Tramandaí | Tramandaí | 1 000 |
| Lagoa do Armazém | Tramandaí | 1 000 |
| Lagoa Caconde | Osório | 100 |

> Para ativar somente algumas lagoas edite `ACTIVE_LAGOAS` em `config.py`.

---

## Faixas de alerta NDCI

| Status | Intervalo | Interpretação |
|---|---|---|
| Bom | < 0,02 | Clorofila baixa |
| Moderado | 0,02 – 0,10 | Atenção |
| Elevado | 0,10 – 0,20 | Alerta — possível floração |
| Crítico | > 0,20 | Floração de cianobactérias |

Limiar de eflorescência ≈ 14 µg/L (linha de referência no gráfico).

---

## Pré-requisitos

- Docker e Docker Compose
- Conta no [Google Earth Engine](https://earthengine.google.com/) com service account
- Python 3.11+ (apenas para o build estático)

---

## Configuração

```bash
# 1. Clone o repositório
git clone https://github.com/drklucas/lagoas.git
cd lagoas/artefacts/ndci_sentinel2

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com sua senha do Postgres e projeto GEE

# 3. Adicione a chave da service account GEE
mkdir -p credentials
cp /caminho/para/sua/gee-key.json credentials/gee-key.json

# 4. Suba os serviços
docker compose up -d

# 5. Acesse o dashboard
open http://localhost:8001
```

---

## Workers de ingestão

### Coletar estatísticas (NDCI/NDTI/NDWI por imagem)

```bash
# Backfill completo desde 2017
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2017"

# Apenas um ano específico
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2024&ano_fim=2024"

# Forçar re-processamento (sobrescreve registros existentes)
curl -X POST "http://localhost:8001/api/workers/collect-stats?force=true"
```

O worker roda em background — acompanhe o progresso:

```bash
docker compose logs -f api
```

### Gerar tiles visuais XYZ

```bash
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2024"
```

### Status do banco

```bash
curl http://localhost:8001/api/workers/status
```

---

## Controle de lagoas ativas

Edite `config.py` para limitar quais lagoas o worker processa:

```python
# Processa todas:
ACTIVE_LAGOAS = None

# Apenas Barros e Peixoto:
ACTIVE_LAGOAS = ["Lagoa dos Barros", "Lagoa do Peixoto"]
```

---

## Deploy estático no GitHub Pages

O site pode ser exportado como HTML + JSON estáticos para hospedagem gratuita no GitHub Pages, sem necessidade de servidor.

### Build + deploy em um comando

```bash
# Da raiz do repositório, com a API rodando localmente:
python artefacts/ndci_sentinel2/scripts/build_static.py --deploy
```

O script:
1. Chama a API local e exporta todos os dados como `.json`
2. Copia os assets do frontend com paths ajustados
3. Faz commit e push direto na branch `gh-pages`

### Apenas build local (sem publicar)

```bash
python artefacts/ndci_sentinel2/scripts/build_static.py --out artefacts/ndci_sentinel2/dist

# Teste local:
python -m http.server 3000 --directory artefacts/ndci_sentinel2/dist
```

### Ativar no GitHub

Em **Settings → Pages → Source**, selecione a branch `gh-pages` e pasta `/ (root)`.

O site ficará disponível em `https://drklucas.github.io/lagoas/`.

---

## API — endpoints principais

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/water-quality` | Série mensal por lagoa |
| GET | `/api/water-quality/current` | Status atual de cada lagoa |
| GET | `/api/water-quality/{lagoa}/images` | Série por imagem individual |
| POST | `/api/workers/collect-stats` | Inicia coleta de estatísticas |
| POST | `/api/workers/generate-tiles` | Gera tiles visuais |
| GET | `/api/workers/status` | Contagem de registros no banco |
| GET | `/docs` | Documentação interativa (Swagger UI) |

---

## Estrutura do projeto

```
ndci_sentinel2/
├── api/
│   ├── main.py                    # FastAPI app
│   └── routers/
│       ├── water_quality.py       # Endpoints de dados
│       ├── workers.py             # Endpoints de disparo de workers
│       └── tiles.py               # Endpoints de tiles XYZ
├── config.py                      # Lagoas, polígonos GEE, parâmetros
├── core/
│   ├── index_registry.py          # Índices espectrais (NDCI, NDTI, NDWI)
│   └── satellite_registry.py
├── frontend/
│   ├── index.html
│   ├── css/app.css
│   └── js/
│       ├── app.js                 # Orquestração principal
│       ├── charts.js              # Gráficos Chart.js
│       ├── api.js                 # Client HTTP (modo dinâmico)
│       └── api.static.js          # Client JSON (modo estático / gh-pages)
├── ingestion/
│   └── sentinel2/
│       ├── stats_worker.py        # Coleta estatísticas por imagem via GEE
│       ├── tiles_worker.py        # Gera tiles visuais XYZ via GEE
│       ├── band_math.py           # Cálculo de índices espectrais
│       └── cloud_mask.py          # Máscara de nuvens SCL
├── migrations/
│   ├── 001_water_quality.sql
│   ├── 002_map_tiles.sql
│   └── 003_image_records.sql
├── ml/
│   ├── features.py
│   └── predictor.py
├── scripts/
│   └── build_static.py            # Build + deploy GitHub Pages
├── storage/
│   ├── models.py
│   └── repositories/
│       ├── water_quality.py
│       ├── image_records.py
│       └── map_tiles.py
├── .env.example
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Referência

Pi, K.; Guasselli, L.A. *Monitoramento de cianobactérias em lagoas costeiras do Litoral Norte do RS via NDCI/Sentinel-2.* SBSR 2025.
