# Diagnóstico: Harmonização das Séries para Mann-Kendall e CUSUM

**Data:** 2026-04-29
**Contexto:** Consultas ao banco `ndci` revelaram dois problemas estruturais que distorcem
os resultados dos testes estatísticos — um no estimador de baseline do CUSUM e outro
na composição sazonal do Mann-Kendall. Ambos têm a mesma raiz: valores extremos nas
primeiras observações do arquivo Sentinel-2 (julho-agosto 2017).

---

## Sumário dos problemas

| # | Problema | Teste afetado | Impacto | Arquivo corrigido |
|---|---|---|---|---|
| 1 | Baseline CUSUM calculado com `mean/std` clássico — sensível a outliers | CUSUM | Alto | `analytics/cusum.py` |
| 2 | CUSUM acumula durante o próprio período de baseline (circularidade) | CUSUM | Alto | `analytics/cusum.py` |
| 3 | Outlier extremo no início da série domina S de uma season inteira | Mann-Kendall | Médio | `analytics/mann_kendall.py` |
| 4 | Warnings de contaminação não expostos na API | Ambos | Baixo | `api/routers/analytics.py` |

---

## Observações que evidenciaram os problemas

### Julho/Agosto 2017 — início de série anômalo

```sql
SELECT lagoa, data, ndci_mean, ndci_p10, ndci_p90, n_pixels, cloud_pct
FROM ndci_image_records
WHERE data BETWEEN '2017-07-01' AND '2017-09-30'
ORDER BY lagoa, data;
```

| Lagoa | Data | NDCI | P10 | P90 | Cloud% |
|---|---|---|---|---|---|
| **Lagoa do Peixoto** | 2017-07-29 | **+0.2231** | 0.0214 | 0.4670 | 0.0% |
| **Lagoa do Peixoto** | 2017-08-23 | **+0.1815** | 0.1454 | 0.2237 | 0.0% |
| **Lagoa Caconde** | 2017-07-29 | **−0.3531** | −0.5670 | −0.1446 | 0.0% |
| Lagoa Itapeva | 2017-07-29 | −0.0889 | normal | normal | 0.0% |
| Lagoa dos Barros | 2017-07-29 | −0.0013 | normal | normal | 0.0% |

Interpretação:
- **Peixoto jul/ago 2017**: valores no limiar "crítico" (> 0,20), com spread P10–P90 de 0,446 —
  heterogeneidade espacial extrema; possível bloom real no início do arquivo.
- **Caconde jul 2017**: valor mais negativo de toda a série (−0,353) com cloud = 0%; possível
  anomalia de abertura do arquivo GEE ou condição transitória de baixa reflectância.
- Ambos são os valores **mais extremos do respectivo mês em toda a série histórica**, e ocorrem
  na **primeira observação** de cada lagoa.

---

## Problema 1 — Estimador clássico do CUSUM inflado por outliers

### Baseline atual (primeiros 24 obs válidos da Lagoa do Peixoto)

```sql
WITH bl AS (
  SELECT ndci_mean, ROW_NUMBER() OVER (ORDER BY data) rn, data
  FROM ndci_image_records
  WHERE lagoa = 'Lagoa do Peixoto' AND ndci_mean IS NOT NULL
)
SELECT ROUND(AVG(ndci_mean)::numeric,5) AS mu0,
       ROUND(STDDEV(ndci_mean)::numeric,5) AS sigma,
       ROUND((4*STDDEV(ndci_mean))::numeric,5) AS h
FROM bl WHERE rn <= 24;
```

| Estimador | μ₀ | σ | h = 4σ |
|---|---|---|---|
| Mean / Std (atual) | 0.03429 | 0.07746 | **0.310** |
| Mediana / MAD×1,4826 (fix) | ~0.015 | ~0.054 | **~0.216** |

O `h` clássico é **+43% maior** do que o robusto para a Lagoa do Peixoto.
Para a Lagoa Caconde, o impacto é ainda maior: `h` passa de **0,456** para **~0,260**.

### Consequência para os alarmes

Com `h = 0.310`, o CUSUM da Lagoa do Peixoto só dispara quando
C⁺ acumula pelo menos 0,31 acima de μ₀ = 0,034.
Com o estimador robusto (`h ≈ 0.216`, μ₀ ≈ 0.015), a sensibilidade aumenta:
eventos de bloom acima de ~0,015 + 0,108 = 0,123 de desvio acumulado são detectados
mais cedo.

---

## Problema 2 — Circularidade: CUSUM roda sobre o próprio período de baseline

O loop atual começa em `i = 0` (primeira observação) enquanto o baseline é também
calculado das primeiras N observações. Resultado: C⁺ começa com valor não-zero
**no dia da primeira observação**:

```
2017-07-29  v = 0.2231,  μ₀ = 0.034,  k = 0.039
C⁺[0] = max(0, 0 + (0.223 − 0.034) − 0.039) = 0.150  ← acumulação circular
```

O CUSUM acumula até 0,259 no segundo ponto (agosto 2017), depois decai conforme os
valores de 2018–2019 baixam. Ele atinge zero apenas em maio/2019. A "fase de
monitoramento real" só começa de fato em meados de 2019, mas o gráfico mostra
acumulação desde o primeiro dia.

### Efeito na detecção

O primeiro alarme real (eleção em 2020-01-05) provavelmente seria detectado
alguns pontos antes com a correção, porque C⁺ parte de zero em outubro/2019
em vez de zero após a drenagem orgânica pós-2017.

---

## Problema 3 — Outlier de início de série domina o S sazonal no Mann-Kendall

Distribuição de julho na Lagoa do Peixoto (17 observações):

```
2017: +0.2231  ← máximo absoluto do mês julho em toda a série
2019:  −0.061, −0.081
2020:  +0.001, +0.049, −0.045
2021:  −0.028, −0.051, −0.039, +0.015, +0.010
2022:  −0.056, −0.062
2024:  −0.081, −0.040
2025:  −0.039, −0.028
```

No cálculo do S sazonal para julho:
- Todos os **16 pares `(2017, ano_posterior)`** contribuem `sgn(v_posterior − v_2017) = −1`
- Contribuição desse único ponto para S_julho: **−16** (máximo negativo possível)
- O resultado é um sinal artificial de **tendência decrescente** em julho

Para a Lagoa Caconde em julho, o efeito é oposto: 2017 é o mínimo absoluto → todos os
pares (2017, posterior) contribuem +1 → sinal artificial de **tendência crescente**.

O Mann-Kendall não-paramétrico usa ranks (função sinal) e é teoricamente robusto a
outliers, mas apenas quando o outlier está em meio a séries longas. Com apenas
1 observação em 2017 por season e esse valor sendo o extremo absoluto, o outlier
domina o S sazonal de forma irrecuperável sem filtro.

### Critério de remoção: modified z-score (Iglewicz & Hoaglin, 1993)

```
M_i = 0.6745 × |x_i − median(x_season)| / MAD(x_season)
```

Threshold: `|M_i| > 3.5`. Só aplicado quando a season tem ≥ 5 observações,
e apenas se restar pelo menos 3 pontos após remoção.

Para julho/Peixoto (mediana ≈ −0.040, MAD ≈ 0.018):
```
M_2017 = 0.6745 × |0.2231 − (−0.040)| / 0.018 = 0.6745 × 14.6 = 9.8  >> 3.5 ✓
```

---

## Fixes implementados

### Fix 1 — CUSUM: baseline robusto (mediana + MAD×1,4826)

**Arquivo:** `analytics/cusum.py`

Substituição de `np.mean` / `np.std` por `np.median` / `MAD × 1.4826`.
O fator 1,4826 = 1/Φ⁻¹(0,75) torna o MAD um estimador consistente de σ para
distribuições normais.

### Fix 2 — CUSUM: monitoramento começa após o baseline

**Arquivo:** `analytics/cusum.py`

O loop agora emite `cusum_pos[i] = 0.0 / cusum_neg[i] = 0.0` para todas as
observações dentro do período de baseline (`i ≤ last_baseline_idx`). A
acumulação de C⁺ e C⁻ só começa na observação seguinte ao último ponto do
baseline. `last_reset_pos` e `last_reset_neg` são inicializados com
`last_baseline_idx` para que o shift-start seja estimado corretamente.

### Fix 3 — CUSUM: aviso de contaminação no baseline

**Arquivo:** `analytics/cusum.py`

Após estimar o baseline, cada observação do baseline é testada com o modified
z-score robusto. Se `|M_i| > 3.5`, a observação é listada em
`outliers_baseline` e `aviso_baseline_contaminado = True` é emitido.
O campo `baseline_estimador = "mediana/MAD"` informa o método utilizado.

### Fix 4 — Mann-Kendall: filtro de outlier sazonal antes de S

**Arquivo:** `analytics/mann_kendall.py`

Função `_seasonal_outlier_filter()` aplicada em cada season antes do cálculo
de S. Remove observações com `|M_i| > 3.5`. Requires `n_season ≥ 5` e mantém
pelo menos 3 pontos por season. Observações removidas são registradas em
`MKResult.outliers` e sumarizadas em `MKResult.avisos`.

### Fix 5 — API: expõe warnings nos endpoints

**Arquivo:** `api/routers/analytics.py`

- `/trend`: resposta inclui `n_outliers_removidos`, `outliers`, `avisos` por índice
- `/changepoint`: resposta inclui `aviso_baseline_contaminado`, `outliers_baseline`,
  `baseline_estimador`

---

## Impacto esperado nos resultados

| Lagoa | Teste | Antes | Depois |
|---|---|---|---|
| Peixoto | CUSUM h | 0,310 | ~0,216 (−30%) |
| Caconde | CUSUM h | 0,456 | ~0,260 (−43%) |
| Peixoto | CUSUM acumulação | começa em jul/2017 | começa em out/2019 |
| Peixoto | MK julho | tendência decrescente (dominada por 2017) | resultado sem viés de outlier |
| Caconde | MK julho | tendência crescente (dominada por 2017) | resultado sem viés de outlier |

---

## Consultas de verificação pós-fix

```sql
-- Confirmar que CUSUM não acumula durante o baseline
-- (checar via API: series.cusum_pos[0..baseline.n_obs-1] devem ser todos 0.0)

-- Verificar distribuição dos outliers identificados no Mann-Kendall
-- Espera-se: jul/2017 Peixoto e jul/2017 Caconde como outliers removidos

-- Verificar melhoria na detecção: primeiro alarme de elevação na Peixoto
-- Antes: 2020-01-05   Depois: possivelmente um ponto anterior (dez/2019)
```

---

## Referências metodológicas

- Iglewicz, B.; Hoaglin, D.C. (1993). *How to Detect and Handle Outliers.*
  ASQ Quality Press. — Modified z-score para outlier detection robusto.
- Page, E.S. (1954). Continuous inspection schemes. *Biometrika* 41:100–115.
- Hampel, F.R. (1974). The influence curve and its role in robust estimation.
  *JASA* 69(346):383–393. — Fundamento teórico do MAD como estimador robusto.
- Hirsch, R.M., Slack, J.R., Smith, R.A. (1982). Techniques of trend analysis
  for monthly water quality data. *Water Resour. Res.* 18(1):107–121.
