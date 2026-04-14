-- Migração 002: cache de tiles visuais GEE
-- Sistema NDCI/Sentinel-2 — independente do eyefish
--
-- Equivalente ao gee_map_tiles do eyefish, mas com colunas
-- `satellite` e `index_key` para suportar múltiplos satélites/índices.

CREATE TABLE IF NOT EXISTS ndci_map_tiles (
    id           SERIAL PRIMARY KEY,
    satellite    VARCHAR(50)  NOT NULL,         -- ex: 'sentinel2'
    index_key    VARCHAR(50)  NOT NULL,          -- ex: 'ndci', 'ndti'
    ano          SMALLINT     NOT NULL,
    mes          SMALLINT     NOT NULL,          -- sempre mensal para água
    lagoa        VARCHAR(100) NOT NULL,
    tile_url     VARCHAR(700) NOT NULL,          -- URL template {z}/{x}/{y}
    map_id       VARCHAR(400) NOT NULL,          -- GEE map resource ID
    vis_min      FLOAT,
    vis_max      FLOAT,
    palette      JSONB,                          -- array de strings hex
    bounds       JSONB,                          -- [west, south, east, north]
    generated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMP,                      -- ~23 h após geração

    CONSTRAINT uq_map_tile UNIQUE (satellite, index_key, ano, mes, lagoa)
);

CREATE INDEX IF NOT EXISTS ix_map_tiles_index_ano
    ON ndci_map_tiles (index_key, ano);

CREATE INDEX IF NOT EXISTS ix_map_tiles_expires
    ON ndci_map_tiles (expires_at);

CREATE INDEX IF NOT EXISTS ix_map_tiles_lagoa
    ON ndci_map_tiles (lagoa);

COMMENT ON TABLE  ndci_map_tiles             IS 'Cache de tile URLs do GEE para visualização pixel-level por índice e período.';
COMMENT ON COLUMN ndci_map_tiles.tile_url    IS 'URL template XYZ: .../tiles/{z}/{x}/{y} — servida via proxy autenticado.';
COMMENT ON COLUMN ndci_map_tiles.map_id      IS 'GEE Map Resource ID. Expira ~24 h após geração.';
COMMENT ON COLUMN ndci_map_tiles.expires_at  IS 'Timestamp de expiração (TTL conservador de 23 h). Worker de refresh regenera antes.';
