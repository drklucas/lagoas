# Diagnóstico: Pluma NDCI Janeiro/2024 — Lagoa do Peixoto

**Observação:** Tile do eyefish (composição mensal) mostra bloom intenso (NDCI crítico)
em janeiro/2024. No lagoas, a região do bloom aparece **transparente** nos tiles
desse período.

---

## O que causa transparência num tile

Um pixel fica transparente quando é mascarado em qualquer etapa do pipeline. O pipeline
do lagoas aplica duas máscaras em sequência:

```
S2_SR_HARMONIZED → cloud_mask_s2 (SCL) → add_water_indices → mosaic → water_mask → clip(geom)
```

Se o pixel é removido na primeira etapa (SCL), ele já chega sem dado para a segunda.

---

## Suspeito 1 — SCL classifica o bloom como nuvem (mais provável)

Blooms densos de cianobactérias têm altíssima reflectância no NIR. O algoritmo SCL
do Sentinel-2 frequentemente classifica esses pixels como **SCL=8 (nuvem média)** ou
**SCL=9 (nuvem alta)**. O `cloud_mask_s2` remove exatamente essas classes:

```python
# cloud_mask.py
mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
return img.updateMask(mask)
```

O `cloud_mask_s2` é aplicado **antes** do cálculo dos índices, tanto no `stats_worker`
quanto no `tiles_worker`. Resultado: pixels de bloom mascarados como nuvem → NDCI
nunca calculado → pixel transparente no tile.

### Por que o eyefish não sofre o mesmo problema

O eyefish usa o mesmo `cloud_mask_s2`, mas trabalha com **composição mensal (mediana)**.
Nos dias sem bloom, os mesmos pixels são água limpa (SCL=6) e contribuem normalmente
para a mediana. O pico do bloom pode estar mascarado, mas a mediana do mês ainda
captura NDCI elevado das demais imagens. O lagoas, por trabalhar imagem a imagem,
não tem esse "resgate" pela mediana.

### Como verificar no GEE Code Editor

```javascript
var lagoa = ee.Geometry.Polygon([[
  [-50.248506, -29.869936], [-50.241872, -29.869051],
  [-50.242280, -29.860022], [-50.236564, -29.857366],
  [-50.231052, -29.861969], [-50.231052, -29.868254],
  [-50.233910, -29.874007], [-50.236870, -29.883035],
  [-50.243913, -29.881176], [-50.249629, -29.874804],
  [-50.247588, -29.869493], [-50.248506, -29.869936]
]]);

var col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterDate('2024-01-01', '2024-01-31')
  .filterBounds(lagoa);

// Ver a distribuição de classes SCL sobre a lagoa para cada imagem
var datas = col.aggregate_array('system:time_start')
  .map(function(t){ return ee.Date(t).format('YYYY-MM-dd'); });

print('Datas disponíveis:', datas);

// Para a imagem suspeita: visualizar a banda SCL
// (trocar o índice para a data com bloom)
var img = ee.Image(col.toList(col.size()).get(0));
Map.addLayer(img.select('SCL'), {min:0, max:11}, 'SCL');
Map.centerObject(lagoa, 14);
// SCL=8 ou 9 sobre a lagoa = bloom mascarado como nuvem
```

---

## Suspeito 2 — Water mask não retém pixels de bloom intenso

Para bloom denso, B8 (NIR) sobe muito, tornando o NDWI muito negativo
(pode chegar a −0.4 ou pior). O threshold de −0.2 não é suficiente:

```python
# band_math.py — water_mask()
ndwi_mask = composite.select("NDWI").gt(threshold)  # threshold=-0.2
fai_mask  = composite.select("FAI").gt(0)
return composite.updateMask(ndwi_mask.Or(fai_mask))
```

O FAI deveria compensar via `fai_mask`, mas em blooms muito intensos B11 (SWIR)
também sobe levemente, elevando o `nir_baseline` e podendo fazer FAI ficar próximo
de zero ou negativo — falhando o critério `FAI > 0`.

Este suspeito é secundário: se o Suspeito 1 for a causa, esses pixels já chegam
mascarados pelo SCL antes da water mask ser avaliada.

---

## Verificações no banco (rodar no computador com Docker)

### Existem ImageRecords para janeiro/2024?

```sql
SELECT data, cloud_pct, n_pixels, ndci_mean, ndci_p90
FROM ndci_image_records
WHERE lagoa = 'Lagoa do Peixoto'
  AND ano = 2024 AND mes = 1
ORDER BY data;
```

- **Zero linhas** → o `stats_worker` filtrou todas as cenas
  (verificar `CLOUDY_PIXEL_PERCENTAGE` no GEE — threshold atual é 20%)
- **Linhas existem** → ImageRecord foi salvo, mas tile não gerado ou bloom mascarado

### Existem tiles para essas datas?

```sql
SELECT index_key, data, expires_at
FROM ndci_map_tiles
WHERE lagoa = 'Lagoa do Peixoto'
  AND EXTRACT(YEAR FROM data) = 2024
  AND EXTRACT(MONTH FROM data) = 1
ORDER BY data;
```

---

## Fix recomendado

O problema de transparência no bloom é de **visualização**, não de qualidade de dado.
A correção é relaxar o threshold da water mask exclusivamente no `tiles_worker`,
sem afetar os stats:

```python
# tiles_worker.py — linha ~85
# antes
water_img = water_mask(composite).clip(geom)

# depois
water_img = water_mask(composite, threshold=-0.5).clip(geom)
```

Threshold −0.5 garante que bloom intenso (NDWI −0.4 a −0.5) não seja mascarado.
O FAI `> 0` continua como fallback para casos extremos.

**Limitação:** não resolve o Suspeito 1 (SCL mascarando o bloom como nuvem).
Se após o fix os tiles ainda ficarem transparentes, o problema é o SCL e exige
uma abordagem diferente — aplicar a cloud mask apenas fora do polígono da lagoa,
ou usar uma estratégia de composição alternativa para os tiles.

### Reprocessar após o fix

```bash
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2024&ano_fim=2024&force=true"
```
