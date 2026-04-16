# NDCI Sentinel-2 — Monitoramento de Qualidade da Água

Monitoramento contínuo de lagoas costeiras do Litoral Norte do RS via **Normalized Difference Chlorophyll Index (NDCI)** calculado sobre imagens Sentinel-2 do Google Earth Engine (GEE).

Metodologia alinhada com **Pi & Guasselli (SBSR 2025)**: processamento por imagem individual, buffer negativo de borda, máscara de água por NDWI/FAI e percentis P10/P90 por cena.

---

## Arquitetura

```
Sentinel-2 (GEE)
      │
      ▼
┌─────────────────────────────────┐
│  stats_worker.py                │  coleta por imagem → ndci_image_records
│  tiles_worker.py                │  tiles visuais XYZ → ndci_map_tiles
└──────────────┬──────────────────┘
               │
               ▼
        PostgreSQL (pg_data)
               │
        ┌──────┴──────┐
        ▼             ▼
┌───────────────┐  ┌──────────────────────────────────┐
│  FastAPI :8001│  │  scheduler (report_scheduler.py) │
│  frontend     │  │  · coleta diária (ano corrente)  │
│  HTML/CSS/JS  │  │  · boletim semanal por e-mail     │
└───────┬───────┘  └──────────────────────────────────┘
        │
        ▼
  GitHub Pages (estático)
  build_static.py --deploy
```

---

## Lagoas monitoradas

| Lagoa | Município | Pixels mín. |
|---|---|---|
| Lagoa dos Barros | Osório | 2 000 |
| Lagoa do Peixoto | Osório | 300 |
| Lagoa Itapeva | Torres | 2 000 |
| Lagoa dos Quadros | Osório | 3 000 |
| Lagoa de Tramandaí | Tramandaí | 1 000 |
| Lagoa do Armazém | Tramandaí | 1 000 |
| Lagoa Caconde | Osório | 100 |

> Para ativar somente algumas lagoas edite `ACTIVE_LAGOAS` em `config.py`.

---

## Faixas de alerta NDCI

| Status | Intervalo | Interpretação |
|---|---|---|
| Bom | < 0,02 | Clorofila baixa |
| Moderado | 0,02 – 0,10 | Atenção |
| Elevado | 0,10 – 0,20 | Alerta — possível floração |
| Crítico | > 0,20 | Floração de cianobactérias |

Limiar de eflorescência ≈ 14 µg/L (linha de referência no gráfico).

---

## Pré-requisitos

- Docker e Docker Compose
- Conta no [Google Earth Engine](https://earthengine.google.com/) com service account
- Python 3.11+ (apenas para o build estático)

---

## Configuração

```bash
# 1. Clone o repositório
git clone https://github.com/drklucas/lagoas.git
cd lagoas/artefacts/ndci_sentinel2

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com sua senha do Postgres e projeto GEE

# 3. Adicione a chave da service account GEE
mkdir -p credentials
cp /caminho/para/sua/gee-key.json credentials/gee-key.json

# 4. Suba os serviços
docker compose up -d

# 5. Acesse o dashboard
open http://localhost:8001
```

---

## Workers de ingestão

### Coletar estatísticas (NDCI/NDTI/NDWI por imagem)

```bash
# Backfill completo desde 2017
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2017"

# Apenas um ano específico
curl -X POST "http://localhost:8001/api/workers/collect-stats?ano_inicio=2024&ano_fim=2024"

# Forçar re-processamento (sobrescreve registros existentes)
curl -X POST "http://localhost:8001/api/workers/collect-stats?force=true"
```

O worker roda em background — acompanhe o progresso:

```bash
docker compose logs -f api
```

### Gerar tiles visuais XYZ

```bash
curl -X POST "http://localhost:8001/api/workers/generate-tiles?ano_inicio=2024"
```

### Status do banco

```bash
curl http://localhost:8001/api/workers/status
```

---

## Controle de lagoas ativas

Edite `config.py` para limitar quais lagoas o worker processa:

```python
# Processa todas:
ACTIVE_LAGOAS = None

# Apenas Barros e Peixoto:
ACTIVE_LAGOAS = ["Lagoa dos Barros", "Lagoa do Peixoto"]
```

---

## Deploy estático no GitHub Pages

O site pode ser exportado como HTML + JSON estáticos para hospedagem gratuita no GitHub Pages, sem necessidade de servidor.

### Build + deploy em um comando

```bash
# Da raiz do repositório, com a API rodando localmente:
python artefacts/ndci_sentinel2/scripts/build_static.py --deploy
```

O script:
1. Chama a API local e exporta todos os dados como `.json`
2. Copia os assets do frontend com paths ajustados
3. Faz commit e push direto na branch `gh-pages`

### Apenas build local (sem publicar)

```bash
python artefacts/ndci_sentinel2/scripts/build_static.py --out artefacts/ndci_sentinel2/dist

# Teste local:
python -m http.server 3000 --directory artefacts/ndci_sentinel2/dist
```

### Ativar no GitHub

Em **Settings → Pages → Source**, selecione a branch `gh-pages` e pasta `/ (root)`.

O site ficará disponível em `https://drklucas.github.io/lagoas/`.

---

## API — endpoints principais

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/water-quality` | Série mensal por lagoa |
| GET | `/api/water-quality/current` | Status atual de cada lagoa |
| GET | `/api/water-quality/{lagoa}/images` | Série por imagem individual |
| POST | `/api/workers/collect-stats` | Inicia coleta de estatísticas |
| POST | `/api/workers/generate-tiles` | Gera tiles visuais |
| GET | `/api/workers/status` | Contagem de registros no banco |
| POST | `/api/notifications/trigger-report` | Dispara relatório por e-mail manualmente |
| GET | `/api/notifications/report-log` | Histórico de relatórios enviados |
| GET | `/docs` | Documentação interativa (Swagger UI) |

---

## Boletim semanal por e-mail

O sistema envia automaticamente um boletim HTML toda segunda-feira com o status de qualidade da água de cada lagoa, baseado nas observações mais recentes do satélite.

### Como funciona

O serviço `scheduler` (container Docker separado) executa dois jobs:

| Job | Horário | O que faz |
|---|---|---|
| `collect_recent` | Diário, 06h UTC | Coleta dados GEE **somente do ano corrente** — nunca backfill histórico |
| `send_weekly_report` | Toda segunda, 08h UTC | Gera o HTML e envia por SMTP para os destinatários configurados |

O relatório busca apenas observações dos **últimos 21 dias** (configurável via `REPORT_LOOKBACK_DAYS`), alinhado com a revisita do Sentinel-2 (~5 dias). Lagoas sem passagem recente válida aparecem com aviso "Sem dados recentes" em vez de dados desatualizados.

A idempotência é garantida pela tabela `ndci_report_log`: cada período ISO (ex: `2026-W15`) é enviado no máximo uma vez, mesmo que o container reinicie.

### Configuração

**1. Preencha as variáveis SMTP no `.env`:**

```bash
# Servidor de saída — exemplos:
#   Gmail (com App Password):  smtp.gmail.com  porta 587
#   SendGrid:                  smtp.sendgrid.net  porta 587  user=apikey
#   Office 365:                smtp.office365.com  porta 587
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu_email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx   # App Password do Gmail (não a senha da conta)
SMTP_FROM=                          # opcional — usa SMTP_USER se vazio

# Lista de destinatários separados por vírgula
REPORT_RECIPIENTS=gestor@prefeitura.gov.br,pesquisador@ifrs.edu.br
```

> **Gmail**: acesse [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), crie uma "App Password" para "Mail" e use-a em `SMTP_PASSWORD`. A autenticação de dois fatores deve estar ativada na conta.

> **SendGrid**: crie uma API Key em sendgrid.com, use `apikey` como `SMTP_USER` e a chave como `SMTP_PASSWORD`.

**2. Suba os serviços (o scheduler sobe junto):**

```bash
docker compose up -d

# Confirme que o scheduler está rodando:
docker compose ps
docker compose logs scheduler
```

**3. Teste o envio imediatamente** (sem esperar a segunda-feira):

```bash
# Gera e envia agora mesmo, ignorando a verificação de idempotência
curl -X POST "http://localhost:8001/api/notifications/trigger-report?force=true"

# Forma nativa PowerShell
Invoke-RestMethod -Method POST "http://localhost:8001/api/notifications/trigger-report?force=true"

# Com janela de busca personalizada (ex: últimos 14 dias)
curl -X POST "http://localhost:8001/api/notifications/trigger-report?force=true&lookback_days=14"

# Forma nativa PowerShell
Invoke-RestMethod -Method POST "http://localhost:8001/api/notifications/trigger-report?force=true&lookback_days=14"
```

**4. Verifique o histórico de envios:**

```bash
curl http://localhost:8001/api/notifications/report-log

Invoke-RestMethod -Method GET "http://localhost:8001/api/notifications/report-log"

```


Resposta de exemplo:

```json
{
  "total": 2,
  "records": [
    {
      "id": 2,
      "report_period": "2026-W16",
      "recipients": "gestor@prefeitura.gov.br",
      "status": "sent",
      "error_message": null,
      "sent_at": "2026-04-20T08:00:12"
    },
    {
      "id": 1,
      "report_period": "2026-W15",
      "recipients": "gestor@prefeitura.gov.br",
      "status": "sent",
      "error_message": null,
      "sent_at": "2026-04-13T08:00:09"
    }
  ]
}
```

### Ajustar horários e janela de dados

| Variável | Padrão | Descrição |
|---|---|---|
| `REPORT_LOOKBACK_DAYS` | `21` | Dias para trás na busca de observações recentes |
| `COLLECT_HOUR_UTC` | `6` | Hora UTC da coleta diária (06h UTC = 03h BRT) |
| `REPORT_DAY_OF_WEEK` | `mon` | Dia da semana do boletim (`mon` `tue` `wed` … `sun`) |
| `REPORT_HOUR_UTC` | `8` | Hora UTC do envio (08h UTC = 05h BRT) |

Para alterar, edite o `.env` e reinicie o scheduler:

```bash
docker compose restart scheduler
```

### Acompanhar logs do scheduler

```bash
# Logs em tempo real
docker compose logs -f scheduler

# Saída esperada em um dia de coleta:
# [INFO] collect_recent: iniciando coleta para o ano 2026
# [INFO] Stats: Lagoa dos Barros — 3 imagens a processar
# [INFO] collect_recent: concluído — salvos=5 pulados=12 erros=0

# Saída esperada na segunda-feira:
# [INFO] send_weekly_report: verificando período 2026-W16
# [INFO] send_weekly_report: gerando relatório para 2026-W16 (janela=21 dias)
# [INFO] E-mail enviado com sucesso para: gestor@prefeitura.gov.br
# [INFO] send_weekly_report: enviado com sucesso — período=2026-W16
```

### Diagnóstico de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `SMTP_HOST, SMTP_USER e SMTP_PASSWORD devem estar configuradas` | Variáveis ausentes no `.env` | Preencha as três variáveis e reinicie o scheduler |
| `SMTPAuthenticationError` | Senha ou App Password incorreta | Gere uma nova App Password / verifique API Key |
| Status `skipped` com `already_sent` | Período já foi enviado nesta semana | Use `?force=true` para reenviar |
| Lagoa aparece como "Sem dados recentes" | Nenhuma passagem válida na janela | Aumente `REPORT_LOOKBACK_DAYS` ou aguarde a próxima passagem do satélite |

---

## Estrutura do projeto

```
ndci_sentinel2/
├── api/
│   ├── main.py                    # FastAPI app
│   └── routers/
│       ├── water_quality.py       # Endpoints de dados
│       ├── workers.py             # Endpoints de disparo de workers
│       ├── tiles.py               # Endpoints de tiles XYZ
│       └── notifications.py       # Endpoints de relatórios por e-mail
├── config.py                      # Lagoas, polígonos GEE, parâmetros
├── core/
│   ├── index_registry.py          # Índices espectrais (NDCI, NDTI, NDWI)
│   └── satellite_registry.py
├── frontend/
│   ├── index.html
│   ├── css/app.css
│   └── js/
│       ├── app.js                 # Orquestração principal
│       ├── charts.js              # Gráficos Chart.js
│       ├── api.js                 # Client HTTP (modo dinâmico)
│       └── api.static.js          # Client JSON (modo estático / gh-pages)
├── ingestion/
│   └── sentinel2/
│       ├── stats_worker.py        # Coleta estatísticas por imagem via GEE
│       ├── tiles_worker.py        # Gera tiles visuais XYZ via GEE
│       ├── band_math.py           # Cálculo de índices espectrais
│       └── cloud_mask.py          # Máscara de nuvens SCL
├── migrations/
│   ├── 001_water_quality.sql
│   ├── 002_map_tiles.sql
│   ├── 003_image_records.sql
│   └── 005_report_log.sql         # Log de idempotência dos relatórios
├── ml/
│   ├── features.py
│   └── predictor.py
├── notifications/
│   ├── email_sender.py            # Envio SMTP via smtplib
│   ├── report_builder.py          # Monta o HTML com dados recentes
│   └── templates/
│       └── weekly_report.html.j2  # Template Jinja2 (CSS inline)
├── scheduler/
│   └── report_scheduler.py        # APScheduler: coleta diária + boletim semanal
├── scripts/
│   └── build_static.py            # Build + deploy GitHub Pages
├── storage/
│   ├── models.py
│   └── repositories/
│       ├── water_quality.py
│       ├── image_records.py
│       ├── map_tiles.py
│       └── report_log.py          # Repositório de idempotência dos relatórios
├── .env.example
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Referência

Pi, K.; Guasselli, L.A. *Monitoramento de cianobactérias em lagoas costeiras do Litoral Norte do RS via NDCI/Sentinel-2.* SBSR 2025.
