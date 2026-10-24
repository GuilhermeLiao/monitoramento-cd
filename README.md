# Monitor de reputação digital

Coleta semanal de indicadores públicos de reputação de instituições financeiras
brasileiras (lojas de apps, Reclame Aqui, Consumidor.gov.br, Instagram) em um
PostgreSQL no Neon, com views prontas para Looker Studio, Metabase ou Power BI.

Nenhum dado pessoal de consumidor é armazenado: só métricas e atributos categóricos.

> Estado atual: prontos os coletores das lojas de apps (`app_store` e `google_play`,
> nota média de cada app) e do Consumidor.gov.br (`consumidor_gov`, indicadores do
> ano corrente), e a importação semiautomática do Reclame Aqui (indicadores de
> 6 meses, via botão no navegador). Instagram ainda não foi implementado.
>
> O projeto grava só indicadores agregados, como aparecem nas páginas das fontes
> (notas, totais, percentuais). Reclamações e avaliações individuais não são coletadas.

## 1. Criar o banco no Neon

1. Crie uma conta em <https://neon.tech> e um projeto (região `sa-east-1`, PostgreSQL 15 ou superior).
2. O projeto já vem com o branch `production`. Em **Branches → Create branch**, crie
   um branch chamado `dev` a partir dele.
3. Em **Connect**, copie a string de conexão de **cada** branch. Use a conexão
   direta (sem "Connection pooling"): o host não deve conter `-pooler`.

| Branch       | Onde a string fica                         | Usado para                   |
|--------------|--------------------------------------------|------------------------------|
| `dev`        | arquivo `.env` no seu computador           | desenvolvimento e testes     |
| `production` | GitHub Secret `DATABASE_URL`               | coleta semanal (Actions)     |

A string de produção não deve ficar no `.env`: os testes e as migrações locais
rodam contra o que estiver lá.

## 2. Configurar o ambiente local (Windows)

Pré-requisitos: [Git](https://git-scm.com/download/win) e [uv](https://docs.astral.sh/uv/).
No PowerShell:

```powershell
# instala o uv (uma vez)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

git clone https://github.com/GuilhermeLiao/monitoramento-cd.git
cd monitoramento-cd

# instala o Python 3.12 e as dependências em .venv
uv sync

# cria o .env a partir do modelo e edita
Copy-Item .env.example .env
notepad .env
```

No `.env`:

```
DATABASE_URL=postgresql://usuario:senha@ep-xxxx.sa-east-1.aws.neon.tech/neondb?sslmode=require
AMBIENTE=dev
```

`AMBIENTE=dev` é o que libera os testes de banco. Só defina se a `DATABASE_URL`
for mesmo a do branch `dev`.

## 3. Criar as tabelas e carregar a configuração

```powershell
uv run alembic upgrade head     # cria tabelas, catálogos e views
uv run monitor sync-config      # carrega config/instituicoes.yaml
```

Edite `config/instituicoes.yaml` para cadastrar as instituições e seus perfis
(o arquivo traz um exemplo comentado) e rode `sync-config` de novo. O comando é
idempotente; o que sair do YAML fica inativo no banco, nunca é apagado.

### Identificadores dos apps

Abra a página do app na loja do Brasil e copie o identificador da URL:

| Plataforma    | Identificador                 | Exemplo de URL                                                   |
|---------------|-------------------------------|------------------------------------------------------------------|
| `app_store`   | o número depois de `id`       | `https://apps.apple.com/br/app/nome-do-app/id`**`123456789`**    |
| `google_play` | o valor do parâmetro `id=`    | `https://play.google.com/store/apps/details?id=`**`com.exemplo.app`** |

Cada app é um perfil; use `rotulo` para distinguir os apps da mesma instituição
(por exemplo, "App PF" e "App PJ").

### Identificador do Consumidor.gov.br

Busque a empresa em <https://www.consumidor.gov.br> e abra o perfil dela. O
identificador é o número da URL: `https://www.consumidor.gov.br/pages/empresa/`**`20191119001741080`**`/perfil`.

## 4. Comandos

```powershell
uv run monitor coletar <coletor>       # roda um coletor (app_store, google_play, consumidor_gov)
uv run monitor coletar lojas           # roda app_store e google_play
uv run monitor coletar todos           # roda todos
uv run monitor importar-reclame-aqui <arquivo.json>  # grava a captura do botão do Reclame Aqui
uv run monitor botao-reclame-aqui      # gera a página que instala o botão
uv run monitor sync-config             # sincroniza o YAML com o banco
uv run monitor limpar-brutos --dias 180  # apaga respostas brutas antigas
uv run monitor status                  # últimas execuções e falhas por perfil
uv run monitor --help
```

`coletar` lista os perfis que falharam e o motivo, e sai com código 1 quando um
coletor falha em todos os perfis. Os logs saem em JSON (uma linha por evento) no
stderr.

Os coletores das lojas gravam só a nota média (`nota_media`) de cada app, sem
arredondar. Se a loja não devolver uma nota válida (app removido, sem avaliações
ou resposta fora do esperado), o perfil fica com erro e nada é gravado para ele.
No Google Play, vários perfis com "nota ausente" de uma vez indicam que a
biblioteca `google-play-scraper` deixou de entender a página da loja.

O coletor `consumidor_gov` grava os indicadores da aba do ano corrente (por
exemplo, "2026") do perfil de cada empresa, com `periodo_inicio` = 1º de janeiro
e `periodo_fim` = dia da coleta:

| Na página                        | Métrica               |
|----------------------------------|-----------------------|
| Total de Reclamações Finalizadas | `total_reclamacoes`   |
| Índice de Solução (%)            | `pct_resolvidas`      |
| Satisfação com o Atendimento (1 a 5) | `nota_consumidor` |
| Reclamações Respondidas (%)      | `pct_respondidas`     |
| Prazo Médio de Respostas (dias)  | `tempo_resposta_dias` |

Indicador exibido como "S/R" (sem registros) é gravado como nulo. Os números
vêm do mesmo JSON que a página usa (`/pages/empresa/<token>/aba/ANUAL/periodo/998/perfil.json`;
o token é lido da própria página de perfil). Se o site mudar e todos os perfis
falharem com "sem a aba do ano", reveja `_ABA_ANUAL` em
`src/monitor/coletores/consumidor_gov.py`.

### Reclame Aqui (semiautomático, uma vez por mês)

O Reclame Aqui bloqueia acesso automatizado (desafio anti-robô do Cloudflare), e
o projeto não contorna essa proteção. A captura é feita por você, no seu
navegador, com um botão de favorito que lê os números do painel "6 meses":

1. `uv run monitor botao-reclame-aqui` gera `dados/botao_reclame_aqui.html`
   com a lista de empresas do YAML. Abra esse arquivo no navegador e siga as
   instruções para arrastar o botão **📌 Monitor RA** para a barra de favoritos.
   Gere a página de novo sempre que mudar os perfis `reclame_aqui` do YAML.
2. Abra a página de cada empresa no Reclame Aqui e clique no botão. O painel
   mostra o que foi capturado e as empresas que faltam, com links.
3. Clique em **Baixar arquivo** e importe:
   `uv run monitor importar-reclame-aqui "$HOME\Downloads\reclame_aqui_AAAA-MM-DD.json"`
4. Clique em **Limpar** no painel para começar o próximo mês do zero.

| No painel                  | Métrica                 |
|----------------------------|-------------------------|
| Reclamações recebidas      | `total_reclamacoes`     |
| Reclamações respondidas    | `pct_respondidas`       |
| Aguardando resposta        | `aguardando_resposta`   |
| Reclamações resolvidas     | `pct_resolvidas`        |
| Voltariam a fazer negócio  | `pct_voltaria_negocio`  |
| Reclamações avaliadas      | `reclamacoes_avaliadas` |
| Nota média do consumidor (0 a 10) | `nota_consumidor` |
| Tempo médio de resposta    | `tempo_resposta_dias` ("10 dias e 10 horas" = 10,4167) |
| Nota "x/10" da reputação   | `nota_reclame_aqui`     |
| Reputação (Ótimo, Bom...)  | `status_reputacao` (texto) |

O período vem do "Dados de ... até ..." do painel; capturas de outra aba (12
meses, 2025...) são recusadas. A data de referência é o dia da captura. Empresas
que ficaram fora do arquivo aparecem como erro em `monitor status`.

Se o site mudar e o botão disser que não encontrou o painel, os rótulos
procurados estão em `src/monitor/ferramentas/botao_reclame_aqui.html` (lista
`ROTULOS`) e em `src/monitor/coletores/reclame_aqui.py`.

Migrações:

```powershell
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic revision -m "descricao"   # nova migração (escrita à mão)
```

## 5. Testes

```powershell
uv run pytest
uv run pytest -m live    # opcional: consulta as fontes reais, pela rede
```

Os testes de banco criam um schema temporário (`teste_xxxx`) no banco do `.env`,
rodam as migrações nele e o apagam ao final; não tocam nas tabelas reais. Sem
`AMBIENTE=dev` eles são pulados e só rodam os testes de validação do YAML.

## 6. GitHub Actions

O workflow `.github/workflows/coleta-semanal.yml` roda toda segunda-feira às
08h de Brasília (11h UTC) e pode ser disparado manualmente em **Actions →
Coleta semanal → Run workflow**, escolhendo o coletor.

Em **Settings → Secrets and variables → Actions → New repository secret**, crie:

| Secret         | Valor                                            |
|----------------|--------------------------------------------------|
| `DATABASE_URL` | string de conexão do branch `production` do Neon |

Cada coletor acrescentará os próprios segredos (por exemplo, o token da Graph
API do Instagram) quando for implementado.

O workflow aplica as migrações e o `sync-config` em produção antes de coletar.
Portanto, o que estiver na `main` é o que vale para o banco de produção.

## 7. Painéis

Conecte a ferramenta de BI ao Neon (de preferência com um usuário somente
leitura) e use as views:

| View                        | Conteúdo                                                        |
|-----------------------------|-----------------------------------------------------------------|
| `vw_metricas_atuais`        | último valor de cada métrica por perfil ativo                   |
| `vw_metricas_mensais`       | último snapshot de cada mês por perfil e métrica                |

Para comparar instituições numa fonte, filtre `plataforma_codigo` e
`metrica_codigo` em `vw_metricas_atuais`. As colunas `periodo_inicio` e
`periodo_fim` dizem a janela de cada indicador (vazias para valores do momento).

## Estrutura

```
config/instituicoes.yaml     instituições e perfis monitorados
src/monitor/
    settings.py              variáveis de ambiente
    config_loader.py         validação do YAML
    cli.py                   comandos `monitor ...`
    db/                      modelos, sessão e repositórios
    coletores/               interface base, executor e os coletores
migrations/                  Alembic
sql/views/                   views para BI
tests/
```

Detalhes de modelagem e convenções estão em [CLAUDE.md](CLAUDE.md).
