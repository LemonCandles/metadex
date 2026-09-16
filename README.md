# 🗡️ Metadex

> Catálogo estatístico para acompanhar o meta de Dota 2 com dados de partidas de alto nível.

## Visão geral

O Metadex coleta partidas por meio da OpenDota API, preserva os dados de origem, produz indicadores estatísticos e os apresenta em uma interface web voltada a jogadores de Dota 2.

O objetivo é responder perguntas como:

- Quais heróis são mais escolhidos em partidas de alto nível?
- Quais heróis apresentam as maiores taxas de vitória dentro de uma amostra relevante?
- Como popularidade e desempenho mudam ao longo do tempo?
- Quais resultados podem ser explicados pelo tamanho ou pela composição da amostra?

O projeto não pretende determinar uma estratégia universalmente correta. Seus resultados representam correlações observadas no recorte analisado e devem sempre ser apresentados junto ao período, aos filtros e ao tamanho da amostra.

## Estado do projeto

O projeto está em fase inicial de planejamento. Este documento define a arquitetura e o escopo pretendidos; os diretórios e serviços descritos abaixo ainda serão implementados.

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
- dashboard responsivo consumindo uma API interna.

Para o primeiro corte, a janela sugerida é de sete dias, com atualização diária. Tanto a janela quanto o recorte de habilidade devem ser configuráveis, pois a disponibilidade exata dos filtros depende da validação dos endpoints da OpenDota.

Ficam fora do MVP:

- recomendação personalizada de heróis ou itens;
- previsão do resultado de partidas;
- análise de partidas em tempo real;
- autenticação de usuários;
- escrita concorrente por múltiplas instâncias;
- aplicativo móvel nativo.

## Arquitetura

O Metadex será organizado como um monorepo com dois componentes principais:

- **Backend:** coleta, persistência, transformação, cálculo das métricas e API HTTP.
- **Frontend:** navegação, filtros, tabelas e visualizações interativas.

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

O coletor é o único responsável por escrever na camada de dados. A API consulta resultados processados e não dispara coletas durante uma requisição do usuário. Essa separação evita que latência ou indisponibilidade da OpenDota comprometam o dashboard.

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
- **shadcn/ui:** componentes de interface.
- **Lucide:** ícones.
- **Recharts:** gráficos interativos.

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

O modelo processado deve começar com três conjuntos principais:

- **matches:** identifica a partida, o horário, a duração, o vencedor e os atributos do recorte disponíveis na fonte.
- **match_players:** relaciona partida, herói, equipe e resultado de cada participante, sem depender de identificação pessoal do jogador.
- **hero_daily_stats:** agrega escolhas, vitórias, derrotas, taxa de escolha, taxa de vitória e tamanho da amostra por herói e dia.

O pipeline deve registrar também informações operacionais, como horário da coleta, intervalo solicitado, quantidade de registros recebidos e eventuais falhas.

## Qualidade estatística

Toda métrica exposta deve informar o tamanho da amostra e os filtros aplicados. Rankings devem exigir uma amostra mínima configurável para reduzir distorções causadas por heróis pouco escolhidos.

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
```

As respostas de estatísticas devem incluir o período consultado, a data da última atualização e o tamanho da amostra, além dos valores calculados.

## Estrutura planejada do repositório

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

## Configuração prevista

As configurações devem ser recebidas por variáveis de ambiente e documentadas em `backend/.env.example`. Nenhum segredo deve ser versionado.

Variáveis iniciais previstas:

```dotenv
OPENDOTA_BASE_URL=https://api.opendota.com/api
OPENDOTA_API_KEY=
DATA_DIR=./data
DUCKDB_PATH=./data/metadex.duckdb
META_WINDOW_DAYS=7
MIN_SAMPLE_SIZE=100
```

Os valores definitivos de limites, paginação e intervalo entre requisições serão definidos após a validação da API e não devem ficar espalhados pelo código.

## Testes e observabilidade

O backend deve testar transformações e métricas com fixtures pequenas e determinísticas. Testes automatizados não devem depender continuamente da disponibilidade da OpenDota; respostas representativas podem ser gravadas e anonimizadas para testes de integração.

Coletas devem produzir logs estruturados com duração, volume, tentativas, falhas e limites de requisição observados. A API deve expor um endpoint de saúde sem incluir segredos ou detalhes internos sensíveis.

## Roadmap

1. Validar os endpoints, os campos e os limites de uso da OpenDota.
2. Inicializar o backend com `uv`, configuração tipada e testes.
3. Implementar uma coleta pequena, idempotente e persistida em Parquet.
4. Criar o modelo processado e o catálogo DuckDB.
5. Calcular as primeiras métricas de heróis com amostra mínima.
6. Publicar os resultados por meio da FastAPI.
7. Construir o dashboard em Next.js.
8. Automatizar atualizações e acompanhar a qualidade dos dados.

O primeiro marco funcional é coletar uma amostra real, persistir os dados e responder a `GET /api/v1/meta/heroes` com escolhas, vitórias, taxas, período e tamanho da amostra por herói.

## Licença

A licença do projeto ainda não foi definida. Os dados consumidos continuam sujeitos aos termos e às políticas da OpenDota e das fontes utilizadas por ela.
