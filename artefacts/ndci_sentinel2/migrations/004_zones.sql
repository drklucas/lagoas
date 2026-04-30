-- 004_zones.sql — Adiciona coluna zona às tabelas de registros
-- Compatível com PostgreSQL 16 (produção)
-- Para SQLite (dev local): recriar o banco após a migração

-- ndci_image_records
ALTER TABLE ndci_image_records ADD COLUMN IF NOT EXISTS zona TEXT NOT NULL DEFAULT 'total';

ALTER TABLE ndci_image_records DROP CONSTRAINT IF EXISTS uq_image_record;
ALTER TABLE ndci_image_records ADD CONSTRAINT uq_image_record
    UNIQUE (satellite, lagoa, data, zona);

CREATE INDEX IF NOT EXISTS ix_ir_lagoa_zona ON ndci_image_records (lagoa, zona);

-- ndci_water_quality
ALTER TABLE ndci_water_quality ADD COLUMN IF NOT EXISTS zona TEXT NOT NULL DEFAULT 'total';

ALTER TABLE ndci_water_quality DROP CONSTRAINT IF EXISTS uq_water_quality;
ALTER TABLE ndci_water_quality ADD CONSTRAINT uq_water_quality
    UNIQUE (satellite, lagoa, ano, mes, zona);

CREATE INDEX IF NOT EXISTS ix_wq_lagoa_zona ON ndci_water_quality (lagoa, zona);
