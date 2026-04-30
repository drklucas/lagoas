
-- Regiões geográficas desenhadas para análise espacial (frontend → worker)
-- lagoa NULL = região não ligada a uma lagoa específica (uso futuro)
CREATE TABLE IF NOT EXISTS geo_regions (
    id            SERIAL PRIMARY KEY,
    nome          VARCHAR(100)  NOT NULL,
    descricao     TEXT,
    polygon       JSON          NOT NULL,   -- [[lon, lat], ...]  ordem GEE
    lagoa         VARCHAR(100),             -- NULL = área livre
    categoria     VARCHAR(50)   NOT NULL DEFAULT 'setor_lagoa',
    ativo         BOOLEAN       NOT NULL DEFAULT TRUE,
    min_pixels    INTEGER,                  -- NULL = sistema usa 30 por padrão
    criado_em     TIMESTAMP     NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geo_region UNIQUE (nome, lagoa)
);

CREATE INDEX IF NOT EXISTS ix_geo_regions_lagoa ON geo_regions(lagoa);
CREATE INDEX IF NOT EXISTS ix_geo_regions_ativo ON geo_regions(ativo);
