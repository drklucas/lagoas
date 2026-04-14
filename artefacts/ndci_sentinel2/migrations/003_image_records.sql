-- Migração 003: tabela de registros por imagem individual
-- Sistema NDCI/Sentinel-2 — Pi & Guasselli (SBSR 2025)
--
-- Fonte primária de dados: cada linha representa uma cena Sentinel-2 individual
-- que passou pelos filtros de qualidade (CLOUDY_PIXEL_PERCENTAGE < 20%,
-- pixels válidos >= mínimo por lagoa).
-- Os agregados mensais em ndci_water_quality são derivados desta tabela.

CREATE TABLE IF NOT EXISTS ndci_image_records (
    id          SERIAL PRIMARY KEY,
    satellite   VARCHAR(50)  NOT NULL,        -- ex: 'sentinel2'
    lagoa       VARCHAR(100) NOT NULL,
    data        DATE         NOT NULL,        -- data da cena (YYYY-MM-DD)
    ano         SMALLINT     NOT NULL,        -- extraído de data
    mes         SMALLINT     NOT NULL,        -- extraído de data (1..12)

    -- Índices calculados na geometria erodida (após buffer negativo)
    ndci_mean   FLOAT,                        -- NDCI médio da imagem
    ndci_p90    FLOAT,                        -- percentil 90 (detecção de bloom)
    ndci_p10    FLOAT,                        -- percentil 10 (água mais limpa)
    ndti_mean   FLOAT,                        -- turbidez (NDTI)
    ndwi_mean   FLOAT,                        -- disponibilidade hídrica
    fai_mean    FLOAT,                        -- Floating Algae Index

    n_pixels    INTEGER,                      -- pixels válidos após máscaras
    cloud_pct   FLOAT,                        -- CLOUDY_PIXEL_PERCENTAGE da cena
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_image_record UNIQUE (satellite, lagoa, data)
);

CREATE INDEX IF NOT EXISTS ix_ir_lagoa_data
    ON ndci_image_records (lagoa, data);

CREATE INDEX IF NOT EXISTS ix_ir_lagoa_periodo
    ON ndci_image_records (lagoa, ano, mes);

CREATE INDEX IF NOT EXISTS ix_ir_satellite
    ON ndci_image_records (satellite);

COMMENT ON TABLE  ndci_image_records             IS 'Estatísticas por imagem Sentinel-2 individual por lagoa. Fonte primária para série temporal de NDCI.';
COMMENT ON COLUMN ndci_image_records.data        IS 'Data de aquisição da cena (YYYY-MM-DD).';
COMMENT ON COLUMN ndci_image_records.ndci_mean   IS 'NDCI médio calculado na geometria erodida (buffer negativo aplicado).';
COMMENT ON COLUMN ndci_image_records.ndci_p90    IS 'Percentil 90 do NDCI — detecta bloom localizado na imagem.';
COMMENT ON COLUMN ndci_image_records.ndci_p10    IS 'Percentil 10 do NDCI — referência de água mais limpa na imagem.';
COMMENT ON COLUMN ndci_image_records.cloud_pct   IS 'CLOUDY_PIXEL_PERCENTAGE dos metadados Sentinel-2. Imagens > 20% descartadas no pipeline.';
COMMENT ON COLUMN ndci_image_records.n_pixels    IS 'Pixels válidos após cloud mask + water mask. Imagens abaixo do mínimo por lagoa são descartadas.';
