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

As etapas 1 a 12 estão implementadas, com testes offline e dados reais preservados.
O backend coleta resumos, detalhes e catálogos da OpenDota, preserva a origem,
normaliza entidades, materializa métricas diárias e publica versões consultadas
pela API de ranking, detalhe e tendência. Backend e frontend foram instalados
pelos lockfiles; lint, testes, build e consultas HTTP locais foram verificados.
O [registro de validação](docs/etapas-1-9-validacao.md) reúne volumes, comandos,
reprocessamento e reconstrução. A etapa 10 acrescenta recomendações explicáveis
de heróis e primeiras compras de itens, com recuo explícito e amostra mínima.
O [guia da etapa 10](docs/etapa-10-explicacao.md) acompanha o código e os testes.
O dashboard da etapa 11 inclui visão geral, detalhe, tendência e recomendações;
a validação pode ser reproduzida pelos comandos e fluxos descritos abaixo.
A etapa 12 acrescenta rotina diária com barreira de qualidade, monitoramento,
backup, retenção, timers locais e integração contínua. O [guia de operação](ops/README.md)
explica a ativação no host, os alertas e a recuperação.
O timer deve ser instalado no host que manterá os dados persistentes; a instalação
não faz parte do checkout de desenvolvimento.

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
- `backend/app/pipeline/`: orquestra as etapas e publica uma versão completa dos dados.
- `backend/app/api/`: publica contratos HTTP e apenas lê resultados já processados.
- `backend/app/core/`: concentra configuração e utilitários compartilhados.
- `frontend/src/app/`: contém páginas, layouts e rotas da interface.
- `frontend/src/components/`: concentra componentes visuais reutilizáveis.
- `frontend/src/lib/`: concentra o cliente HTTP e utilitários do navegador.
- `frontend/src/types/`: mantém tipos TypeScript compartilhados pela interface.

Os comandos locais de coleta e processamento escrevem na camada de dados sob
um bloqueio de escritor único. Os dados brutos são imutáveis: correções geram
um novo processamento, nunca uma edição silenciosa da origem. A API consulta
resultados processados e não dispara coletas durante uma requisição do usuário.
Essa separação evita que latência ou indisponibilidade da OpenDota comprometam
o dashboard.

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
├── processed/
│   ├── public_matches/  # Normalização individual da etapa 6
│   └── versions/        # Versões completas publicadas pelo pipeline
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

## API versionada (etapas 9 e 10)

Os endpoints de saúde e métricas estão implementados. A documentação interativa
fica em `/docs`, e o contrato OpenAPI em `/openapi.json`. As recomendações da
etapa 10 também estão disponíveis:

```text
GET /health
GET /api/v1/meta/heroes
GET /api/v1/meta/heroes/{hero_id}
GET /api/v1/meta/heroes/{hero_id}/trend
GET /api/v1/recommendations/heroes
GET /api/v1/recommendations/items
```

As respostas de métricas incluem `period`, `filters`, `updated_at`, `version_id`
e `sample`. A atualização é o horário da publicação consultada. A API só lê a
última versão consistente; uma requisição nunca coleta nem publica dados.

| Parâmetro | Comportamento |
|---|---|
| `period_start`, `period_end` | Datas `AAAA-MM-DD`, fornecidas juntas; início inclusivo e fim exclusivo, em UTC. A janela aceita de 1 a 365 dias. Sem datas, usa `META_WINDOW_DAYS` dias completos anteriores ao dia atual UTC. |
| `cohort` | `all` (padrão): partidas normalizadas válidas. `high_skill_public_v1`: rank médio >=70, cobertura >=5 e modo/lobby balanceados segundo os catálogos da publicação; sem catálogo vinculado, responde `503`. |
| `game_mode`, `lobby_type` | IDs exatos que refinam o recorte escolhido. |
| `skill_min`, `skill_max` | Limites inclusivos de `avg_rank_tier`, entre 0 e 85. Exigem cobertura de rank positiva; não representam o rank individual de todos os participantes. |
| `rank_coverage_min` | Entre 1 e 10 jogadores com rank informado. |
| `order_by`, `order` | Apenas no ranking: `picks`, `wins`, `losses`, `pick_rate` ou `win_rate`; `asc` ou `desc`. Padrão: `win_rate` decrescente. Empates usam `hero_id` crescente. |
| `include_below_min` | Apenas no ranking: `true` inclui amostras abaixo de `MIN_SAMPLE_SIZE` para auditoria. O padrão é `false`. |

`pick_rate = picks / partidas elegíveis` e `win_rate = wins / picks`, na escala
de 0 a 1. As contagens são somadas antes das divisões. O denominador de escolhas
inclui partidas em que o herói não apareceu. `sample.matches` conta as partidas
do recorte; `hero.sample_size` conta escolhas do herói. O detalhe mantém amostras
pequenas consultáveis e informa `meets_min_sample`.

O ranking responde `200` com `heroes: []` e `status: no_data` quando o período
não contém partidas. Se há partidas, mas nenhum herói atinge a amostra mínima,
usa `status: below_min_sample`. Um herói observado na publicação pode ter
zero escolhas no período; um ID nunca observado recebe `404`. Taxas sem
denominador são `null`, e filtros não suportados, como posição, recebem `422`.

A tendência inclui cada dia do período e uma janela anterior de mesma duração,
com os mesmos filtros e a mesma publicação. Diferenças só são calculadas quando
ambas têm partidas em todos os dias. O campo `comparison.status` distingue
`comparable`, `insufficient_history`, `incomplete_current_period` e
`no_current_data`. Ter partidas diariamente não garante cobertura completa da
OpenDota nem demonstra causalidade.

Erros têm o formato `{"error":{"code":"...","message":"...","details":[]}}`.
Parâmetros inválidos usam `422`; catálogo ausente, sem publicação, ocupado ou
ilegível usa `503`, sem expor caminhos, SQL ou segredos. `/health` continua
respondendo `{"status":"ok"}` nesses casos: ele verifica a aplicação, não os dados.
As conexões são abertas somente durante cada consulta e fechadas ao final.
Uma consulta pode receber `503` durante a execução de um escritor DuckDB;
execute o pipeline fora das requisições e tente novamente após sua conclusão.

O pipeline materializa e valida `hero_daily_stats.parquet` antes da publicação.
Sem filtros, a API lê suas contagens; com filtros, recalcula a partir das
entidades usando o mesmo recorte no numerador e denominador. Publicações antigas
com agregador 1 permanecem legíveis por esse segundo caminho. Os quatro
catálogos da fonte são preservados e vinculados em `metadata.json` por versão.

Após publicar dados, exemplos de consultas são:

```bash
curl 'http://localhost:8000/api/v1/meta/heroes?include_below_min=true&order_by=picks'
curl 'http://localhost:8000/api/v1/meta/heroes/1?period_start=2026-09-18&period_end=2026-09-19'
curl 'http://localhost:8000/api/v1/meta/heroes/1/trend?period_start=2026-09-18&period_end=2026-09-19'
```

As datas acima correspondem às fixtures preservadas. Para outros dados locais,
informe seu período real. Os testes da etapa 9 executam coleta simulada com
projeções de respostas reais, armazenamento, publicação e consultas HTTP em
diretórios temporários. A validação real das etapas 1–9 também executou novas
coletas e confirmou as respostas com o servidor HTTP local.
O [guia para iniciantes](docs/etapa-9-explicacao.md) acompanha a execução entre
os arquivos e ensina a reproduzir a validação.

### Recomendações explicáveis (etapa 10)

O pipeline materializa `recommendation_stats.parquet` com contagens de vitórias
e participações em contextos realmente observados: dia, recorte, herói, posição
conhecida, aliados, adversários e duração. As compras incluem a chave do item,
o tempo e o índice original de compra. A agregação é recalculada e comparada
às entidades antes de promover a publicação. O agregador passa à versão 3;
versões 1 e 2 continuam legíveis para métricas e reconstrução. Para habilitar
recomendações sobre dados antigos, execute `uv run python -m app.pipeline reprocess`.

Os dois endpoints aceitam os filtros de período e recorte descritos acima,
`ally_ids` (até quatro IDs distintos), `opponent_ids` (até cinco), `position`
(1 a 5), `allow_fallback` (padrão `true`) e `limit` (1 a 100, padrão 10).
Listas usam parâmetros repetidos, como `ally_ids=1&ally_ids=2`; um ID não pode
estar nos dois lados. O endpoint de itens exige `hero_id`, que também não pode
aparecer nas listas. Heróis já informados no draft são excluídos do ranking.
`lane_role` não determina posição econômica: com os dados atuais, solicitar
posição devolve `unsupported_context` e uma lista vazia.

Todos os IDs do contexto precisam aparecer nos lados indicados. Se nenhum
candidato atinge `MIN_SAMPLE_SIZE`, o recuo tenta retirar os aliados e depois
os adversários. Ele conserva período, recorte, posição, herói e filtros de
itens. `allow_fallback=false` conserva o contexto exato. A resposta distingue
`requested_context` e `used_context`, informa cada tentativa em `fallback`
e usa o primeiro nível com evidência suficiente para o ranking inteiro.
Ordenação: taxa de vitória decrescente, amostra decrescente e identificador
crescente (`hero_id` ou `item_key`). As contagens são somadas antes da divisão.

O endpoint de itens aceita `duration_min_seconds`, `duration_max_seconds`,
`purchase_time_min_seconds`, `purchase_time_max_seconds` (padrão 1200),
`purchase_index_min` e `purchase_index_max`. Limites são inclusivos e o índice
começa em zero na lista original, incluindo receitas. Só a primeira compra
cronológica de cada item por participante é contada, com índice como desempate.
Inventário final, receitas e compras após o fim da partida são excluídos.
O limite padrão de vinte minutos deixa compras tardias fora do ranking;
ampliá-lo explicitamente permite inspecioná-las. Tempo e ordem médios descrevem
as compras observadas; não determinam o momento ideal de comprar.

Cada sugestão informa vitórias, derrotas, `sample_size`, `win_rate`, contexto,
`context_sample_size`, médias de duração/compra e explicação. `sample` descreve
o período e recorte, incluindo duração para itens, antes de aplicar o draft.
`context_sample_size` conta participações de heróis no contexto usado; para
itens ele conserva o herói. `sample_size` conta participações do candidato ou
participantes com a primeira compra daquele item. Ausência de log não prova
ausência de compra. Vantagem anterior e sobrevivência até comprar continuam
sendo vieses; as respostas incluem essas limitações e não atribuem causalidade.

Sem partidas elegíveis: `no_data`. Sem candidato com amostra suficiente:
`insufficient_evidence`. Ambos devolvem `200` e `recommendations: []`.
Sem publicação compatível: `503`; herói de itens nunca observado: `404`.

```bash
curl 'http://localhost:8000/api/v1/recommendations/heroes?period_start=2026-09-18&period_end=2026-10-02&ally_ids=93'
curl 'http://localhost:8000/api/v1/recommendations/items?hero_id=93&period_start=2026-09-18&period_end=2026-10-02&purchase_time_max_seconds=1200'
```

A amostra real local foi reprocessada sem nova coleta. Ela tem onze partidas,
insuficientes para o mínimo padrão de cem participações por candidato;
receber uma lista vazia nessas consultas é o comportamento esperado. Casos
sintéticos verificam sugestões, filtros, recuos, desempates e exclusões.

## Estrutura inicial do repositório

```text
metadex/
├── backend/
│   ├── app/
│   │   ├── main.py              # Inicialização da FastAPI
│   │   ├── api/                 # Rotas e contratos HTTP
│   │   ├── analytics/           # Métricas e agregações
│   │   ├── pipeline/            # Orquestração e publicação de versões
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
- O formato estruturado e os campos operacionais estão implementados em `backend/app/core/logging.py` e `runs.py`.

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
O endpoint `http://localhost:8000/health` deve responder `{"status":"ok"}`. A
cópia de `.env.example` é opcional enquanto os valores padrão servirem; a
leitura tipada dessas variáveis já está implementada.

Para executar as verificações:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Os testes unitários ficam em `backend/tests/unit/` e os testes de integração em
`backend/tests/integration/`. Ambos usam fixtures versionadas e não acessam a
internet. É possível executar apenas um grupo com `uv run pytest -m unit` ou
`uv run pytest -m integration`.

### Frontend

O frontend requer Node.js 20.9 ou superior e `pnpm` 11.19.0, versão registrada no `package.json`. Em outro terminal, a partir da raiz do repositório:

```bash
cd frontend
pnpm install --frozen-lockfile
cp .env.example .env.local
pnpm dev
```

A aplicação ficará disponível em `http://localhost:3000`.
As telas são `/` (ranking), `/heroes/{hero_id}` (detalhe e tendência) e
`/recommendations` (heróis e itens). O frontend consulta a API em
`NEXT_PUBLIC_API_BASE_URL` diretamente do navegador. Inicie o backend e publique
dados antes de esperar resultados estatísticos: sem publicação, a interface
mostra o erro `503` da API com opção de tentar novamente. O frontend não dispara
coleta. IDs de heróis e chaves de itens são exibidos como vêm da API, que ainda
não expõe nomes localizados.

Para executar as verificações:

```bash
pnpm lint
pnpm build
```

Para conferir a etapa 11 no navegador, inicie a API e visite `/`,
`/heroes/{hero_id}` e `/recommendations`. Verifique o ranking com e sem
amostras pequenas, a tabela diária da tendência e as sugestões de heróis e
itens. Ajuste período ou habilidade para um recorte vazio e desligue a API
para conferir o erro e a nova tentativa. Navegue com Tab e Enter em larguras
mobile e desktop; período, recorte, amostra e publicação devem permanecer
visíveis. Nesta implementação, ESLint, TypeScript e o build passaram; os
fluxos preenchidos foram exercitados com respostas sintéticas temporárias.

## Configuração

As configurações são documentadas nos arquivos `.env.example`. Copie esses arquivos localmente; nunca substitua os exemplos por valores secretos nem versione os arquivos gerados.

### Backend (`backend/.env.example`)

| Variável | Padrão de desenvolvimento | Finalidade |
|---|---|---|
| `OPENDOTA_BASE_URL` | `https://api.opendota.com/api` | URL HTTP base da fonte externa, sem parâmetros de consulta. |
| `OPENDOTA_API_KEY` | vazio | Chave opcional e secreta; não deve aparecer em logs ou commits. |
| `DATA_DIR` | `./data` | Diretório dos artefatos locais; caminhos relativos partem de `backend/`. |
| `DUCKDB_PATH` | `./data/metadex.duckdb` | Caminho validado do catálogo analítico local. |
| `META_WINDOW_DAYS` | `7` | Janela inicial do meta, entre 1 e 365 dias. |
| `MIN_SAMPLE_SIZE` | `100` | Amostra mínima positiva de escolhas por herói para rankings. |
| `CORS_ORIGINS` | `["http://localhost:3000","http://127.0.0.1:3000"]` | Lista JSON de origens autorizadas a consultar a API no navegador. Sem caminhos ou credenciais. |

### Frontend (`frontend/.env.example`)

| Variável | Padrão de desenvolvimento | Finalidade |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Endereço público usado pelo navegador para acessar a API. Não pode conter segredos. |

O cliente da OpenDota usa timeout de 10 segundos, no máximo três tentativas por
requisição, espera progressiva de 1 e 2 segundos e pausa de 1,1 segundo entre
páginas. Os limites ficam em `backend/app/collectors/opendota.py`. O comando de
coleta pública aceita no máximo cinco páginas e 200 partidas por execução.
Além de `/publicMatches?min_rank=70`, o cliente consulta detalhes por ID e
quatro catálogos. Detalhes são sequenciais e limitados a vinte IDs.
O recorte estatístico é selecionado explicitamente pela API ou pelo comando de
consulta; receber uma candidata não significa aprová-la para alto nível.

Para preservar os catálogos e coletar detalhes junto da amostra:

```bash
uv run python -m app.collectors --metadata --save
uv run python -m app.pipeline run --count 10 --max-pages 1 --with-details
```

Detalhes isolados usam `uv run python -m app.collectors --details ID --save`,
substituindo `ID` por um identificador real. Os quatro catálogos são guardados
em `raw/constants/`; somente uma captura completa é vinculada ao processamento.

Para executar uma amostra pequena, a partir de `backend/`:

```bash
uv run python -m app.collectors --count 2 --max-pages 1
```

O comando escreve um objeto JSON com as partidas e os metadados da execução na
saída padrão; logs estruturados saem na saída de erro. Os códigos de saída são
`0` para sucesso, `2` para amostra parcial e `1` para falha sem partidas.
Cada página da OpenDota pode trazer até 100 partidas mesmo quando `--count` é
menor; o excedente aparece na contagem `discarded_count`.

Para arquivar a amostra bruta, acrescente `--save` ao comando. Cada execução
gera `manifest.json` e `matches.parquet` em
`backend/data/raw/public_matches/collected_date=AAAA-MM-DD/run_ID/`.
O Parquet guarda o JSON integral de cada partida selecionada e os metadados da
requisição; o manifesto registra parâmetros, páginas, volumes, estado e erros.
Uma nova coleta pode reutilizar IDs: nesse caso, somente o primeiro payload
gravado para cada `(fonte, match_id)` permanece no conjunto bruto, e o novo manifesto
aponta para esses IDs. O arquivo da execução fica visível somente após a
gravação completa. O MVP pressupõe um único processo escritor.

Para inspecionar os arquivos sem rede, em `backend/`:

```bash
uv run python -m app.storage partitions
uv run python -m app.storage runs
uv run python -m app.storage read ID_DA_EXECUCAO
```

A leitura recompõe as partidas selecionadas na ordem da execução. O comando
`--save` também registra execuções sem partidas, para manter a falha auditável.
O [guia da etapa 5](docs/etapa-5-explicacao.md) explica o fluxo e os testes.

Para normalizar uma execução arquivada, copie seu `run_id` da saída de `runs`
e execute em `backend/`:

```bash
uv run python -m app.analytics RUN_ID
```

O comando lê apenas os dados brutos locais e grava `matches.parquet`,
`match_players.parquet`, `player_items.parquet` e `quality.json` em
`backend/data/processed/public_matches/RUN_ID/`. O relatório informa partidas
aceitas e rejeitadas, motivos e campos ausentes nas partidas aceitas. Resumos
públicos não informam inventário nem o `player_slot` real; apenas essa fonte
produz itens vazios e slots nulos. O fluxo `--with-details` preserva detalhes
separadamente e combina suas informações com o resumo antes de normalizar.
Posição econômica não é inferida; compras só existem quando fornecidas.
O [guia da etapa 6](docs/etapa-6-explicacao.md) explica essas regras.

### Catálogo e pipeline (etapa 7)

Para coletar uma amostra e executar o fluxo completo, em `backend/`:

```bash
uv run python -m app.pipeline run --count 2 --max-pages 1
```

A sequência é `collect → validate → normalize → aggregate → publish`.
A coleta é arquivada primeiro; depois, o pipeline relê todas as execuções
brutas confirmadas, valida os hashes dos payloads e deduplica por `match_id`.
Ele normaliza uma versão cumulativa, verifica a integridade entre partidas,
participantes e itens e agrega contagens de auditoria em
`dataset_counts.parquet`, métricas diárias em `hero_daily_stats.parquet` e
catálogos por versão em `metadata.json`. As agregações usam dias UTC e são
validadas contra as entidades antes da promoção.

Para repetir o processamento sem acessar a OpenDota:

```bash
uv run python -m app.pipeline reprocess
```

Cada execução usa um novo identificador, mas as mesmas entradas produzem
as mesmas entidades e contagens. Os arquivos anteriores permanecem preservados.
Registros rejeitados ficam no relatório de qualidade; somente os aceitos
entram nas entidades publicadas. Uma entrada sem partidas válidas falha e
preserva a publicação anterior.

O catálogo em `DUCKDB_PATH` contém:

| Contrato | Conteúdo |
|---|---|
| `pipeline_runs` | Etapa, estado, duração, volumes, tentativas, origem e erro de cada execução. |
| `collection_runs` | Manifestos confirmados das coletas de resumos e detalhes. |
| `dataset_versions` | Versões publicadas, versões substituídas, versões das transformações e manifestos. |
| `current_publication` | Identificador da versão atual. |
| `raw_matches` | Payloads e metadados brutos pertencentes à versão atual. |
| `matches`, `match_players`, `player_items` | Visões estáveis das entidades da versão atual. |
| `dataset_counts` | Contagens auditáveis das quatro entidades. |
| `hero_daily_stats` | Escolhas, vitórias, derrotas, partidas e taxas por herói/dia UTC. |

Os artefatos de cada versão ficam em
`backend/data/processed/versions/RUN_ID/`: três Parquets de entidades,
`dataset_counts.parquet`, `hero_daily_stats.parquet`, `quality.json`,
`metadata.json`, `version.json` com esquemas,
origens e checksums e `published.json` para recuperação da publicação.
As visões apontam para arquivos específicos. Coletas posteriores e diretórios
de preparação não alteram uma versão já publicada.

A promoção troca todas as visões, o identificador atual e o estado final da
execução em uma única transação DuckDB. Uma falha intermediária ou na promoção
mantém a versão anterior consultável. Uma coleta parcial ou com falha fica
arquivada, termina sem publicar e pode ser aproveitada depois por um
`reprocess` explícito. Os comandos retornam JSON em `stdout`, logs em `stderr`
e códigos `0` para sucesso, `2` para coleta parcial e `1` para falha.

Para inicializar ou reconstruir o catálogo a partir dos artefatos locais:

```bash
uv run python -m app.pipeline rebuild
```

O comando verifica schemas, checksums, contagens e integridade e restaura as
publicações completas e suas execuções bem-sucedidas, selecionando a mais
recente. Resultados sem comprovante de publicação e diretórios de preparação
são ignorados. Sem publicações anteriores, cria visões processadas vazias com
tipos definidos e uma visão das coletas brutas confirmadas; execute `reprocess`
para publicar os dados. O histórico de falhas é mantido no DuckDB e não pode
ser recuperado se esse arquivo for perdido.

Todos os escritores compartilham bloqueios locais em `raw/`, `processed/`
e ao lado do catálogo, inclusive os comandos anteriores `collectors --save`
e `analytics`. Um segundo escritor recebe um erro imediatamente. Os arquivos
de bloqueio permanecem no disco, mas o sistema operacional libera o bloqueio
quando o processo termina. Esse controle usa `flock` em Linux/macOS.

Consultas externas podem abrir o catálogo com `duckdb.connect(..., read_only=True)`
após o término do escritor. O [modo local do DuckDB](https://duckdb.org/docs/current/connect/concurrency.html)
permite um processo com escrita ou múltiplos processos somente de leitura;
a API da etapa 9 implementa essa leitura e converte indisponibilidade em `503`.

### Consultas locais de métricas (etapa 8)

Os comandos usam o mesmo serviço da API e não fazem coleta:

```bash
uv run python -m app.analytics.queries ranking --include-below-min
uv run python -m app.analytics.queries ranking --cohort high_skill_public_v1 --period-start 2026-09-18 --period-end 2026-10-02 --include-below-min
uv run python -m app.analytics.queries detail 86 --period-start 2026-09-18 --period-end 2026-10-02
uv run python -m app.analytics.queries trend 86 --period-start 2026-09-18 --period-end 2026-10-02
```

Datas e ID correspondem à amostra validada; adapte-os a outras coletas.
O [guia da etapa 8](docs/etapa-8-explicacao.md) explica as fórmulas e retornos.

## Testes e observabilidade

O backend separa testes unitários de testes de integração. As fixtures pequenas e determinísticas da OpenDota são carregadas por um utilitário compartilhado, e a suíte completa roda sem depender da internet.

O logger do projeto emite um objeto JSON por linha e remove chaves, tokens e valores secretos, inclusive em estruturas aninhadas. O modelo de execução reúne identificador, operação, estado, duração, volumes, tentativas e falhas. Os módulos futuros devem reutilizar esse contexto em vez de criar formatos próprios. A API expõe um endpoint de saúde sem incluir segredos ou detalhes internos sensíveis.

Falhas esperadas são classificadas em três categorias: recuperáveis, de dados e permanentes. Essa classificação descreve a natureza do problema; a política de novas tentativas pertence ao cliente da etapa 4.

## Checklist de arquitetura e escopo

- [x] Backend e frontend possuem comandos reproduzíveis de instalação e execução.
- [x] Responsabilidades de coleta, armazenamento, transformação, API e interface estão separadas.
- [x] Escritor único, dados brutos imutáveis e API desacoplada da coleta estão registrados como decisões do MVP.
- [x] Convenções de nomes, testes, logs e artefatos de dados estão definidas.
- [x] Arquivos de ambiente de exemplo documentam a configuração sem conter segredos.
- [x] Segredos, DuckDB, Parquet, dependências locais e builds estão ignorados pelo Git.
- [x] Itens fora do MVP estão explícitos na seção de escopo.
- [x] Endpoints e limitações da OpenDota validados (etapa 2).
- [x] Configuração tipada, testes e logs estruturados implementados (etapa 3).
- [x] Cliente e coleta pequena assíncrona implementados (etapa 4).
- [x] Persistência bruta em Parquet implementada (etapa 5).
- [x] Normalização e relatório de qualidade implementados (etapa 6).
- [x] Catálogo DuckDB, pipeline local, escritor único e publicação consistente implementados (etapa 7).
- [x] Materialização de métricas diárias, filtros e consultas por janela (etapa 8).
- [x] API versionada de ranking, detalhe e tendência validada offline e com dados reais (etapa 9).
- [x] Coleta real de resumos, detalhes e catálogos, deduplicação, reprocessamento e reconstrução verificados (etapas 1–9).
- [x] Recomendações explicáveis implementadas (etapa 10).
- [x] Dashboard responsivo integrado aos cinco endpoints estatísticos do MVP (etapa 11).
- [x] Rotina diária, monitor de publicação, backup, retenção e CI implementados (etapa 12).

O plano detalhado e a ordem das próximas entregas estão em `metadex-plano-12-etapas.md`.

## Licença

A licença do projeto ainda não foi definida. Os dados consumidos continuam sujeitos aos termos e às políticas da OpenDota e das fontes utilizadas por ela.
