# Etapa 12: operação do MVP

## Instalação e agendamento

Use um host Linux com `systemd --user`, `uv`, acesso à OpenDota e diretório de dados persistente. Configure `backend/.env` a partir de `backend/.env.example`, execute `uv sync --frozen --group dev` em `backend/` e faça uma execução manual antes do agendamento:

```bash
cd backend
uv run --frozen python -m app.operations daily --count 20 --max-pages 2
uv run --frozen python -m app.operations monitor
```

O comando diário coleta até 20 partidas e seus detalhes por padrão, reprocessa o arquivo bruto cumulativo, aplica a barreira de qualidade (até 5% de partidas rejeitadas) e publica uma versão completa. `--no-details` reduz as chamadas à OpenDota, mas deixa itens de novas partidas indisponíveis. Coleta parcial, limite de API, falha de qualidade e erro de publicação terminam com código diferente de zero; a publicação anterior permanece ativa. O bloqueio de escritor único já cobre a coleta e o processamento. Repetições usam deduplicação por `match_id`.
Se uma consulta da API ou outro escritor mantiver o catálogo ocupado, a rotina tenta obter o bloqueio até três vezes com espera curta. O campo `scheduler_attempts` registra esse caso.

Se a fonte começar a produzir registros inválidos, inspecione `quality.json` e os manifestos brutos. Corrija a transformação ou investigue a fonte; `--max-rejected-percent` só deve ser elevado após essa análise. A rotina nunca remove registros brutos inválidos automaticamente.

No host que executará o serviço:

```bash
python3 ops/install_systemd.py
systemctl --user list-timers 'metadex-*'
systemctl --user status metadex-daily.timer metadex-monitor.timer
```

O timer diário inicia às 03:15 UTC e o monitor roda a cada hora. `Persistent=true` recupera horários perdidos quando o usuário volta a iniciar sessão. Para executar mesmo sem sessão interativa, habilite `loginctl enable-linger "$USER"` com as permissões apropriadas do host. O instalador escreve unidades em `~/.config/systemd/user/` e não deve ser executado em checkout de desenvolvimento que não seja o host operacional.

## Monitoramento e resposta

`python -m app.operations monitor` devolve JSON e código `0` quando saudável ou `2` quando há alerta. Ele verifica a última rotina, execução presa por mais de duas horas, catálogo consultável e publicação com até 36 horas. A rotina diária registra `backend/data/operations/daily-status.json` com horário, versão, volume, tentativas, falhas e alertas. Repetições da fonte e zero partidas novas geram alerta diagnóstico; a atualização ainda conclui. Falha ou coleta parcial gera código `1` e mantém a versão anterior.

Consulte `journalctl --user -u metadex-daily.service -u metadex-monitor.service --since today` e o JSON do monitor. Configure o supervisor do host para notificar quando qualquer serviço terminar com código diferente de zero; o destino de alerta (email, pager, webhook) depende da implantação. Para erro de API ou limite, consulte as tentativas e os cabeçalhos nos logs do coletor e espere a janela da OpenDota antes de repetir. Para `publication_stale`, verifique timer, último status e `pipeline_runs`. Para `catalog_unavailable`, aguarde o escritor terminar; se persistir, siga a recuperação abaixo.

## Backup, retenção e recuperação

Preserve **todo** `backend/data/raw/` e o snapshot processado atual em backup externo ao host. O catálogo DuckDB sozinho não contém os Parquets: suas visões apontam para eles. Faça backup após a rotina diária, com o escritor ocioso:

```bash
cd backend
uv run --frozen python -m app.operations backup --destination /caminho/backup/metadex.duckdb
```

O comando verifica ausência de WAL, copia o arquivo e cria um recibo com SHA-256 e versão. Copie `data/raw/` e `data/processed/versions/` junto com ele, preservando os mesmos caminhos no host restaurado. Mantenha o backup fora de `data/`; teste periodicamente a reconstrução em um diretório de teste.

Retenção padrão: todos os dados brutos e catálogos de origem são mantidos; versões processadas ficam por no mínimo 30 dias e sempre são preservadas a atual e a anterior. A limpeza é explícita e começa com prévia:

```bash
uv run --frozen python -m app.operations prune
uv run --frozen python -m app.operations prune --apply
```

Execute a limpeza somente após backup e com a API parada: o comando abre o catálogo para escrita, inclusive na prévia. Ele usa o mesmo bloqueio e nunca remove `raw/`. Históricos de execuções permanecem no catálogo, mas versões processadas eliminadas deixam de ser reconstruíveis; o bruto ainda permite um `reprocess` completo.

Se o catálogo estiver corrompido ou ausente, pare API, timers e escritores. Guarde uma cópia do arquivo defeituoso. Com os arquivos brutos e versões publicados preservados, remova ou renomeie o catálogo defeituoso e rode:

```bash
uv run --frozen python -m app.pipeline rebuild
uv run --frozen python -m app.operations monitor
```

`rebuild` verifica hashes, esquemas e contagens, e restaura somente publicações completas. Se faltar uma versão processada mas o bruto estiver íntegro, rode `uv run --frozen python -m app.pipeline reprocess` para gerar outra. Depois reinicie a API e os timers. Falhas operacionais históricas do DuckDB perdido não são reconstruídas, por isso preserve também logs e recibos dos backups.

## Checklist de release

- [ ] `uv sync --frozen --group dev` e `pnpm install --frozen-lockfile` em ambiente limpo.
- [ ] `uv run --frozen ruff check .` e `uv run --frozen pytest` em `backend/`.
- [ ] `pnpm lint` e `pnpm build` em `frontend/`.
- [ ] Duas rotinas diárias consecutivas sem duplicar `match_id`; validar versões e contagens.
- [ ] Simular rejeição de qualidade; confirmar versão anterior e alerta acionável.
- [ ] Confirmar backup, reconstrução e restauração das consultas da API.
- [ ] Revisar `CORS_ORIGINS`, segredos fora do Git, permissões dos diretórios e acesso de rede.
- [ ] Verificar `GET /health`, ranking, detalhe, tendência e recomendações após a publicação.
- [ ] Verificar largura mobile e desktop, teclado, contraste e textos de amostra/contexto.
- [ ] Avaliar tempo do pipeline, tamanho dos Parquets e período de sete dias com dados reais.
- [ ] Conferir limites estatísticos: amostra mínima, recuos e interpretação não causal das recomendações.

A CI executa lint, testes offline e build web. Ela não substitui a verificação de dados reais, acessibilidade manual, permissões do host nem a ativação dos timers.

## Roteiro de validação reproduzível

Ferramentas usadas: Python, pytest, Ruff, DuckDB, `systemd-analyze`, Node.js e Next.js. No checkout de desenvolvimento, as fixtures da OpenDota exercitam duas atualizações, deduplicação, falha de qualidade, backup e reconstrução sem rede:

```bash
cd backend
uv run --frozen ruff check .
uv run --frozen pytest tests/integration/test_operations.py tests/integration/test_pipeline.py tests/integration/test_processed_storage.py tests/integration/test_raw_storage.py
uv run --frozen pytest
cd ../frontend
pnpm lint
pnpm build
```

No host operacional, faça o ensaio manual de `daily`, `monitor`, `backup` e `rebuild` em um diretório de dados de teste antes de ativar os timers. Valide os horários com `systemd-analyze calendar '*-*-* 03:15:00 UTC'`.
