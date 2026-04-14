-- Migração 001: tabela de qualidade da água
-- Sistema NDCI/Sentinel-2 — independente do eyefish
--
-- Equivalente ao gee_qualidade_agua do eyefish, mas com colunas
-- `satellite` e `index_key` para suportar múltiplos satélites/índices.

CREATE TABLE IF NOT EXISTS ndci_water_quality (
    id           SERIAL PRIMARY KEY,
    satellite    VARCHAR(50)  NOT NULL,        -- ex: 'sentinel2'
    lagoa        VARCHAR(100) NOT NULL,
    ano          SMALLINT     NOT NULL,
    mes          SMALLINT     NOT NULL,         -- 1..12
    ndci_mean    FLOAT,                         -- NDCI médio — TARGET do ML
    ndci_p90     FLOAT,                         -- percentil 90 (pior pixel)
    ndti_mean    FLOAT,                         -- turbidez (NDTI)
    fai_mean     FLOAT,                         -- Floating Algae Index
    ndwi_mean    FLOAT,                         -- disponibilidade hídrica
    n_pixels     INTEGER,                       -- pixels válidos no mês
    collected_at TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_water_quality UNIQUE (satellite, lagoa, ano, mes)
);

CREATE INDEX IF NOT EXISTS ix_wq_lagoa_periodo
    ON ndci_water_quality (lagoa, ano, mes);

CREATE INDEX IF NOT EXISTS ix_wq_satellite
    ON ndci_water_quality (satellite);

COMMENT ON TABLE  ndci_water_quality           IS 'Estatísticas mensais de qualidade da água por lagoa (Sentinel-2 via GEE).';
COMMENT ON COLUMN ndci_water_quality.ndci_mean IS 'Normalized Difference Chlorophyll Index médio do mês — proxy clorofila-a/cianobactérias.';
COMMENT ON COLUMN ndci_water_quality.ndci_p90  IS 'Percentil 90 do NDCI no mês (pior pixel — alerta de floração localizada).';
COMMENT ON COLUMN ndci_water_quality.ndti_mean IS 'Normalized Difference Turbidity Index — partículas em suspensão.';
COMMENT ON COLUMN ndci_water_quality.fai_mean  IS 'Floating Algae Index — tapete de algas na superfície.';
COMMENT ON COLUMN ndci_water_quality.ndwi_mean IS 'Normalized Difference Water Index — disponibilidade de água.';
COMMENT ON COLUMN ndci_water_quality.n_pixels  IS 'Pixels válidos usados (excluídos: nuvem, sombra, terra). Meses com <100 pixels têm dado pouco confiável.';
