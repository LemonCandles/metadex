# Fixtures da OpenDota

Projeções anonimizadas de respostas reais capturadas sem chave de API em 18 de
setembro de 2026.

| Arquivo | Origem | Propósito |
|---|---|---|
| `public_matches_high_skill.json` | `/publicMatches?min_rank=70` | Mostra uma partida elegível, uma com pouca cobertura de rank e uma Turbo |
| `match_detail_unparsed.json` | `/matches/9005421215` | Mostra inventário final com rota e compras ausentes |
| `match_detail_parsed.json` | `/matches/9005425491` | Mostra rota e compras depois do processamento do replay |
| `constants.json` | `/constants/*` | Exemplos mínimos de heróis, itens, modos e lobbies |

Os objetos mantêm somente os campos necessários para a validação da etapa 2.
Identificadores e nomes de jogadores, chat e demais dados pessoais foram
removidos. Em `match_detail_parsed.json`, cada `purchase_log` foi limitado às
cinco primeiras entradas. Nenhum valor preservado foi inventado.

Essas projeções não representam o futuro armazenamento bruto integral. Consulte
`docs/contracts/raw-opendota.md` para essa distinção.
