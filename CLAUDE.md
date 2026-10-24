# Monitor de reputação digital

Projeto pessoal que coleta periodicamente indicadores públicos de reputação de
instituições financeiras brasileiras (todas contas de terceiros), grava em
PostgreSQL (Neon) e alimenta comparativos e painéis de BI (Looker Studio,
Metabase ou Power BI) direto no banco.

## Fontes (um coletor por fonte)

**Escopo: só indicadores agregados**, como a fonte os exibe na tela (notas,
totais, percentuais). Nada de reclamações, avaliações ou posts individuais:
decisão do dono do projeto (24/10/2026). Prefira a fonte que entrega o indicador
pronto a recalculá-lo a partir de dados brutos. As tabelas `reclamacoes_*` e
`arquivos_processados` existem (migração 0001), mas ficam sem uso. Exceção: no
Instagram, o dono quer a lista de posts do último mês inteiro com data e
curtidas (`posts_instagram`, `snapshots_posts_instagram`).

| Coletor / plataforma | Como coleta | O que coleta | Janela |
|---|---|---|---|
| `app_store` | iTunes Lookup API (em lote) | nota média | atual |
| `google_play` | biblioteca google-play-scraper, isolada em `adaptador_google_play.py` | nota média | atual |
| `reclame_aqui` | semiautomático: botão de favorito no navegador do dono (`src/monitor/ferramentas/botao_reclame_aqui.html`) gera um JSON, importado por `monitor importar-reclame-aqui` (`coletores/reclame_aqui.py`, fora do registro e do Actions) | total, % respondidas, aguardando resposta, % resolvidas, voltaria a fazer negócio, avaliadas, nota do consumidor (0–10), tempo de resposta, nota RA, status de reputação | 6 meses (padrão do site) |
| `consumidor_gov` | JSON da aba do ano no perfil da empresa (token lido da página) | total finalizadas, índice de solução, satisfação, % respondidas, prazo médio | ano corrente (1º/jan até a coleta) |
| `instagram` | Graph API Business Discovery (conta profissional do dono ligada a uma Página) | seguidores; posts do último mês inteiro com data e curtidas (exceção pedida pelo dono) | atual / último mês inteiro |

Outras redes sociais (só seguidores) ficaram fora por decisão do dono; X,
LinkedIn e TikTok não têm API pública viável. Futuro: ranking de reclamações do
Banco Central.

Estado: `app_store`, `google_play` (`monitor coletar lojas` roda os dois),
`consumidor_gov`, `instagram` e a importação do `reclame_aqui` implementados.

Instagram: `META_ACCESS_TOKEN` (token de Página, vai no cabeçalho Authorization,
nunca na URL) e `IG_USER_ID`; `META_GRAPH_API_VERSION` padrão `v26.0`. O acesso
a dados do token vence a cada 90 dias; o coletor expõe `avisos` que a CLI mostra.

**Sem contornar anti-robô**: o Reclame Aqui bloqueia acesso automatizado
(Cloudflare). Não implemente impersonação de navegador (curl_cffi), Chromium
headless nem outro meio de passar pelo desafio; a captura é feita pelo dono.

Das lojas só se grava `nota_media`, por decisão do dono do projeto: a quantidade
de avaliações é lida apenas para validar a nota e fica no payload bruto.

## Restrições inegociáveis

- **Privacidade**: nunca armazenar dados pessoais de consumidores (nome, texto
  livre ou título de reclamação, cidade, idade, gênero). Só métricas e atributos
  categóricos. Isso vale também para `respostas_brutas`: remova esses campos do
  payload antes de gravar.
- **Sem navegador**: nenhum coletor usa Selenium, Playwright ou Chromium, nem
  depende de classes CSS. Só APIs, bibliotecas e arquivos.
- **Desconhecido não é zero**: valor que não pôde ser obtido vira `None` ou erro
  registrado no perfil. Nunca gravar 0 no lugar de "não sei".
- **Banco de produção**: nunca rodar testes nem experimentos contra ele. O `.env`
  local aponta para o branch `dev` do Neon; a string de produção existe só nos
  GitHub Secrets.
- **Espaço**: plano gratuito do Neon, 0,5 GB. Não guardar payloads grandes em
  `respostas_brutas`.
- Cada coletor roda no GitHub Actions (semanal) e localmente no Windows via CLI.

## Stack

Python 3.12 com uv; SQLAlchemy 2.x tipado + psycopg 3; Alembic; Typer;
pydantic-settings; logging JSON (stdlib, `logging_config.py`); pytest.

## Como rodar

```powershell
uv sync
uv run alembic upgrade head
uv run monitor sync-config
uv run monitor coletar <coletor> | todos
uv run monitor status
uv run monitor limpar-brutos --dias 180
uv run pytest
```

Variáveis (`.env`): `DATABASE_URL` (obrigatória), `AMBIENTE` (`dev` libera os
testes de banco), `LOG_LEVEL`, `CONFIG_PATH`, `DB_SCHEMA` (uso dos testes),
`META_ACCESS_TOKEN`, `IG_USER_ID`, `META_GRAPH_API_VERSION` (Instagram).

Testes de banco usam um schema temporário `teste_*` criado pelo `conftest.py`
e são pulados sem `AMBIENTE=dev`.

## Modelagem

Nomes em português, snake_case. PK `bigint identity`. Timestamps `timestamptz`
(UTC). Datas de referência (`data_referencia`, `data_coleta`) no fuso
`America/Sao_Paulo` (`settings.FUSO_REFERENCIA`). Categorias são `text` com
CHECK, não enum nativo.

| Tabela | Papel |
|---|---|
| `instituicoes` | cadastro; `nome_curto` é a chave do upsert vindo do YAML |
| `plataformas` | catálogo (PK `codigo`); rede nova = um insert por migração |
| `perfis` | app, slug ou username de uma instituição numa plataforma; único em (`plataforma_codigo`, `identificador`); várias por instituição, distinguidas por `rotulo` |
| `metricas` | catálogo de códigos de métrica (PK `codigo`) |
| `execucoes` | uma linha por rodada de coletor: status `em_andamento`/`sucesso`/`parcial`/`erro`, contagens e `detalhes.erros` por perfil |
| `snapshots_metricas` | valores das métricas; único em (`perfil_id`, `metrica_codigo`, `data_referencia`, `periodo_inicio`, `periodo_fim`) com NULLS NOT DISTINCT, então reexecutar no dia faz upsert |
| `respostas_brutas` | payload original de APIs pequenas, para reprocessar; limpo por `limpar-brutos` |
| `posts_instagram` | posts (único em `media_id`) |
| `snapshots_posts_instagram` | curtidas e comentários por post e dia; único em (`post_id`, `data_coleta`) |
| `arquivos_processados`, `reclamacoes_consumidor_gov`, `reclamacoes_reclame_aqui` | sem uso (fora do escopo de só indicadores) |

Views (`sql/views/`, criadas pela migração 0003), todas com instituição, rótulo
do perfil e plataforma: `vw_metricas_atuais` e `vw_metricas_mensais`; e
`vw_instagram_posts` (migração 0005): posts com a contagem mais recente.
`vw_consumidor_gov_periodo` também existe, mas lê `reclamacoes_consumidor_gov`
e fica vazia.

### Migrações

- Escritas à mão em `migrations/versions/NNNN_descricao.py`, com downgrade.
- Mudou `db/models.py`? Crie a migração. `test_modelos_batem_com_as_migracoes`
  falha se os dois divergirem.
- Mudou uma view? Edite o `.sql` e crie uma migração que o reaplique
  (`DROP VIEW` + arquivo, se colunas mudarem de posição ou tipo).
- Nomes de constraints e índices são explícitos: `uq_`, `ck_`, `ix_` + tabela.

## Convenções de métricas

Todo valor gravado em `snapshots_metricas` usa um código do catálogo `metricas`.
Métrica nova entra por migração (insert), antes de o coletor usá-la.

- snake_case, em português, sem nome de plataforma no código (a plataforma vem do perfil).
- Percentuais: prefixo `pct_`, escala 0 a 100.
- Durações: unidade no nome (`tempo_resposta_dias`).
- Categorias: código descritivo, valor em `valor_texto` e `valor` nulo.
- Valor do momento (nota, seguidores): `periodo_inicio` e `periodo_fim` nulos.
- Valor de janela ("últimos 6 meses", "agosto/2026"): preencher os dois.
  As views pegam o snapshot mais recente por métrica; se uma fonte publicar a
  mesma métrica em janelas diferentes ao mesmo tempo, crie um código por janela.

Catálogo atual: `nota_media`, `total_avaliacoes`, `seguidores`, `posts_periodo`,
`aguardando_resposta`, `reclamacoes_avaliadas`, `nota_reclame_aqui` (0004),
`total_reclamacoes`, `pct_respondidas`, `pct_resolvidas`, `nota_consumidor`,
`tempo_resposta_dias`, `pct_voltaria_negocio`, `status_reputacao`.

## Como escrever um coletor

1. Crie `src/monitor/coletores/<nome>.py` com uma classe que herda de `Coletor`
   (`coletores/base.py`), define `nome` e `plataforma` e implementa
   `coletar(perfil) -> ResultadoColeta`. `coletar` não acessa o banco.
2. Decore a classe com `@registrar` e importe o módulo no final de
   `coletores/__init__.py`.
3. Devolva `RegistroMetrica` para métricas e `RespostaBrutaColetada` para o
   payload original. Registros próprios da fonte (reclamações, posts) vão em
   `ResultadoColeta.registros` e são gravados sobrescrevendo `gravar_registros`.
4. Levante exceção quando o perfil falhar: o executor (`coletores/executor.py`)
   isola o erro, grava cada perfil em sua própria transação e registra tudo em
   `execucoes`.
5. Fonte com consulta em lote? Sobrescreva `preparar(perfis)`, chamado uma vez
   antes dos perfis; `coletar` continua funcionando sem ele. Retentativas usam
   `coletores/tentativas.py` (levante `ErroTransitorio` para repetir).
6. Descomente o passo do coletor em `.github/workflows/coleta-semanal.yml` e
   documente os segredos novos no README e no `.env.example`.

## Configuração de instituições

`config/instituicoes.yaml` é a fonte da verdade; `monitor sync-config` valida
(pydantic, `config_loader.py`) e faz upsert. Itens removidos do YAML ficam
`ativo = false`, nunca são apagados. Plataformas são validadas contra a tabela
`plataformas`.

## Git

Repositório privado `GuilhermeLiao/monitoramento-cd`, branch `main`. Commits
pequenos por etapa. O `.env` nunca é versionado.
