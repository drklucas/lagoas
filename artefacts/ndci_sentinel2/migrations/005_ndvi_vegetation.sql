-- 005_ndvi_vegetation.sql — Tabelas de NDVI no anel de vegetação terrestre
-- Compatível com PostgreSQL 16 (produção) e SQLite (dev local via create_all)

CREATE TABLE IF NOT EXISTS ndvi_vegetation_records (
    id          SERIAL PRIMARY KEY,
    satellite   VARCHAR(50)  NOT NULL,
    lagoa       VARCHAR(100) NOT NULL,
    data        DATE         NOT NULL,
    ano         SMALLINT     NOT NULL,
    mes         SMALLINT     NOT NULL,
    ndvi_mean   FLOAT,
    ndvi_p90    FLOAT,
    ndvi_p10    FLOAT,
    n_pixels    INTEGER,
    cloud_pct   FLOAT,
    created_at  TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_ndvi_record UNIQUE (satellite, lagoa, data)
);

CREATE INDEX IF NOT EXISTS ix_ndvi_lagoa_data    ON ndvi_vegetation_records (lagoa, data);
CREATE INDEX IF NOT EXISTS ix_ndvi_lagoa_periodo ON ndvi_vegetation_records (lagoa, ano, mes);

CREATE TABLE IF NOT EXISTS ndvi_vegetation_monthly (
    id           SERIAL PRIMARY KEY,
    satellite    VARCHAR(50)  NOT NULL,
    lagoa        VARCHAR(100) NOT NULL,
    ano          SMALLINT     NOT NULL,
    mes          SMALLINT     NOT NULL,
    ndvi_mean    FLOAT,
    ndvi_p90     FLOAT,
    ndvi_p10     FLOAT,
    n_pixels     INTEGER,
    collected_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ndvi_monthly UNIQUE (satellite, lagoa, ano, mes)
);

CREATE INDEX IF NOT EXISTS ix_ndvi_monthly_lagoa ON ndvi_vegetation_monthly (lagoa, ano, mes);
