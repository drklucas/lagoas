-- Migration 004: ndci_map_tiles — granularidade mensal → por imagem individual
--
-- Antes: tile_key = satellite|index_key|ano|mes|lagoa  (mediana mensal)
-- Depois: tile_key = satellite|index_key|YYYY-MM-DD|lagoa  (imagem individual)
--
-- Metodologia Pi & Guasselli (SBSR 2025): tiles por data exata de passagem.

BEGIN;

-- Limpa tiles mensais — serão regenerados por imagem após migrate
DELETE FROM ndci_map_tiles;

-- Adiciona coluna de data exata (nullable para compatibilidade de DDL)
ALTER TABLE ndci_map_tiles
  ADD COLUMN IF NOT EXISTS data DATE;

-- Remove constraint mensal e cria constraint por data de imagem
ALTER TABLE ndci_map_tiles DROP CONSTRAINT IF EXISTS uq_map_tile;
ALTER TABLE ndci_map_tiles
  ADD CONSTRAINT uq_map_tile UNIQUE (satellite, index_key, data, lagoa);

-- Atualiza índice de ano (mantém as colunas mas remove o índice antigo de ano/mes)
DROP INDEX IF EXISTS ix_map_tiles_index_ano;
CREATE INDEX IF NOT EXISTS ix_map_tiles_index_data ON ndci_map_tiles (index_key, data);

COMMIT;
