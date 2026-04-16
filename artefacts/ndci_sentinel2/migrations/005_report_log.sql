-- Tabela de log de relatórios enviados.
-- Garante idempotência: cada período ISO (ex: "2026-W15") só é enviado uma vez.

CREATE TABLE IF NOT EXISTS ndci_report_log (
    id             SERIAL PRIMARY KEY,
    report_period  VARCHAR(20)  NOT NULL,           -- ex: "2026-W15"
    recipients     TEXT         NOT NULL,           -- lista separada por vírgula
    status         VARCHAR(20)  NOT NULL,           -- sent | skipped | error
    error_message  TEXT,
    sent_at        TIMESTAMP    NOT NULL DEFAULT now(),

    CONSTRAINT uq_report_period UNIQUE (report_period)
);

CREATE INDEX IF NOT EXISTS ix_report_log_sent_at
    ON ndci_report_log (sent_at DESC);
