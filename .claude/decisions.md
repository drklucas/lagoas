# Decisões Arquiteturais — ndci_sentinel2

## Processamento por imagem individual (não composição mensal)

**Decisão:** O stats_worker processa cada cena Sentinel-2 individualmente e salva em `ndci_image_records`. Os agregados mensais em `ndci_water_quality` são *derivados* via SQL GROUP BY após a coleta.

**Por quê:** Composições mensais mascaram picos de bloom de curta duração. A metodologia Pi & Guasselli (SBSR 2025) exige granularidade por cena para capturar florescimentos que duram menos de um mês.

---

## Duas tabelas de dados (image_records + water_quality)

**Decisão:** Manter `ndci_image_records` (fonte primária, por cena) e `ndci_water_quality` (derivada, mensal) como tabelas separadas.

**Por quê:** O modelo ML e a API legada consomem séries mensais regulares. O frontend expõe ambas (toggle mensal/por-imagem). Derivar agregados no banco é mais eficiente do que recomputar no Python a cada request.

---

## GEE stats worker roda em thread executor (não coroutine nativa)

**Decisão:** `_sync_collect_stats()` é função síncrona; `collect_stats()` usa `loop.run_in_executor(None, lambda: ...)` para expô-la como coroutine.

**Por quê:** A GEE Python API (`ee.Image`, `getInfo()`, etc.) é bloqueante e não tem suporte a asyncio. Rodar em executor evita bloquear o event loop do FastAPI sem precisar de um worker externo (Celery, etc.).

---

## Buffer negativo por lagoa (não uniforme)

**Decisão:** Cada lagoa tem seu próprio `buffer_negativo_m` em `config.py` (30 m para Peixoto e Caconde; 100–200 m para as grandes).

**Por quê:** Lagoas pequenas (Peixoto, Caconde) perdem área demais com buffers grandes. O buffer é calibrado pelo tamanho da lagoa e pela resolução de 20 m do Sentinel-2. Peixoto foi reduzido de 100 m para 30 m após produzir poucos pixels válidos.

---

## Filtro duplo de água: NDWI > -0.2 OR FAI > 0

**Decisão:** A máscara de água em `band_math.py` usa `(NDWI > -0.2) OR (FAI > 0)` em vez do threshold padrão `-0.1`.

**Por quê:** Pixels com bloom denso de cianobactérias têm alta reflectância no NIR, o que pode gerar NDWI ligeiramente negativo (abaixo de -0.1). O critério FAI > 0 retém esses pixels. O threshold relaxado de -0.2 é compensado pelo buffer negativo.

---

## Tile proxy no backend (não exposição direta do map_id)

**Decisão:** O frontend acessa tiles via `/api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>`. O `map_id` GEE nunca é exposto diretamente ao browser.

**Por quê:** `map_id` contém credenciais implícitas e expira em ~24 h. O proxy centraliza o refresh e permite que o `tile_key` (composto estável: `satellite|index|ano|mes|lagoa`) permaneça válido mesmo após regeneração do `map_id`.

---

## SQLite como fallback de desenvolvimento (sem Docker)

**Decisão:** `DATABASE_URL` default é `sqlite:///./ndci_sentinel2.db`. O engine adapta o pool (`pool_size` só para PostgreSQL).

**Por quê:** Permite rodar a API localmente sem Docker. SQLite não suporta concorrência real, mas é suficiente para desenvolvimento e testes unitários dos endpoints.

---

## `satellite` como coluna de extensão em todas as tabelas

**Decisão:** Todos os modelos e repositórios têm coluna `satellite` (default `"sentinel2"`).

**Por quê:** Preparação para adicionar Landsat 8/9 ou outros satélites sem schema migration. Os repositories filtram por `satellite=` em todas as queries — nenhuma mudança necessária ao adicionar um novo satélite.

---

## Frontend com dois modos de API (dinâmico vs. estático)

**Decisão:** `api.js` (fetch para `/api/*`) e `api.static.js` (lê JSONs de `./data/*.json`). O `index.html` importa um ou outro dependendo do modo de build.

**Por quê:** GitHub Pages não suporta servidor backend. O `build_static.py` exporta todos os dados como JSON e troca o import para `api.static.js`, permitindo hospedagem gratuita e sem servidor.

---

## Migrações como SQL puro (sem Alembic obrigatório)

**Decisão:** Migrações em `migrations/001_*.sql`, `002_*.sql`, `003_*.sql`. Docker Compose monta os SQLs como init scripts. `alembic` está em `requirements.txt` mas marcado como opcional.

**Por quê:** O sistema é suficientemente simples para SQL direto. O Docker já aplica as migrações automaticamente na inicialização via `docker-entrypoint-initdb.d/`. `create_all_tables()` cobre o caso sem Docker.
