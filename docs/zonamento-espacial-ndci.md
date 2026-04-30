# Zonamento Espacial por Anéis Concêntricos — NDCI/Sentinel-2

## Motivação

O processamento original calcula estatísticas NDCI sobre a lagoa inteira (com buffer negativo de borda). Essa agregação mascara gradientes espaciais relevantes: zonas litorâneas rasas tendem a ter NDCI mais alto por influência de macrófitas e sedimento, enquanto o núcleo pelágico reflete melhor a biomassa de fitoplâncton em suspensão.

O zonamento divide cada lagoa em anéis concêntricos a partir do polígono original, permitindo comparar a dinâmica de NDCI entre margem, zona média e núcleo.

---

## Metodologia

### Geometria dos anéis

Cada zona é definida por dois buffers negativos aplicados ao polígono original:

```
anel = polygon.buffer(-buffer_ext).difference(polygon.buffer(-buffer_int))
nucleo = polygon.buffer(-buffer_ext)   # sem limite interno
```

`buffer_ext` define a borda externa do anel; `buffer_int` define a borda interna. `buffer_int = None` indica o núcleo (sem erosão interna).

### Configuração por lagoa

| Lagoa | buffer atual | margem | medio | nucleo |
|---|---|---|---|---|
| Lagoa do Peixoto | 30 m | 0–30 m | — | >30 m |
| Lagoa Caconde | 50 m | 0–50 m | — | >50 m |
| Lagoa do Armazém | 100 m | 0–100 m | 100–300 m | >300 m |
| Lagoa de Tramandaí | 150 m | 0–150 m | 150–400 m | >400 m |
| Lagoa Itapeva | 200 m | 0–200 m | 200–600 m | >600 m |
| Lagoa dos Barros | 300 m | 0–300 m | 300–700 m | >700 m |

A zona `margem` corresponde exatamente à faixa que era descartada pelo buffer negativo original — agora analisada separadamente em vez de excluída.

Lagoas pequenas (Peixoto, Caconde) recebem apenas 2 zonas por limitação de área.

### Processamento GEE

Para cada imagem Sentinel-2 válida, o worker executa `reduceRegion` separadamente em cada geometria de zona. O processamento mantém compatibilidade com os dados existentes através da zona `total` (idêntica ao fluxo anterior com buffer negativo).

Limiar mínimo de pixels: 30 px por zona (menor que o da lagoa inteira pela área reduzida dos anéis).

---

## Implementação

### Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `config.py` | Chave `zonas: [{"nome", "buffer_ext", "buffer_int"}]` em cada lagoa |
| `storage/models.py` | Coluna `zona TEXT NOT NULL DEFAULT 'total'` em `ImageRecord` e `WaterQualityRecord`; UniqueConstraints atualizados para incluir `zona` |
| `storage/repositories/image_records.py` | Parâmetro `zona=` em `upsert`, `exists`, `get_series`, `get_monthly_aggregation`; novo `get_zones_series()` |
| `storage/repositories/water_quality.py` | Idem + `get_zones_series()`, `get_all_series(zona=)`, `get_latest(zona=)` |
| `ingestion/sentinel2/stats_worker.py` | `_build_zone_geometries()`, `_reduce_zone()`; loop de zonas dentro de `_process_lagoa()`; `_update_monthly_aggregates()` recebe lista de zonas |
| `api/routers/water_quality.py` | Parâmetro `?zona=` no endpoint existente; novo `GET /{lagoa}/zones` |
| `migrations/004_zones.sql` | `ADD COLUMN zona`, troca de constraints, novos índices (PostgreSQL) |
| `frontend/js/api.js` | `getZoneSeries(lagoa)` |
| `frontend/js/api.static.js` | `getZoneSeries` para build estático (gh-pages) |
| `frontend/js/charts.js` | `buildZoneChart()` — linha por zona com cores distintas e faixas de alerta |
| `frontend/js/app.js` | Modo `viewMode='zonas'`, cache `zoneData`, integração do botão Zonas |
| `frontend/index.html` | Botão "Zonas" com ícone de círculos concêntricos |
| `frontend/css/app.css` | Estilo `.btn-zone` e estado ativo |
| `scripts/build_static.py` | Exporta `data/zones/<slug>.json` no build estático |

### Migration (PostgreSQL)

```bash
docker compose exec -T db psql -U ndci -d ndci -f - < migrations/004_zones.sql
```

Para SQLite (dev local): recriar o banco (o `create_all_tables()` recria com o novo schema).

### Reprocessamento do histórico

```bash
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2017&force=true"
```

O `force=true` é necessário para processar as zonas de imagens já existentes no banco (que têm `zona='total'` por default da migration).

---

## API

### Endpoint novo

```
GET /api/water-quality/{lagoa}/zones
```

Retorna séries mensais por zona (exclui `total`):

```json
{
  "lagoa": "Lagoa dos Barros",
  "satellite": "sentinel2",
  "zonas": {
    "margem": { "periodos": ["2017-07", ...], "ndci_mean": [...], "ndci_p90": [...], ... },
    "medio":  { ... },
    "nucleo": { ... }
  }
}
```

### Endpoint existente com filtro de zona

```
GET /api/water-quality?zona=margem
GET /api/water-quality/{lagoa}/images  (já inclui zona via parâmetro interno)
```

---

## Frontend

Botão **Zonas** na barra de controles do gráfico de série temporal (ao lado de "Por imagem"). Quando ativo, exibe um gráfico de linhas com uma série por zona:

- **Margem** — laranja `rgba(247,147,26)`
- **Médio** — azul `rgba(88,166,255)`
- **Núcleo** — verde `rgba(63,185,80)`

As faixas de alerta NDCI (bom/moderado/elevado/crítico) são mantidas no gráfico de zonas. Se não houver dados por zona (ingestão pendente), o modo cai automaticamente para mensal.

---

## Interpretação esperada

A diferença entre `margem` e `nucleo` é o gradiente espacial de NDCI. Em eventos de bloom de cianobactérias, espera-se que a margem apresente NDCI mais alto antes do núcleo (progressão da zona litorânea para o pelágico). A convergência entre zonas sugere bloom generalizado.

A zona `total` (dados históricos) permanece inalterada — zero quebra de compatibilidade com o modelo ML e exportações existentes.
