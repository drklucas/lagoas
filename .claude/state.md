# Estado do Repositório — ndci_sentinel2

_Snapshot em: 2026-04-15_

---

## O que está pronto e funcional

- **Pipeline de ingestão completo:** `stats_worker.py` coleta por imagem individual (Sentinel-2 via GEE), salva em `ndci_image_records` e deriva agregados mensais em `ndci_water_quality`. Este era o "worker ausente" do eyefish original — foi implementado neste sistema.
- **API FastAPI:** Todos os 4 routers estão implementados (`water_quality`, `tiles`, `predictions`, `workers`). Endpoint `/api/water-quality/{lagoa}/images` (série por imagem) alinhado com Pi & Guasselli.
- **Frontend completo:** 7 abas/views — Dashboard (KPIs + 6 gráficos), Tabela (exportar CSV), Mapa (Leaflet + tiles GEE). Toggle mensal/por-imagem. Filtro de período.
- **Modo estático GitHub Pages:** `build_static.py --deploy` exporta dados como JSON e publica na branch `gh-pages`. Site disponível em `https://drklucas.github.io/lagoas/`.
- **ML:** `NdciPredictor` (RandomForest walk-forward CV) implementado em `ml/predictor.py`.
- **Docker Compose:** Serviços `db` (PostgreSQL 16) + `api` funcionais. Migrações aplicadas automaticamente na inicialização.

---

## Arquivos com modificações não commitadas (em 2026-04-15)

Baseado no `git status`, os seguintes arquivos estão modificados (não commitados):
- `api/routers/water_quality.py`
- `frontend/index.html`
- `frontend/js/api.js`
- `frontend/js/charts.js`
- `ingestion/sentinel2/band_math.py`
- `ingestion/sentinel2/cloud_mask.py`
- `storage/database.py`
- `storage/models.py`

Todas as mudanças são dentro de `artefacts/ndci_sentinel2/`. O foco recente foi:
1. Adicionar endpoint `/api/water-quality/{lagoa}/images` (série por imagem)
2. Ajuste do buffer_negativo_m de Lagoa do Peixoto: 100 m → 30 m
3. Filtro de período na série temporal do frontend
4. Seletor de período filtrado por lagoa na aba de disponibilidade

---

## O que falta / pode ser melhorado

- **Testes:** Sem testes automatizados no repositório. Nenhum arquivo `test_*.py` ou diretório `tests/` encontrado.
- **`ndci_image_records` no dist estático:** O `build_static.py` provavelmente exporta apenas dados mensais. Verificar se exporta também `/api/water-quality/{lagoa}/images` para o modo gh-pages.
- **Refresh worker scheduling:** `refresh_worker.py` existe mas não há cron job configurado — precisa ser disparado manualmente ou integrado via `POST /api/workers/refresh-tiles`.
- **ML em produção:** O predictor existe mas não está integrado no frontend (não há gráfico de previsão visível no `app.js`).
- **`satellite_registry.py`:** Existe mas só `"sentinel2"` está registrado. Extensão para Landsat está documentada mas não implementada.

---

## Contexto do foco atual

O commit mais recente (`e6cb612`) corrigiu o buffer_negativo_m da Lagoa do Peixoto de 100 m para 30 m — indicando que o pipeline de ingestão está sendo calibrado/validado com dados reais.

Os commits anteriores (`f13b7d4`, `8e716ac`) adicionaram:
- Filtro de período na disponibilidade + seletor filtrado por lagoa
- Aba Mapa (Leaflet + GEE) e exportar CSV na tabela
- Pipeline NDCI por imagem + build estático GitHub Pages

O trabalho ativo está na **qualidade dos dados ingeridos** (buffer, máscara de água) e na **expansão do frontend** (novos charts, mapa, tabela).
