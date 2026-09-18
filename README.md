# 🗡️ Metadex

> Catálogo estatístico para acompanhar o meta de Dota 2 com dados de partidas de alto nível.

## Visão geral

O Metadex coleta partidas por meio da OpenDota API, preserva os dados de origem, produz indicadores estatísticos e os apresenta em uma interface web voltada a jogadores de Dota 2.

O objetivo é responder perguntas como:

- Quais heróis são mais escolhidos em partidas de alto nível?
- Quais heróis apresentam as maiores taxas de vitória dentro de uma amostra relevante?
- Como popularidade e desempenho mudam ao longo do tempo?
- Quais heróis e itens apresentam os melhores resultados para um contexto informado pelo jogador?
- Quais resultados podem ser explicados pelo tamanho ou pela composição da amostra?
- Skin gera Skill?

O projeto não pretende determinar uma estratégia universalmente correta. Seus resultados representam correlações observadas no recorte analisado e devem sempre ser apresentados junto ao período, aos filtros e ao tamanho da amostra.

## Estado do projeto

As etapas 1 e 2 estão concluídas. A estrutura do monorepo e os ambientes estão configurados, e a fonte OpenDota foi validada com respostas reais anonimizadas. Ainda não existe coletor nem cálculo de métricas: a próxima etapa prepara configuração, testes e observabilidade.

## Escopo do MVP

A primeira versão deve entregar um fluxo completo, da coleta à visualização, para um conjunto pequeno de indicadores:

- coleta periódica de partidas públicas de alto nível;
- armazenamento dos dados brutos para permitir reprocessamento;
- normalização de partidas e participações de heróis;
- taxa de escolha por herói;
- taxa de vitória por herói;
- tamanho da amostra de cada indicador;
- variação dos indicadores ao longo do tempo;
- filtros por período e, quando os dados permitirem, faixa de habilidade;
- recomendação de heróis baseada em posição, aliados, adversários e recorte do meta;
- recomendação de itens baseada no herói, no contexto da partida e no desempenho observado;
- dashboard responsivo consumindo uma API interna.

Para o primeiro corte, a janela sugerida é de sete dias, com atualização diária. Tanto a janela quanto o recorte de habilidade devem ser configuráveis, pois a disponibilidade exata dos filtros depende da validação dos endpoints da OpenDota.

Ficam fora do MVP:

- personalização baseada no histórico de uma conta ou no perfil persistente do jogador;
- previsão do resultado de partidas;
- análise de partidas em tempo real;
- autenticação de usuários;
- escrita concorrente por múltiplas instâncias;
- aplicativo móvel nativo.

## Arquitetura

O Metadex é organizado como um monorepo com dois componentes principais:

- **Backend (`backend/`):** coleta, persistência, transformação, cálculo das métricas e API HTTP. A aplicação FastAPI é iniciada por `backend/app/main.py`.
- **Frontend (`frontend/`):** navegação, filtros, tabelas e visualizações interativas. A aplicação Next.js usa o App Router em `frontend/src/app/`.

```text
OpenDota API
     │
     ▼
Coletor assíncrono
     │
     ▼
Parquet bruto (raw)
     │
     ▼
Normalização e validação
     │
     ▼
Parquet processado + DuckDB
     │
     ▼
FastAPI
     │
     ▼
Next.js
```

### Responsabilidades por camada

- `backend/app/collectors/`: acessa fontes externas e inicia a entrada de dados.
- `backend/app/storage/`: grava e lê Parquet e DuckDB; no MVP, somente um processo pode escrever.
- `backend/app/analytics/`: transforma dados preservados e calcula resultados explicáveis.
- `backend/app/api/`: publica contratos HTTP e apenas lê resultados já processados.
- `backend/app/core/`: concentra configuração e utilitários compartilhados.
- `frontend/src/app/`: contém páginas, layouts e rotas da interface.
- `frontend/src/components/`: concentra componentes visuais reutilizáveis.
- `frontend/src/lib/`: concentra o cliente HTTP e utilitários do navegador.
- `frontend/src/types/`: mantém tipos TypeScript compartilhados pela interface.

O coletor é o único responsável por escrever na camada de dados. Os dados brutos são imutáveis: correções geram um novo processamento, nunca uma edição silenciosa da origem. A API consulta resultados processados e não dispara coletas durante uma requisição do usuário. Essa separação evita que latência ou indisponibilidade da OpenDota comprometam o dashboard.

### Decisões fixas do MVP

1. Há apenas um processo escritor para Parquet e DuckDB.
2. A camada bruta preserva a resposta de origem e não é alterada após a gravação.
3. Coleta e requisições HTTP da API têm ciclos de execução independentes.
4. Indicadores informam período, filtros e tamanho da amostra.
5. Código e diretórios usam nomes em inglês; documentação e interface podem usar português.

## Stack tecnológica

### Backend e dados

- **Python 3:** linguagem do pipeline e da API.
- **uv:** gerenciamento do ambiente, das dependências e do lockfile.
- **HTTPX:** cliente HTTP assíncrono para integração com a OpenDota.
- **Pandas:** limpeza, exploração e transformações tabulares.
- **DuckDB:** consultas analíticas, catálogo local e agregações.
- **Parquet:** armazenamento colunar dos dados brutos e processados.
- **FastAPI:** API HTTP consumida pelo frontend.

### Frontend

- **Next.js com React:** aplicação web e roteamento.
- **TypeScript:** tipagem do código e dos contratos com a API.
- **Tailwind CSS:** estilos e layout responsivo.

Bibliotecas de componentes, ícones e gráficos serão escolhidas e adicionadas somente quando a interface funcional exigir. Isso evita instalar dependências de etapas futuras na base inicial.

### Fonte de dados

- **OpenDota API:** fonte externa das partidas e dos metadados de Dota 2.

## Persistência de dados

O MVP utiliza **Parquet + DuckDB**. Essa combinação oferece leitura analítica eficiente, integração direta com Pandas e operação local sem manter um servidor de banco de dados.

### Responsabilidades

- **Parquet** preserva conjuntos de dados grandes em arquivos colunares, compactos e particionáveis.
- **DuckDB** consulta os arquivos Parquet, mantém metadados das execuções e materializa agregações usadas pela API.

### Camadas

Os artefatos locais ficam em `backend/data/`, que não é versionado:

```text
backend/data/
├── raw/                 # Respostas preservadas para reprocessamento
├── processed/           # Entidades limpas e normalizadas
└── metadex.duckdb       # Catálogo, execuções e agregações
```

Os arquivos Parquet devem ser particionados por data de coleta ou data da partida. O `match_id` da OpenDota deve ser usado como chave de deduplicação para tornar novas execuções idempotentes.

O repositório deve conter apenas esquemas, transformações e amostras pequenas destinadas a testes. Dados coletados e o arquivo local do DuckDB permanecem fora do controle de versão.

### Evolução

DuckDB é adequado enquanto houver um único processo escritor e a carga for predominantemente analítica. Uma migração para PostgreSQL deve ser considerada quando o projeto exigir escrita concorrente, múltiplas instâncias da API ou operação distribuída. O contrato público da FastAPI deve permanecer independente da tecnologia de persistência.

## Modelo de dados inicial

O modelo processado deve começar com cinco conjuntos principais:

- **matches:** identifica a partida, o horário, a duração, o vencedor e os atributos do recorte disponíveis na fonte.
- **match_players:** relaciona partida, herói, equipe e resultado de cada participante, sem depender de identificação pessoal do jogador.
- **player_items:** relaciona a participação aos itens observados e, quando disponível, ao momento de aquisição.
- **hero_daily_stats:** agrega escolhas, vitórias, derrotas, taxa de escolha, taxa de vitória e tamanho da amostra por herói e dia.
- **recommendation_stats:** agrega desempenho e tamanho da amostra para combinações de herói, item e contexto utilizadas pelo recomendador.

O pipeline deve registrar também informações operacionais, como horário da coleta, intervalo solicitado, quantidade de registros recebidos e eventuais falhas.

## Qualidade estatística

Toda métrica exposta deve informar o tamanho da amostra e os filtros aplicados. Rankings devem exigir uma amostra mínima configurável para reduzir distorções causadas por heróis pouco escolhidos.

As recomendações devem ser explicáveis: cada sugestão precisa indicar quais filtros e estatísticas a sustentam. Correlações com vitórias não devem ser apresentadas como causalidade. Recomendações de itens também devem considerar vieses como duração da partida, ordem de compra e itens que aparecem com maior frequência apenas em partidas já favoráveis.

As transformações devem ser reproduzíveis e cobrir, no mínimo:

- remoção de duplicatas;
- validação de campos obrigatórios;
- tratamento explícito de valores ausentes;
- separação entre dados brutos e derivados;
- registro da versão ou data de atualização dos metadados de heróis;
- testes para as fórmulas das métricas.

## API inicial

O contrato definitivo será definido durante a implementação. O MVP deve oferecer, no mínimo:

```text
GET /health
GET /api/v1/meta/heroes
GET /api/v1/meta/heroes/{hero_id}
GET /api/v1/meta/heroes/{hero_id}/trend
GET /api/v1/recommendations/heroes
GET /api/v1/recommendations/items
```

As respostas de estatísticas devem incluir o período consultado, a data da última atualização e o tamanho da amostra, além dos valores calculados.

## Estrutura inicial do repositório

```text
metadex/
├── backend/
│   ├── app/
│   │   ├── main.py              # Inicialização da FastAPI
│   │   ├── api/                 # Rotas e contratos HTTP
│   │   ├── analytics/           # Métricas e agregações
│   │   ├── collectors/          # Coleta da OpenDota
│   │   ├── core/                # Configuração e utilitários compartilhados
│   │   └── storage/             # DuckDB, Parquet e repositórios de dados
│   ├── data/                    # Artefatos locais não versionados
│   ├── notebooks/               # Exploração de dados
│   ├── tests/                   # Testes unitários e de integração
│   ├── .env.example             # Variáveis documentadas
│   ├── pyproject.toml           # Projeto e dependências Python
│   └── uv.lock                  # Versões reproduzíveis
├── frontend/
│   ├── src/
│   │   ├── app/                 # Páginas e rotas do Next.js
│   │   ├── components/          # Componentes e gráficos
│   │   ├── lib/                 # Cliente da API e utilitários
│   │   └── types/               # Tipos compartilhados no frontend
│   ├── package.json
│   └── tsconfig.json
├── .gitignore
└── README.md
```

Os nomes de diretório do código seguem convenções em inglês para manter consistência com os ecossistemas Python e TypeScript. A documentação e a interface podem permanecer em português.

## Convenções do repositório

### Nomes e módulos

- Módulos, funções e variáveis Python usam `snake_case`; classes usam `PascalCase`.
- Arquivos e variáveis TypeScript usam nomes descritivos em inglês; componentes React usam `PascalCase`.
- Rotas HTTP públicas ficam sob `/api/v1`, exceto rotas operacionais como `/health`.
- Variáveis de ambiente usam `UPPER_SNAKE_CASE`; somente variáveis públicas do navegador recebem o prefixo `NEXT_PUBLIC_`.

### Testes

- Testes unitários do backend ficam em `backend/tests/unit/`.
- Testes de integração do backend ficam em `backend/tests/integration/`.
- Arquivos Python de teste seguem `test_*.py`.
- Testes não devem depender continuamente da OpenDota; respostas pequenas e anonimizadas poderão ser usadas como fixtures quando o contrato da fonte for validado.
- Testes do frontend devem ficar próximos ao código como `*.test.ts` ou `*.test.tsx` quando forem introduzidos.

### Logs

- Aplicações escrevem logs em `stdout`/`stderr`; logs de execução não são versionados.
- Mensagens devem incluir contexto operacional, sem chaves de API ou outros segredos.
- O formato estruturado e os campos obrigatórios serão implementados na etapa de observabilidade.

### Dados e artefatos

- Dados locais ficam exclusivamente em `backend/data/`.
- `backend/data/raw/` recebe dados de origem imutáveis; `backend/data/processed/` recebe resultados derivados.
- Bancos `*.duckdb`, arquivos auxiliares `*.duckdb.wal` e conjuntos `*.parquet` são ignorados pelo Git em qualquer diretório.
- Artefatos de build (`.next/`, `out/`, `dist/`, `build/`) e dependências instaladas (`.venv/`, `node_modules/`) são recriados localmente e não são versionados.

## Desenvolvimento local

### Backend

O backend requer Python 3.12 a 3.14 e `uv`. A partir da raiz do repositório:

```bash
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

A API ficará disponível em `http://localhost:8000` e a documentação interativa em `http://localhost:8000/docs`.
O endpoint `http://localhost:8000/health` deve responder `{"status":"ok"}`. A cópia de `.env.example` prepara o ambiente, embora a leitura tipada dessas variáveis só seja implementada em uma etapa posterior.

Para executar as verificações:

```bash
uv run ruff check .
```

### Frontend

O frontend requer Node.js 20.9 ou superior e `pnpm` 11.19.0, versão registrada no `package.json`. Em outro terminal, a partir da raiz do repositório:

```bash
cd frontend
pnpm install --frozen-lockfile
cp .env.example .env.local
pnpm dev
```

A aplicação ficará disponível em `http://localhost:3000`.

Para executar as verificações:

```bash
pnpm lint
pnpm build
```

## Configuração

As configurações são documentadas nos arquivos `.env.example`. Copie esses arquivos localmente; nunca substitua os exemplos por valores secretos nem versione os arquivos gerados.

### Backend (`backend/.env.example`)

| Variável | Padrão de desenvolvimento | Finalidade |
|---|---|---|
| `OPENDOTA_BASE_URL` | `https://api.opendota.com/api` | URL base da fonte externa. |
| `OPENDOTA_API_KEY` | vazio | Chave opcional e secreta; não deve aparecer em logs ou commits. |
| `DATA_DIR` | `./data` | Diretório dos artefatos locais, relativo a `backend/`. |
| `DUCKDB_PATH` | `./data/metadex.duckdb` | Caminho do catálogo analítico local. |
| `META_WINDOW_DAYS` | `7` | Janela inicial do meta em dias. |
| `MIN_SAMPLE_SIZE` | `100` | Amostra mínima inicial para rankings. |

### Frontend (`frontend/.env.example`)

| Variável | Padrão de desenvolvimento | Finalidade |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Endereço público usado pelo navegador para acessar a API. Não pode conter segredos. |

Os valores definitivos de limites, paginação e intervalo entre requisições serão definidos após a validação da API e não devem ficar espalhados pelo código.

## Testes e observabilidade

O backend deve testar transformações e métricas com fixtures pequenas e determinísticas. Testes automatizados não devem depender continuamente da disponibilidade da OpenDota; respostas representativas podem ser gravadas e anonimizadas para testes de integração.

Coletas devem produzir logs estruturados com duração, volume, tentativas, falhas e limites de requisição observados. A API deve expor um endpoint de saúde sem incluir segredos ou detalhes internos sensíveis.

## Checklist de arquitetura e escopo

- [x] Backend e frontend possuem comandos reproduzíveis de instalação e execução.
- [x] Responsabilidades de coleta, armazenamento, transformação, API e interface estão separadas.
- [x] Escritor único, dados brutos imutáveis e API desacoplada da coleta estão registrados como decisões do MVP.
- [x] Convenções de nomes, testes, logs e artefatos de dados estão definidas.
- [x] Arquivos de ambiente de exemplo documentam a configuração sem conter segredos.
- [x] Segredos, DuckDB, Parquet, dependências locais e builds estão ignorados pelo Git.
- [x] Itens fora do MVP estão explícitos na seção de escopo.
- [ ] Endpoints e limitações da OpenDota validados (etapa 2).
- [ ] Configuração tipada, testes e logs estruturados implementados (etapa 3).
- [ ] Coleta, persistência, métricas e interface de negócio implementadas (etapas seguintes).

O plano detalhado e a ordem das próximas entregas estão em `metadex-plano-12-etapas.md`.

## Licença

A licença do projeto ainda não foi definida. Os dados consumidos continuam sujeitos aos termos e às políticas da OpenDota e das fontes utilizadas por ela.
