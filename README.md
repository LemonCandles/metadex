# Metadex

Aplicação web para acompanhar o meta de Dota 2 com dados da OpenDota. Apresenta ranking de heróis, tendências e recomendações de heróis e itens, com período, filtros e tamanho da amostra.

## Como executar

**Pré-requisitos:** Linux (ou WSL), Python 3.12, uv, Node.js 22 e pnpm 11.19.0. A instalação das dependências e a coleta precisam de internet.

### 1. Preparar o backend

A partir da raiz do repositório:

```bash
cd backend
uv sync --frozen --group dev
cp -n .env.example .env
```

O `cp -n` preserva um arquivo de configuração já existente. Os padrões de `.env.example` usam `backend/data/` para os dados, janela de sete dias e amostra mínima de 100 escolhas por herói. A chave da OpenDota é opcional.

### 2. Publicar os dados

Ainda em `backend/`, antes de iniciar a API, colete os nomes do jogo e uma amostra com detalhes:

```bash
uv run --frozen python -m app.collectors --metadata --save
uv run --frozen python -m app.pipeline run --count 20 --max-pages 2 --with-details
```

Se já houver uma publicação local, essa etapa é opcional. Para recalcular dados brutos preservados, sem acessar a OpenDota:

```bash
uv run --frozen python -m app.pipeline reprocess
```

### 3. Iniciar a API

Ainda em `backend/`:

```bash
uv run --frozen uvicorn app.main:app --reload --port 8000
```

- API: <http://localhost:8000>
- Documentação interativa: <http://localhost:8000/docs>
- Saúde da aplicação: <http://localhost:8000/health>

Sem dados publicados, as consultas estatísticas retornam HTTP 503; o endpoint de saúde continua disponível.

### 4. Iniciar o frontend

Em outro terminal, a partir da raiz do repositório:

```bash
cd frontend
pnpm install --frozen-lockfile
cp -n .env.example .env.local
pnpm dev
```

Abra <http://localhost:3000>. O endereço da API é configurado por `NEXT_PUBLIC_API_BASE_URL` em `frontend/.env.local`, com padrão `http://localhost:8000`.

Uma coleta pequena pode não atingir a amostra mínima. Use **Mostrar amostras pequenas** para explorar o ranking e ajuste o período às datas coletadas. A janela padrão considera os sete dias completos anteriores ao dia atual em UTC.

## Arquitetura

Backend e frontend ficam no mesmo repositório e se comunicam por uma API HTTP:

```text
OpenDota -> Coleta -> Parquet bruto
                          |
                          v
                  Validação e normalização
                          |
                          v
                  Parquet processado
                          |
                          v
                  DuckDB -> FastAPI -> Next.js
```

O pipeline preserva a origem, normaliza partidas, participantes e compras, calcula estatísticas e publica uma versão completa. A API consulta essa versão; o frontend apresenta os resultados e os nomes do jogo. Visitar uma página não dispara coleta.

Os dados brutos são imutáveis e permitem reprocessamento. Os comandos de escrita usam um bloqueio de escritor único; execute atualizações com a API parada para evitar disputa pelo catálogo DuckDB. As recomendações representam associações observadas com vitórias.

## Organização das pastas

```text
backend/
├── app/
│   ├── core/        # Configuração, tempo, erros e logs
│   ├── collectors/  # Cliente e coleta da OpenDota
│   ├── analytics/   # Normalização, métricas e recomendações
│   ├── storage/     # Parquet, catálogo DuckDB e consultas
│   ├── pipeline/    # Processamento e publicação de versões
│   ├── api/         # Rotas e contratos HTTP
│   └── operations/  # Atualização diária, monitoramento e manutenção
├── tests/           # Testes unitários, integração e fixtures offline
└── data/            # Dados locais gerados, fora do Git
frontend/
├── src/
│   ├── app/         # Páginas, layout e estilos globais
│   ├── components/  # Componentes e hooks compartilhados
│   └── lib/         # Cliente HTTP, tipos e utilitários
└── tests/           # Testes das regras usadas pelos formulários
ops/                 # Instruções de operação e timers systemd
.github/workflows/   # Integração contínua
```

## Tecnologias

| Tecnologia | Uso no projeto |
|---|---|
| Python | Coleta, processamento, cálculos e API |
| FastAPI, Pydantic e Uvicorn | Rotas HTTP, validação dos contratos e servidor |
| HTTPX e OpenDota | Consulta assíncrona à fonte de partidas e catálogos |
| PyArrow e Parquet | Escrita de tabelas tipadas e preservação dos dados em arquivos |
| DuckDB e SQL | Catálogo local, consultas e agregações analíticas |
| Pandas | Exploração tabular e leitura de Parquet nos testes |
| Next.js, React e TypeScript | Páginas, interação e tipagem da interface |
| CSS, Tailwind CSS e PostCSS | Estilos e processamento de CSS; o layout usa principalmente CSS próprio |
| uv e pnpm | Ambientes, dependências e instalação pelos lockfiles |
| pytest, pytest-asyncio, Ruff, node:test e ESLint | Testes e verificações de código |
| GitHub Actions e systemd | Verificações automáticas e agendamento no host Linux |

## Verificações

Em `backend/`:

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
```

Em `frontend/`:

```bash
pnpm lint
pnpm test
pnpm build
```

Os testes usam dados simulados e não acessam a OpenDota. Para servir o frontend compilado, execute `pnpm start` após o build. Agendamento, monitoramento e recuperação estão descritos em [ops/README.md](ops/README.md).
