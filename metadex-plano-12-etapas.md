# Metadex em 12 etapas

Plano de execução do MVP, da validação da OpenDota até uma aplicação atualizada diariamente, com dados auditáveis, métricas explicáveis e interface responsiva.

## Princípios do projeto

- **Dados antes da interface:** o dashboard só consome contratos estabilizados pela API.
- **Dados brutos preservados:** toda transformação pode ser refeita sem realizar uma nova coleta.
- **Amostra sempre visível:** taxas e recomendações incluem período, filtros e contagens.
- **Coleta fora das requisições:** indisponibilidade da OpenDota não deve impedir consultas ao dashboard.
- **Um único escritor no MVP:** Parquet e DuckDB permanecem simples e consistentes.
- **Correlação não é causalidade:** resultados estatísticos devem ser apresentados com suas limitações.

## Sequência geral

| Etapas | Foco |
|---|---|
| 1 a 3 | Base do projeto e redução das incertezas |
| 4 a 7 | Coleta, persistência e processamento reproduzível |
| 8 e 9 | Métricas e primeiro marco funcional pela API |
| 10 e 11 | Recomendações e experiência do usuário |
| 12 | Automação, qualidade e preparação da entrega |

---

## Etapa 1 — Consolidar a base e as regras do projeto

**Estado atual:** estrutura inicial concluída.

### Objetivo

Transformar o README em uma referência operacional e confirmar que o esqueleto atual é reproduzível antes de iniciar funcionalidades.

### O que será feito

- Revisar a estrutura do monorepo, os comandos de instalação e os arquivos de ambiente de exemplo.
- Confirmar as responsabilidades do coletor, das transformações, do armazenamento, da API e do frontend.
- Definir convenções de nomes, localização de testes, logs e artefatos de dados.
- Registrar decisões que não devem variar durante o MVP:
  - apenas um processo escritor;
  - dados brutos imutáveis;
  - API desacoplada da coleta.
- Criar uma lista objetiva do que está fora do MVP para evitar expansão de escopo.

### Entregáveis

- Estrutura base executável do backend e do frontend.
- Configurações de ambiente documentadas.
- Dados locais e segredos ignorados pelo Git.
- Checklist de arquitetura e escopo aceito para as próximas etapas.

### Como validar

- Instalar as dependências do backend com `uv`.
- Instalar as dependências do frontend com `pnpm`.
- Executar Ruff no backend.
- Executar ESLint e o build de produção do Next.js.
- Confirmar que nenhum segredo, banco DuckDB ou arquivo Parquet está versionado.

### Critério de conclusão

A equipe consegue clonar, instalar e abrir os dois projetos sem implementar funcionalidades de negócio.

### Risco principal

Começar a coleta com contratos ou responsabilidades ainda ambíguos pode gerar retrabalho em todas as outras camadas.

---

## Etapa 2 — Validar a OpenDota e o recorte estatístico

### Objetivo

Comprovar quais dados podem ser obtidos, com que qualidade e sob quais limites antes de fixar o modelo de dados.

### O que será feito

- Mapear endpoints para:
  - partidas públicas de alto nível;
  - detalhes de partidas;
  - heróis;
  - itens;
  - metadados auxiliares.
- Registrar parâmetros, paginação, limites de requisição, autenticação opcional e comportamento de erros.
- Verificar se estão disponíveis:
  - faixa de habilidade;
  - posição do herói;
  - aliados e adversários;
  - horário de aquisição dos itens.
- Coletar pequenas respostas reais e anonimizadas para inspeção e testes futuros.
- Definir o denominador correto da taxa de escolha.
- Definir o significado exato de cada filtro estatístico.
- Documentar campos ausentes, instáveis ou inferidos.

### Entregáveis

- Matriz relacionando endpoints, campos e disponibilidade.
- Fixtures pequenas e representativas.
- Contrato preliminar dos dados brutos.
- Lista de limitações conhecidas da fonte.

### Como validar

- Reproduzir requisições de exemplo com e sem chave de API, quando aplicável.
- Observar e registrar limites e códigos de erro.
- Classificar cada campo necessário como disponível, derivado ou indisponível.
- Confirmar se o recorte de partidas realmente representa o público pretendido.

### Critério de conclusão

É possível explicar exatamente quais dados sustentarão escolhas, vitórias, tendências e recomendações.

### Risco principal

Assumir filtros inexistentes ou dados de itens completos pode inviabilizar as recomendações posteriormente.

---

## Etapa 3 — Preparar configuração, testes e observabilidade

### Objetivo

Criar a infraestrutura interna necessária para desenvolver o pipeline com comportamento previsível e diagnóstico claro.

### O que será feito

- Implementar configuração tipada para:
  - URL da OpenDota;
  - chave de API;
  - diretórios de dados;
  - caminho do DuckDB;
  - janela do meta;
  - amostra mínima.
- Separar configuração de código.
- Garantir que segredos nunca apareçam nos logs.
- Configurar pytest e fixtures determinísticas.
- Separar testes unitários de testes de integração.
- Definir logs estruturados contendo:
  - identificador da execução;
  - duração;
  - volumes processados;
  - tentativas;
  - falhas.
- Criar utilitários compartilhados de horário, caminhos e identificação de execuções.
- Definir diferenças entre erros recuperáveis, erros de dados e falhas permanentes.

### Entregáveis

- Módulo de configuração validado.
- Base de testes e fixtures reutilizáveis.
- Padrão de logs estruturados.
- Modelo inicial de registro das execuções.

### Como validar

- Testar valores padrão e sobrescritas por variáveis de ambiente.
- Testar configurações inválidas.
- Verificar que logs não apresentam a chave de API.
- Executar a suíte local sem depender da internet.

### Critério de conclusão

Novos módulos conseguem receber configuração e emitir diagnósticos sem duplicar lógica.

### Risco principal

Configuração espalhada e logs informais tornam falhas de coleta difíceis de reproduzir.

---

## Etapa 4 — Implementar o cliente e o coletor assíncrono

### Objetivo

Buscar uma amostra pequena da OpenDota de forma controlada, resiliente e observável.

### O que será feito

- Criar um cliente HTTPX assíncrono.
- Configurar timeouts, cabeçalhos e autenticação opcional.
- Implementar paginação ou cursor conforme o endpoint validado.
- Adicionar repetição limitada com espera progressiva para:
  - falhas temporárias de rede;
  - respostas 429;
  - respostas 5xx.
- Não repetir automaticamente erros permanentes de autenticação ou parâmetros inválidos.
- Registrar quantidade solicitada, recebida, descartada e duração da coleta.
- Criar um comando explícito para executar a coleta.
- Manter a coleta completamente separada das requisições da API FastAPI.

### Entregáveis

- Cliente OpenDota isolado e testável.
- Coletor de uma amostra pequena.
- Resultado da coleta acompanhado de metadados da execução.
- Testes com respostas simuladas para sucesso, limite e falha.

### Como validar

- Executar uma coleta real pequena.
- Confirmar que os limites observados não foram ultrapassados.
- Simular timeout, 429, 5xx e payload inválido.
- Confirmar que uma falha parcial termina com estado e mensagem compreensíveis.

### Critério de conclusão

Uma execução controlada obtém partidas e informa com precisão o que aconteceu.

### Risco principal

Concorrência agressiva ou repetições ilimitadas podem bloquear o acesso e ocultar defeitos reais.

---

## Etapa 5 — Persistir a camada bruta em Parquet

### Objetivo

Preservar os dados de origem com rastreabilidade suficiente para reprocessar tudo sem consultar novamente a API.

### O que será feito

- Definir o esquema mínimo do registro bruto.
- Manter o payload original ou uma representação integral dele.
- Particionar os arquivos pela data da coleta e, quando útil, pela data da partida.
- Usar `match_id` como chave de deduplicação.
- Tornar novas execuções idempotentes.
- Gravar arquivos de forma segura para evitar resultados parciais em caso de interrupção.
- Salvar metadados da execução:
  - horário;
  - parâmetros;
  - volumes;
  - versão do coletor;
  - erros observados.
- Criar uma leitura simples para listar partições e reconstruir uma execução.

### Entregáveis

- Arquivos Parquet brutos particionados.
- Manifesto ou registro de execuções.
- Rotina de deduplicação.
- Capacidade de reprocessar uma amostra preservada.

### Como validar

- Executar a mesma coleta duas vezes.
- Confirmar que `match_id` não foi duplicado.
- Comparar contagens entre resposta recebida, manifesto e Parquet.
- Abrir os arquivos usando DuckDB e Pandas.
- Conferir tipos e campos essenciais.

### Critério de conclusão

A amostra real está preservada, auditável e pode ser relida sem acesso à rede.

### Risco principal

Descartar campos muito cedo pode impedir a correção de transformações sem uma nova coleta.

---

## Etapa 6 — Normalizar partidas, jogadores e itens

### Objetivo

Converter payloads variáveis em entidades limpas, consistentes e adequadas para análise.

### O que será feito

- Implementar `matches` com:
  - horário;
  - duração;
  - vencedor;
  - atributos disponíveis do recorte.
- Implementar `match_players` com:
  - herói;
  - equipe;
  - resultado;
  - posição, quando confiável.
- Implementar `player_items` com:
  - item;
  - slot;
  - momento de aquisição, quando disponível.
- Validar campos obrigatórios, tipos, equipes e identificadores.
- Validar a quantidade esperada de participantes.
- Tratar valores ausentes explicitamente.
- Não transformar informação desconhecida em zero ou falso.
- Registrar rejeições e seus motivos sem modificar a camada bruta.

### Entregáveis

- Parquet processado para `matches`.
- Parquet processado para `match_players`.
- Parquet processado para `player_items`.
- Relatório de qualidade com registros aceitos, rejeitados e campos ausentes.
- Transformações puras cobertas por testes determinísticos.

### Como validar

- Confirmar que cada participação referencia uma partida existente.
- Conferir equipes e vitórias com a fonte.
- Confirmar que o reprocessamento da mesma camada bruta produz o mesmo resultado.
- Testar campos ausentes, tipos inesperados e partidas incompletas.

### Critério de conclusão

As entidades processadas são reproduzíveis e suas perdas de dados são mensuradas.

### Risco principal

Inferências silenciosas sobre posição ou itens podem parecer fatos e contaminar recomendações.

---

## Etapa 7 — Criar o catálogo DuckDB e orquestrar o pipeline

### Objetivo

Centralizar metadados, visões e execuções para consultar Parquet por contratos estáveis.

### O que será feito

- Criar o arquivo `metadex.duckdb`.
- Criar tabelas operacionais para execuções e versões.
- Registrar visões sobre os arquivos Parquet brutos e processados.
- Definir a sequência explícita do pipeline:
  1. coletar;
  2. validar;
  3. normalizar;
  4. agregar;
  5. publicar.
- Impedir dois escritores simultâneos durante o MVP.
- Garantir que uma falha não publique agregações incompletas.
- Criar comandos separados para:
  - reprocessar dados existentes;
  - executar coleta e processamento completos.

### Entregáveis

- Catálogo DuckDB inicializado por código.
- Visões consultáveis das entidades processadas.
- Orquestrador local com estados claros de execução.
- Controle de publicação da última versão consistente.

### Como validar

- Recriar o catálogo a partir de um diretório de dados válido.
- Simular uma falha intermediária.
- Confirmar que a última versão consistente continua disponível.
- Comparar consultas de contagem e integridade com os arquivos Parquet.

### Critério de conclusão

Uma única operação reproduz o pipeline e publica somente resultados completos.

### Risco principal

Misturar escrita parcial com leitura da API pode apresentar números inconsistentes aos usuários.

---

## Etapa 8 — Calcular métricas e tendências de heróis

### Objetivo

Produzir indicadores diários e por janela com fórmulas explícitas, tamanho da amostra e filtros.

### O que será feito

- Calcular por herói e por dia:
  - escolhas;
  - vitórias;
  - derrotas;
  - taxa de escolha;
  - taxa de vitória.
- Implementar `hero_daily_stats`.
- Definir agregação para uma janela móvel, inicialmente de sete dias.
- Não somar ou tirar média simples de taxas já calculadas.
- Aplicar amostra mínima configurável aos rankings.
- Manter as contagens reais disponíveis para auditoria.
- Calcular variação temporal com bases comparáveis.
- Sinalizar quando não houver histórico suficiente.
- Incluir período, filtros e horário da última atualização.
- Criar recortes de habilidade somente quando sustentados pela fonte.

### Entregáveis

- `hero_daily_stats`.
- Agregações para janelas configuráveis.
- Consultas para ranking, detalhe e tendência.
- Testes das fórmulas com casos pequenos calculados manualmente.

### Como validar

- Confirmar que vitórias mais derrotas equivalem às escolhas para registros válidos.
- Confirmar que taxas permanecem nos intervalos esperados.
- Verificar o denominador documentado de cada taxa.
- Confirmar que amostras abaixo do limite não entram no ranking principal.
- Manter resultados abaixo do limite disponíveis para auditoria.

### Critério de conclusão

Os indicadores respondem quais heróis são escolhidos, quais vencem e como isso varia no recorte analisado.

### Risco principal

Rankear somente por taxa de vitória favorece amostras pequenas e transmite falsa certeza.

---

## Etapa 9 — Publicar o primeiro marco pela FastAPI

Esta etapa conclui o primeiro marco funcional do projeto.

### Objetivo

Expor métricas processadas por uma API versionada, previsível e independente da tecnologia de armazenamento.

### O que será feito

- Implementar `GET /health` sem revelar configurações sensíveis.
- Implementar `GET /api/v1/meta/heroes` com:
  - período;
  - filtros;
  - ordenação;
  - tamanho da amostra.
- Implementar detalhe por `hero_id`.
- Implementar tendência temporal por `hero_id`.
- Criar modelos consistentes de resposta e erro.
- Tratar parâmetros inválidos e períodos sem dados.
- Isolar repositórios de consulta para que o contrato não dependa diretamente do DuckDB.
- Gerar OpenAPI e exemplos coerentes com dados reais processados.

### Entregáveis

- `GET /health`.
- `GET /api/v1/meta/heroes`.
- `GET /api/v1/meta/heroes/{hero_id}`.
- `GET /api/v1/meta/heroes/{hero_id}/trend`.
- Testes unitários de contrato.
- Testes de integração com um banco temporário.

### Como validar

- Confirmar que as respostas incluem período, atualização, filtros e amostra.
- Confirmar que uma requisição da API nunca dispara coleta.
- Revisar o documento OpenAPI.
- Testar códigos HTTP, parâmetros inválidos e resultados vazios.
- Executar o fluxo com uma amostra real.

### Critério de conclusão

Uma amostra real percorre coleta, armazenamento e métricas até chegar ao endpoint de heróis.

### Risco principal

Acoplar as rotas diretamente aos detalhes do DuckDB dificulta a evolução do armazenamento e dos testes.

---

## Etapa 10 — Implementar recomendações explicáveis

### Objetivo

Sugerir heróis e itens com contexto, evidência e limites claros, sem apresentar correlação como causalidade.

### O que será feito

- Definir os contextos realmente suportados:
  - posição;
  - aliados;
  - adversários;
  - herói;
  - período;
  - recorte do meta.
- Criar `recommendation_stats` com desempenho e amostra para combinações válidas.
- Estabelecer regras de recuo quando filtros específicos produzirem pouca amostra.
- Ranquear heróis com critérios transparentes.
- Documentar critérios de desempate.
- Tratar recomendações de itens considerando:
  - duração da partida;
  - ordem de compra;
  - itens de fim de jogo;
  - viés de partidas que já estavam favoráveis.
- Expor recomendações acompanhadas de explicação, filtros e amostra.

### Entregáveis

- Agregações contextuais reproduzíveis.
- Recomendador de heróis.
- Recomendador de itens.
- `GET /api/v1/recommendations/heroes`.
- `GET /api/v1/recommendations/items`.

### Como validar

- Confirmar que cada sugestão inclui contexto e tamanho da amostra.
- Confirmar que cenários sem evidência suficiente não retornam rankings enganosos.
- Criar casos sintéticos para validar filtros, recuos e ordenação.
- Comparar recomendações com as estatísticas que as sustentam.

### Critério de conclusão

Cada recomendação pode ser explicada pelas estatísticas observadas e por suas limitações.

### Risco principal

Itens de fim de jogo e combinações raras podem refletir uma vantagem anterior, em vez de causar a vitória.

---

## Etapa 11 — Construir o dashboard responsivo

### Objetivo

Transformar contratos estáveis da API em navegação clara, filtros e visualizações que preservem o contexto estatístico.

### O que será feito

- Criar um cliente tipado da API.
- Implementar estados de:
  - carregamento;
  - resultado vazio;
  - erro;
  - dados desatualizados.
- Criar tabela de heróis com escolhas, vitórias, taxas e amostra.
- Adicionar filtros de período e habilidade somente quando suportados pela API.
- Criar página de detalhe do herói.
- Criar gráfico de tendência temporal.
- Criar fluxos de recomendação de heróis e itens.
- Manter explicações e amostras visíveis.
- Revisar:
  - acessibilidade;
  - comportamento em dispositivos móveis;
  - contraste;
  - navegação por teclado;
  - legibilidade dos gráficos.

### Entregáveis

- Dashboard Next.js responsivo.
- Componentes reutilizáveis de filtros, tabelas, gráficos e estados.
- Integração tipada com os endpoints do MVP.
- Páginas de visão geral, detalhe e recomendações.

### Como validar

- Executar ESLint.
- Executar o build de produção.
- Testar os fluxos principais em larguras mobile e desktop.
- Navegar usando teclado.
- Confirmar que período, filtros, amostra e atualização permanecem visíveis.
- Simular respostas vazias, lentas e com erro.

### Critério de conclusão

Um jogador consegue explorar o meta e entender de onde cada número ou sugestão veio.

### Risco principal

Uma interface atraente sem contexto pode transformar estimativas frágeis em certezas aparentes.

---

## Etapa 12 — Automatizar, monitorar e preparar a entrega

### Objetivo

Executar atualizações diárias com controle de qualidade e tornar o MVP reproduzível para uso contínuo.

### O que será feito

- Agendar coleta e processamento diário.
- Manter um bloqueio para garantir apenas um escritor.
- Definir retenção, limpeza e recuperação de dados.
- Preservar a camada bruta necessária para reprocessamento.
- Monitorar:
  - atraso da atualização;
  - volume anormal;
  - falhas;
  - limites da API;
  - degradação da qualidade dos dados.
- Criar verificações completas de backend e frontend para integração contínua.
- Documentar backup do DuckDB.
- Documentar reconstrução do catálogo a partir do Parquet.
- Criar um procedimento de resposta a falhas.
- Executar revisão final de segurança, desempenho, acessibilidade e qualidade estatística.

### Entregáveis

- Rotina diária automatizada e observável.
- Alertas acionáveis.
- Checklist de release.
- Procedimento de recuperação.
- MVP documentado e reproduzível.

### Como validar

- Executar duas atualizações consecutivas sem duplicar dados.
- Simular uma falha de coleta ou processamento.
- Confirmar que a última publicação válida permanece disponível.
- Confirmar que a falha produz um alerta compreensível.
- Executar pipeline, testes da API e build web em ambiente limpo.
- Reconstruir o DuckDB a partir dos arquivos preservados.

### Critério de conclusão

O Metadex atualiza diariamente, detecta falhas e pode ser reconstruído a partir dos dados preservados.

### Risco principal

Automação sem alertas pode manter um dashboard aparentemente normal usando dados antigos ou incompletos.

---

## Marcos de entrega

| Marco | Etapas | Evidência de conclusão |
|---|---:|---|
| Base confiável | 1 a 3 | Ambientes reproduzíveis, fonte validada e infraestrutura de testes pronta |
| Dado durável | 4 a 7 | Amostra real preservada, normalizada e consultável no DuckDB |
| Primeiro marco funcional | 8 e 9 | `GET /api/v1/meta/heroes` responde métricas reais com período e amostra |
| Produto analítico | 10 e 11 | Recomendações explicáveis e dashboard responsivo consumindo a API |
| MVP operável | 12 | Atualização diária, alertas e recuperação documentada |

## Regra para iniciar cada etapa

Antes de codificar:

1. confirmar as entradas necessárias;
2. identificar os arquivos que serão alterados;
3. definir a evidência usada para considerar a etapa concluída;
4. evitar antecipar funcionalidades de etapas futuras.

Ao terminar:

1. executar as validações pertinentes;
2. registrar as ferramentas utilizadas;
3. produzir um roteiro de testes reproduzível;
4. registrar limitações ou decisões relevantes;
5. somente então avançar para a etapa seguinte.

## Resultado esperado

Um catálogo estatístico que informa o que aconteceu no recorte analisado, mostra a força da evidência e evita transformar correlação em certeza.
