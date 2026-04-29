# Diagnóstico: Pluma NDCI Janeiro/2024 — Lagoa do Peixoto

**Observação:** Tile do eyefish (composição mensal) mostra bloom intenso (NDCI crítico)
em janeiro/2024. No lagoas, a região do bloom aparece **transparente** nos tiles
desse período.

---

## Pipeline atual (por imagem individual)

Os tiles são gerados por imagem individual — uma entrada em `ndci_map_tiles` por
`(satellite, index_key, data, lagoa)`. A `data` é a data exata da passagem do satélite,
não um agregado mensal. O pipeline completo:

```
S2_SR_HARMONIZED → cloud_mask_s2 (SCL) → add_water_indices → filterDate(1 dia)
  → mosaic → water_mask → clip(geom) → getMapId → tile_url
```

O `tiles_worker` itera sobre os `ImageRecord`s existentes no banco — só gera tiles
para datas que passaram pelo `stats_worker` (CLOUDY_PIXEL_PERCENTAGE < 20 % e
pixels válidos mínimos).

---

## Estado atual do cloud_mask_s2

O `cloud_mask_s2` atual (`ingestion/sentinel2/cloud_mask.py`) **já mantém a classe 4
(VEGETATION)** de forma explícita:

```python
# cloud_mask.py — código atual
mask = (
    scl.neq(1)    # saturado/defeituoso
    .And(scl.neq(3))    # sombra de nuvem
    .And(scl.neq(8))    # nuvem média prob
    .And(scl.neq(9))    # nuvem alta prob
    .And(scl.neq(10))   # cirrus
)
```

Classes **não removidas**: 2 (dark area), 4 (VEGETATION), 5 (not vegetated),
6 (WATER), 7 (UNCLASSIFIED), 11 (snow/ice).

A retenção de SCL=4 foi introduzida justamente porque bloom moderado de
cianobactérias tem espectro próximo ao da vegetação rasteira e o Sen2Cor o
classifica como VEGETATION. Isso já endereça parte do problema original.

---

## Causa raiz remanescente — SCL=8/9 em bloom intenso

A retenção de classe 4 protege blooms de intensidade moderada. Blooms densos
(NDCI > 0,20 — nível crítico) têm reflectância NIR tão alta que o Sen2Cor os
classifica como **SCL=8 (nuvem média prob)** ou **SCL=9 (nuvem alta prob)**, e
não como SCL=4. Esses pixels ainda são removidos pelo `cloud_mask_s2`.

Consequência: o pixel entra na coleção filtrada já sem dado → `water_mask` nunca
avalia esses pixels → tile transparente exatamente onde o bloom é mais intenso.

Este é o problema de causa raiz para o evento de janeiro/2024.

---

## Causa secundária — water_mask falha em bloom muito intenso

Para pixels que sobrevivem à máscara SCL (ex.: SCL=4 ou SCL=6 em borda de bloom),
a `water_mask` pode ainda excluí-los:

```python
# band_math.py — water_mask() atual
# threshold padrão = -0.2 (parâmetro default da função em band_math.py)
ndwi_mask = composite.select("NDWI").gt(threshold)   # -0.2
fai_mask  = composite.select("FAI").gt(0)
return composite.updateMask(ndwi_mask.Or(fai_mask))
```

Em bloom intenso:
- **NDWI** pode cair a −0,4 / −0,5 (B8 NIR muito alto) → falha o critério NDWI > −0,2
- **FAI** = B8 − (B4 + (B11−B4) × 0,179) — quando B11 (SWIR) sobe levemente junto
  com B8, o `nir_baseline` sobe e FAI pode ficar próximo de zero ou negativo →
  falha o critério FAI > 0

Ambos os critérios falham simultaneamente → pixel mascarado mesmo sem nuvem.

> **Nota:** o docstring do `tiles_worker.py` menciona threshold −0,1, mas o código
> chama `water_mask(composite)` sem argumento, usando o padrão −0,2 de `band_math.py`.
> O docstring está desatualizado e deve ser corrigido.

---

## Verificações no banco

### Existem ImageRecords para janeiro/2024?

```sql
SELECT data, cloud_pct, n_pixels, ndci_mean, ndci_p90
FROM ndci_image_records
WHERE lagoa = 'Lagoa do Peixoto'
  AND ano = 2024 AND mes = 1
ORDER BY data;
```

- **Zero linhas** → o `stats_worker` descartou todas as cenas antes mesmo de gerar
  tile (CLOUDY_PIXEL_PERCENTAGE ≥ 20 % ou n_pixels < 300). Bloom não tem registro.
- **Linhas existem** → ImageRecord foi salvo; a transparência é exclusiva do tile.
  Nesse caso, o ImageRecord tem `ndci_mean` calculado? Se sim, o dado está correto
  e o problema é apenas de visualização.

### Existem tiles para essas datas?

```sql
SELECT index_key, data, expires_at
FROM ndci_map_tiles
WHERE lagoa = 'Lagoa do Peixoto'
  AND ano = 2024 AND mes = 1
ORDER BY data;
```

*(a tabela `ndci_map_tiles` usa `data DATE` como chave por imagem individual)*

---

## Como verificar no GEE Code Editor

```javascript
var lagoa = ee.Geometry.Polygon([[
  [-50.248664, -29.871184], [-50.248598, -29.874336],
  [-50.247782, -29.875848], [-50.245891, -29.877761],
  [-50.244210, -29.878421], [-50.243550, -29.880717],
  [-50.239831, -29.882773], [-50.238194, -29.882915],
  [-50.236888, -29.882394], [-50.236968, -29.878394],
  [-50.236286, -29.875188], [-50.236705, -29.874376],
  [-50.236393, -29.871942], [-50.231782, -29.867014],
  [-50.230199, -29.865980], [-50.231805, -29.862421],
  [-50.233142, -29.861770], [-50.235095, -29.860196],
  [-50.237040, -29.857476], [-50.238654, -29.857507],
  [-50.239746, -29.858074], [-50.242221, -29.860045],
  [-50.241387, -29.861663], [-50.241115, -29.863612],
  [-50.240527, -29.864481], [-50.240585, -29.867375],
  [-50.241160, -29.869614], [-50.242560, -29.870314],
  [-50.245900, -29.870256], [-50.247153, -29.869609],
  [-50.248664, -29.871184]
]]);

var col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterDate('2024-01-01', '2024-01-31')
  .filterBounds(lagoa);

print('Datas disponíveis:', col.aggregate_array('system:time_start')
  .map(function(t){ return ee.Date(t).format('YYYY-MM-dd'); }));

// Para a imagem suspeita — verificar distribuição SCL
var img = ee.Image(col.toList(col.size()).get(0));
Map.addLayer(img.select('SCL'), {min:0, max:11}, 'SCL');
Map.centerObject(lagoa, 14);
// SCL=8 ou 9 sobre a lagoa → bloom mascarado como nuvem

// Verificar também NDWI e FAI após SCL mask
var scl = img.select('SCL');
var mask = scl.neq(1).And(scl.neq(3)).And(scl.neq(8))
              .And(scl.neq(9)).And(scl.neq(10));
var masked = img.updateMask(mask);
var ndwi = masked.normalizedDifference(['B3','B8']).rename('NDWI');
var nir_baseline = masked.select('B4').add(
  masked.select('B11').subtract(masked.select('B4')).multiply(0.179)
);
var fai = masked.select('B8').subtract(nir_baseline).rename('FAI');

Map.addLayer(ndwi, {min:-0.6, max:0.4, palette:['red','white','blue']}, 'NDWI');
Map.addLayer(fai,  {min:-0.05, max:0.1, palette:['red','white','green']}, 'FAI');
// Pixels com NDWI < -0.2 E FAI < 0 = transparentes no tile mesmo sem nuvem
```

---

## Estratégia de correção

O problema tem **dois vetores independentes** que precisam de abordagem separada:

### Vetor 1 — SCL=8/9 mascarando bloom intenso (causa raiz)

**Opção A — SCL diferenciado dentro da lagoa:**
Aplicar máscara SCL completa apenas fora do polígono da lagoa; dentro, remover
apenas SCL=1 (saturado) e SCL=3 (sombra). Pixels de nuvem real dentro da lagoa
são raros; o risco de contaminação é baixo se o buffer negativo estiver ativo.

```python
# cloud_mask.py — variante com máscara espacialmente adaptativa
def cloud_mask_s2_water(img, geom_water):
    scl = img.select('SCL')
    # Máscara permissiva: só remove saturado e sombra dentro da água
    mask_water = scl.neq(1).And(scl.neq(3))
    # Máscara completa fora da geometria
    mask_land = scl.neq(1).And(scl.neq(3)).And(scl.neq(8)) \
                          .And(scl.neq(9)).And(scl.neq(10))
    is_water = ee.Image.constant(1).clip(geom_water).unmask(0)
    final_mask = is_water.where(is_water.eq(0), mask_land).where(is_water.eq(1), mask_water)
    return img.updateMask(final_mask)
```

**Opção B — NDCI como fallback de desbloqueio:**
Após a máscara SCL, desmascarar pixels onde NDCI > 0,10 dentro da lagoa
(limiar de floração), mesmo que tenham sido removidos pelo SCL.
Mais simples de implementar, mas matematicamente circular (calcula NDCI
para decidir se mantém o pixel de NDCI).

### Vetor 2 — water_mask em bloom intenso (causa secundária, relevante só se Vetor 1 resolvido)

Relaxar o threshold exclusivamente no `tiles_worker` (visualização) sem afetar
os stats:

```python
# tiles_worker.py — linha 160
# atual (usa padrão -0.2):
water_img = water_mask(composite).clip(geom)

# proposta (-0.5 garante retenção de bloom com NDWI até -0.5):
water_img = water_mask(composite, threshold=-0.5).clip(geom)
```

Threshold −0,5 retém bloom intenso (NDWI −0,4 a −0,5) sem risco de incluir
pixels de terra seca (buffer negativo de 30 m da Lagoa do Peixoto já cobre isso).

---

## Correção imediata recomendada

Dado que o Vetor 1 é a causa raiz e requer mais teste, a sequência sugerida:

1. **Aplicar Vetor 2** (threshold −0,5 no `tiles_worker`) — melhoria imediata sem
   risco para os stats; válida para blooms que passam pelo SCL como SCL=4.
2. **Reprocessar tiles de jan/2024**:

```bash
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2024&ano_fim=2024&force=true"
```

3. **Verificar no GEE** se transparência persiste — se sim, o problema é SCL=8/9
   e o Vetor 1 (Opção A) deve ser implementado e testado.

4. **Corrigir docstring desatualizado** em `tiles_worker.py` (linha 15):
   trocar `"(NDWI > -0.1)"` por `"(NDWI > -0.2)"`.

---

## Critério de sucesso

Após cada intervenção, verificar:

```sql
-- Antes/depois: quantos tiles válidos existem para jan/2024 na Lagoa do Peixoto
SELECT data, tile_url IS NOT NULL AS tem_tile
FROM ndci_image_records ir
LEFT JOIN ndci_map_tiles mt
  ON mt.lagoa = ir.lagoa
 AND mt.data  = ir.data
 AND mt.index_key = 'ndci'
 AND mt.satellite = 'sentinel2'
WHERE ir.lagoa = 'Lagoa do Peixoto'
  AND ir.ano = 2024 AND ir.mes = 1
ORDER BY ir.data;
```

E visualmente: o tile da data com bloom deve mostrar pixels coloridos (NDCI alto)
exatamente onde o eyefish mostra a pluma.
