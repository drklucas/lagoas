# Ajustes metodológicos — alinhamento com Pi & Guasselli (SBSR 2025)

**Referência**: Pi, N. B.; Guasselli, L. A. Séries temporais de NDCI para análise de tendências de eutrofização, lagoas do Litoral Norte-RS. *Anais do XXI SBSR*, INPE, Salvador/BA, abril 2025.

**Objetivo**: documentar todas as mudanças necessárias para que nosso pipeline reproduza — e generalize para as 7 lagoas — a metodologia validada pelo paper, substituindo as escolhas de implementação atuais que introduzem viés sistemático nos valores de NDCI.

---

## Sumário de problemas e soluções

| # | Problema | Impacto | Arquivo(s) afetado(s) |
|---|---|---|---|
| 1 | Polígonos imprecisos ou retângulos bbox | Alto | `config.py` |
| 2 | Sem buffer negativo de borda | Alto | `config.py`, `stats_worker.py` |
| 3 | Composição mensal por mediana em vez de imagens individuais | Médio | `stats_worker.py` |
| 4 | Máscara SCL remove pixels de bloom como vegetação | Médio | `cloud_mask.py` |
| 5 | Schema do banco não comporta granularidade por imagem | Alto | `models.py`, `repositories/water_quality.py` |
| 6 | Frontend exibe apenas mediana mensal, sem P90 por imagem | Médio | `charts.js`, `api/routers/water_quality.py` |

---

## Problema 1 — Polígonos imprecisos

### Situação atual

`config.py` contém dois tipos de polígono:

- **Preciso** (Peixoto, Barros, Caconde): coordenadas levantadas manualmente ou extraídas do GEE, com forma razoável.
- **Retângulo bbox** (Tramandaí, Armazém, Itapeva, Quadros): simples retângulo de 4 pontos que cobre o bounding box da lagoa, incluindo terra nas quinas e margens.

O paper usa polígonos da **Base Cartográfica do RS escala 1:25.000 (BCRS25)** para Barros e Quadros. A Lagoa dos Quadros tem 120,6 km² — um retângulo de bbox captura margem, campos e estradas junto com a água.

### O que fazer

Para cada lagoa, obter o polígono vetorial da hidrografia oficial:

- **Fonte primária**: BCRS25 — Secretaria do Meio Ambiente e Infraestrutura do RS + FEPAM.
  - Download: `https://www.sema.rs.gov.br/base-cartografica-rs`
  - Camada: Hidrografia — corpos d'água poligonais.
- **Fonte alternativa**: OpenStreetMap (camada `natural=water`) ou Global Surface Water (JRC) exportado do GEE como vetor.

**Lagoas prioritárias** (polígonos mais deficientes):

| Lagoa | Problema atual | Ação |
|---|---|---|
| Lagoa dos Quadros | Retângulo bbox 70×60 km² | Substituir pelo polígono BCRS25 |
| Lagoa de Tramandaí | Retângulo bbox | Substituir pelo polígono BCRS25 |
| Lagoa do Armazém | Retângulo bbox | Substituir pelo polígono BCRS25 |
| Lagoa Itapeva | Retângulo bbox | Substituir pelo polígono BCRS25 |
| Lagoa dos Barros | Polígono razoável | Validar vs. BCRS25 e refinar |
| Lagoa do Peixoto | Polígono razoável | Validar vs. BCRS25 |
| Lagoa Caconde | Polígono detalhado | Validar — provavelmente ok |

**Formato esperado em `config.py`**: lista de `[lon, lat]` em sentido horário, fechando no primeiro ponto. Manter a chave `"polygon"` — o restante do pipeline já a consome.

### Como extrair do GEE (alternativa automatizável)

O script `scripts/extract_polygon.py` já existe no projeto e faz exatamente isso. Para cada lagoa sem polígono preciso:

```bash
python -m scripts.extract_polygon --nome "Lagoa dos Quadros" --lat -29.750 --lon -50.175
python -m scripts.extract_polygon --nome "Lagoa de Tramandaí" --lat -29.975 --lon -50.120
python -m scripts.extract_polygon --nome "Lagoa do Armazém"   --lat -29.965 --lon -50.140
python -m scripts.extract_polygon --nome "Lagoa Itapeva"      --lat -29.365 --lon -49.995
```

Colar o resultado em `config.py` substituindo os retângulos atuais.

---

## Problema 2 — Buffer negativo de borda ausente

### Situação atual

`stats_worker.py` passa o polígono bruto diretamente ao `reduceRegion`:

```python
geom = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
# ... sem erosão ...
means = water_img.reduceRegion(geometry=geom, ...)
```

Pixels de borda (água rasa, macrófitas, lama, terra úmida) têm mistura de sinal espectral que distorce o NDCI medido. O paper aplica buffer negativo empírico — **300 m para Barros, 200 m para Quadros** — antes de qualquer extração.

### O que fazer

#### 2a — Adicionar campo `buffer_negativo_m` em `config.py`

```python
LAGOAS: dict[str, dict] = {
    "Lagoa dos Barros": {
        "polygon": [...],
        "bbox": [...],
        "municipio": 4313508,
        "buffer_negativo_m": 300,   # ← novo campo
    },
    "Lagoa dos Quadros": {
        "polygon": [...],
        "bbox": [...],
        "municipio": 4313508,
        "buffer_negativo_m": 200,   # ← novo campo
    },
    # Para lagoas menores, usar valores menores empiricamente:
    "Lagoa do Peixoto":   { ..., "buffer_negativo_m": 100 },
    "Lagoa Caconde":      { ..., "buffer_negativo_m":  50 },
    "Lagoa de Tramandaí": { ..., "buffer_negativo_m": 150 },
    "Lagoa do Armazém":   { ..., "buffer_negativo_m": 100 },
    "Lagoa Itapeva":      { ..., "buffer_negativo_m": 200 },
}
```

**Critério para escolher o valor**: o buffer deve ser suficiente para eliminar a zona de variação sazonal de área superficial da lagoa. Para lagoas grandes (Barros, Quadros, Itapeva) usar 200–300 m; para lagoas pequenas (Caconde, Peixoto) usar 50–100 m. Os valores podem ser ajustados empiricamente observando os mapas de tiles.

#### 2b — Aplicar o buffer no `stats_worker.py`

```python
geom_raw    = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
buffer_m    = lagoa_cfg.get("buffer_negativo_m", 0)
geom        = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw

# A partir daqui, usar `geom` (erodida) em vez de `geom_raw`
monthly = s2_base.filterDate(d0, d1).filterBounds(geom_raw)  # filtro espacial no bbox original
# ...
means = water_img.reduceRegion(geometry=geom, ...)            # redução na geometria erodida
```

**Importante**: usar `geom_raw` no `filterBounds` (para não descartar imagens) e `geom` erodida apenas no `reduceRegion`.

#### 2c — Aplicar o mesmo buffer no `tiles_worker.py`

Os tiles visuais exibidos no mapa também devem ser recortados na geometria erodida para consistência visual com os valores numéricos.

---

## Problema 3 — Composição mensal por mediana em vez de imagens individuais

### Situação atual

```python
composite = monthly.median()   # mediana de todas as imagens do mês
water_img = water_mask(composite, WATER_MASK_THRESHOLD)
means = water_img.reduceRegion(reducer=ee.Reducer.mean(), ...)
```

Uma mediana mensal de 15–20 imagens suaviza eventos de bloom que duram dias ou semanas. O paper captura imagens individuais com até 10 dias de intervalo, mantendo a variabilidade temporal real — que é justamente o que permite detectar picos de Chl-a de verão.

### O que fazer

#### 3a — Novo modelo de coleta: por imagem individual

Substituir o loop `ano × mês` por um loop `por imagem individual` dentro do período:

```python
col = (
    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
    .filterDate(d0_periodo, d1_periodo)
    .filterBounds(geom_raw)
    .map(cloud_mask_s2)
    .map(add_water_indices)
)

image_list = col.toList(col.size())
n = col.size().getInfo()

for i in range(n):
    img = ee.Image(image_list.get(i))
    date_str = img.date().format("YYYY-MM-dd").getInfo()

    water_img = water_mask(img, WATER_MASK_THRESHOLD)

    # Filtrar imagens com cobertura de água insuficiente (análogo ao critério de nuvens do paper)
    n_pixels = ...  # contar pixels válidos
    if n_pixels < MIN_VALID_PIXELS:
        continue

    ndci_mean = ...  # reduceRegion na geom erodida
    ndci_p90  = ...
    # salvar com granularidade de data
```

#### 3b — Critério de qualidade por imagem (equivalente à seleção manual do paper)

O paper seleciona manualmente imagens com baixa cobertura de nuvens. Automatizar isso:

- Calcular `n_pixels` válidos após cloud mask + water mask.
- Definir `MIN_VALID_PIXELS` por lagoa (proporcional à área esperada com o buffer aplicado).
- Descartar imagens onde `n_pixels < MIN_VALID_PIXELS` — equivale a descartar imagens com nuvens excessivas.
- Alternativamente: usar a propriedade `CLOUDY_PIXEL_PERCENTAGE` dos metadados do Sentinel-2 como pré-filtro: `.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))`.

#### 3c — Manter agregação mensal como derivada

A série temporal por imagem individual é a fonte primária. A mediana/média mensal passa a ser calculada **no banco ou na API** como agregação sobre os registros individuais, não no GEE. Isso preserva os dados brutos e permite recalcular a agregação com diferentes janelas.

---

## Problema 4 — Máscara SCL remove pixels de bloom como vegetação

### Situação atual

`cloud_mask.py` mantém todas as classes SCL exceto 3 (sombra), 8, 9 (nuvem) e 10 (cirrus). A classe **4 (VEGETATION)** é mantida. O problema: o processador Sen2Cor classifica florescências densas de cianobactérias como vegetação (classe 4), porque o espectro de bloom denso se assemelha ao de vegetação rasteira. Esses pixels têm exatamente os maiores valores de NDCI — e são descartados pelo filtro NDWI > −0.1 aplicado depois, que exclui vegetação emergente.

### O que fazer

#### 4a — Não usar SCL como filtro primário para pixels de água

A abordagem mais robusta é usar a máscara de água (NDWI) como critério principal e a SCL apenas para remover nuvens confirmadas:

```python
def cloud_mask_s2(img):
    """
    Remove apenas artefatos atmosféricos confirmados pela SCL.
    Não remove VEGETATION (4) — bloom de cianobactérias aparece como vegetação.
    """
    scl  = img.select("SCL")
    mask = (
        scl.neq(1)   # saturado/defeituoso
        .And(scl.neq(3))   # sombra de nuvem
        .And(scl.neq(8))   # nuvem média prob
        .And(scl.neq(9))   # nuvem alta prob
        .And(scl.neq(10))  # cirrus
        # classe 4 (VEGETATION) é mantida — pode ser bloom
    )
    return img.updateMask(mask)
```

Essa mudança já está implementada de forma equivalente — o problema real está no filtro NDWI subsequente.

#### 4b — Revisar o threshold do filtro NDWI para pixels de bloom

A máscara de água em `band_math.py` usa `NDWI > −0.1`. Florescências densas de cianobactérias têm alta reflectância no verde e no NIR, podendo produzir NDWI próximo de 0 ou ligeiramente negativo — logo acima do threshold, mas em bloom muito intenso podem cair abaixo de −0.1.

Opções:
1. **Relaxar o threshold** de −0.1 para −0.2 em `config.py` (`WATER_MASK_THRESHOLD`). Mais pixels de bloom são retidos, mas mais terra também pode entrar — por isso o buffer negativo do Problema 2 se torna ainda mais crítico.
2. **Usar FAI (Floating Algae Index) como complemento**: pixels com FAI > 0 são superfícies de água com material flutuante (bloom ou macrófitas) e devem ser incluídos mesmo que NDWI esteja abaixo do threshold. O FAI já é calculado em `stats_worker.py` — a lógica de máscara pode usar `NDWI > threshold OR FAI > 0`.

```python
# Em band_math.py — water_mask revisada
def water_mask(composite, threshold: float = -0.2):
    ndwi_mask = composite.select("NDWI").gt(threshold)
    # Incluir pixels de bloom mesmo com NDWI baixo
    fai_mask  = composite.select("FAI").gt(0)  # se FAI disponível
    return composite.updateMask(ndwi_mask.Or(fai_mask))
```

#### 4c — Usar produto S2_CLOUD_PROBABILITY como alternativa à SCL

O GEE disponibiliza `COPERNICUS/S2_CLOUD_PROBABILITY` (Sentinel-2 Cloud Probability, s2cloudless). Esse modelo não usa o Sen2Cor e é mais conservador — remove menos pixels de vegetação/bloom. Pode substituir a SCL como fonte de máscara de nuvens:

```python
s2_sr   = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
s2_prob = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY")

def mask_with_probability(img):
    prob = ee.Image(s2_prob.filterDate(...).first()).select("probability")
    return img.updateMask(prob.lt(40))  # threshold 40% de probabilidade de nuvem
```

Isso é opcional mas resolve o problema de bloom classificado como vegetação pelo Sen2Cor de forma mais limpa.

---

## Problema 5 — Schema do banco não suporta granularidade por imagem

### Situação atual

`models.py` armazena um registro por `(satellite, lagoa, ano, mes)` — chave única mensal. Não há campo para data de imagem individual.

### O que fazer

#### 5a — Adicionar tabela de registros por imagem

Criar uma nova tabela `ndci_image_records` separada da tabela mensal agregada:

```python
class ImageRecord(Base):
    __tablename__ = "ndci_image_records"

    id          = Column(Integer, primary_key=True)
    satellite   = Column(String, nullable=False)
    lagoa       = Column(String, nullable=False)
    data        = Column(Date, nullable=False)          # data da imagem (YYYY-MM-DD)
    ano         = Column(Integer, nullable=False)       # derivado de data
    mes         = Column(Integer, nullable=False)       # derivado de data
    ndci_mean   = Column(Float)
    ndci_p90    = Column(Float)
    ndci_p10    = Column(Float)
    ndti_mean   = Column(Float)
    ndwi_mean   = Column(Float)
    fai_mean    = Column(Float)
    n_pixels    = Column(Integer)
    cloud_pct   = Column(Float)                        # CLOUDY_PIXEL_PERCENTAGE da imagem
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("satellite", "lagoa", "data", name="uq_image_record"),
    )
```

#### 5b — Manter a tabela mensal como view agregada

A tabela `ndci_water_quality` existente pode continuar, mas passa a ser populada a partir dos registros individuais (média e P90 dos `ImageRecord` do mês), não diretamente do GEE. Isso garante consistência entre as duas granularidades.

---

## Problema 6 — Frontend exibe apenas mediana mensal

### Situação atual

`charts.js` plota apenas `ndci_mean` por período (mês). Não há visualização de variabilidade intra-mensal nem de P90 por imagem.

### O que fazer

#### 6a — Série temporal por imagem individual

Adicionar endpoint `GET /water-quality/{lagoa}/images` que retorna os registros da tabela `ndci_image_records`, permitindo ao frontend plotar a série com granularidade de imagem (como o paper).

#### 6b — Banda de incerteza no gráfico de série temporal

No `buildSeriesChart`, adicionar um segundo dataset com P10–P90 como área sombreada ao redor da linha de média:

```javascript
datasets: [
  {
    label: 'NDCI P10–P90',
    data: periodos.map((_, i) => ({ x: periodos[i], y: ndci_p90[i] })),
    fill: '+1',   // preenche até o próximo dataset
    backgroundColor: rgba(color, 0.12),
    borderWidth: 0,
    pointRadius: 0,
  },
  {
    label: 'NDCI médio',
    data: ndci_mean,
    // ... configuração atual ...
  },
  {
    label: 'NDCI P10',
    data: ndci_p10,
    fill: false,
    borderWidth: 0,
    pointRadius: 0,
  },
]
```

#### 6c — Linha de referência de eflorescência algal

O paper usa NDCI = 0 como referência de ~14 µg/L de Chl-a (limiar de eflorescência). Adicionar essa linha em `alertAnnotations()` em `charts.js`:

```javascript
bloom_line: {
  type: 'line', yMin: 0, yMax: 0,
  borderColor: 'rgba(163,113,247,0.55)',
  borderWidth: 1, borderDash: [6, 3],
  label: {
    display: true, content: 'Eflorescência (~14 µg/L)',
    position: 'start', color: 'rgba(163,113,247,0.75)',
    font: { size: 9, family: FONT },
    backgroundColor: 'transparent', padding: 0,
  },
},
```

---

## Ordem de implementação sugerida

```
Fase 1 — Base de dados (sem quebrar o que funciona hoje)
  [1.1] Obter polígonos BCRS25 para Quadros, Tramandaí, Armazém, Itapeva
  [1.2] Atualizar config.py com novos polígonos + campo buffer_negativo_m
  [1.3] Criar tabela ndci_image_records + migration

Fase 2 — Pipeline de ingestão
  [2.1] Refatorar stats_worker.py para coletar por imagem individual
  [2.2] Aplicar buffer negativo no geom do reduceRegion
  [2.3] Adicionar pré-filtro CLOUDY_PIXEL_PERCENTAGE < 20
  [2.4] Revisar cloud_mask.py e water_mask (threshold + FAI)
  [2.5] Rodar coleta histórica 2018–2025 nas lagoas prioritárias (Barros, Quadros)

Fase 3 — API e Frontend
  [3.1] Endpoint GET /water-quality/{lagoa}/images
  [3.2] Série temporal por imagem no buildSeriesChart
  [3.3] Banda P10–P90 nos gráficos
  [3.4] Linha de referência de eflorescência (NDCI = 0)
```

---

## Referências

- Pi, N. B.; Guasselli, L. A. (2025). Séries temporais de NDCI para análise de tendências de eutrofização, lagoas do Litoral Norte-RS. *Anais do XXI SBSR*. INPE.
- Mishra, S.; Mishra, D. R. (2012). Normalized difference chlorophyll index. *Remote Sensing of Environment*, 117, 394–406.
- SEMA/FEPAM. Base Cartográfica do RS — BCRS25 v1.0, 2018.
- Caneve et al. (2023). Meteorological and potential climatic influence on high cyanobacterial biomass within Patos Lagoon. *Ocean and Coastal Research*, 71.
