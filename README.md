# Monitor de reputação digital

Coleta semanal de indicadores públicos de reputação de instituições financeiras
brasileiras (lojas de apps, Reclame Aqui, Consumidor.gov.br, Instagram) em um
PostgreSQL no Neon, com views prontas para Looker Studio, Metabase ou Power BI.

Nenhum dado pessoal de consumidor é armazenado: só métricas e atributos categóricos.

> Estado atual: prontos os coletores das lojas de apps (`app_store` e `google_play`,
> nota média de cada app) e do Consumidor.gov.br (`consumidor_gov`, indicadores do
> ano corrente), e a importação semiautomática do Reclame Aqui (indicadores de
> 6 meses, via botão no navegador) e do Instagram (`instagram`, seguidores e posts
> do último mês inteiro com curtidas).
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
uv run monitor coletar <coletor>       # roda um coletor (app_store, google_play, consumidor_gov, instagram)
uv run monitor coletar lojas           # roda app_store e google_play
uv run monitor coletar todos           # roda todos
uv run monitor importar-reclame-aqui <arquivo.json>  # grava a captura do botão do Reclame Aqui
uv run monitor botao-reclame-aqui      # gera a página que instala o botão
uv run monitor painel                  # gera e abre o dashboard local
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

### Instagram

O coletor `instagram` usa a Graph API da Meta (recurso Business Discovery), que
lê dados públicos de contas profissionais a partir de uma conta profissional sua.
A cada execução grava, por perfil:

- `seguidores` (valor atual);
- `posts_periodo`: quantidade de posts do **último mês inteiro** (no fuso de Brasília);
- cada post desse mês em `posts_instagram`, com data, e a contagem de curtidas e
  comentários do dia em `snapshots_posts_instagram`. Perfil que esconde as
  curtidas fica com `curtidas` nula e `curtidas_ocultas = true` (nunca zero).

A view `vw_instagram_posts` lista os posts com a contagem mais recente
(`mes_publicacao` facilita filtrar o mês). O `identificador` do perfil no YAML é
o username, sem @. Contas pessoais ou inexistentes aparecem como erro.

#### Credenciais (uma vez)

1. Tenha uma conta profissional do Instagram ligada a uma Página do Facebook da
   qual a sua conta pessoal do Facebook é administradora.
2. Em <https://developers.facebook.com>, crie um app do tipo **Empresa** com o
   produto **Login do Facebook para Empresas**. O app pode ficar em modo de
   desenvolvimento: como você é administrador, não precisa de revisão da Meta.
3. No [Graph API Explorer](https://developers.facebook.com/tools/explorer),
   deixe o servidor em **graph.facebook.com** (não graph.instagram.com), escolha
   o app e **Token do usuário**, adicione as permissões `instagram_basic`,
   `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement` e
   `business_management` e clique em **Generate Access Token**.
4. Rode `me/accounts?fields=name,instagram_business_account`: o
   `instagram_business_account.id` é o `IG_USER_ID`.
5. Teste: `<IG_USER_ID>?fields=business_discovery.username(nubank){followers_count}`.
6. Token que não expira: no [depurador de token](https://developers.facebook.com/tools/debug/accesstoken),
   cole o token, **Depurar** → **Estender token de acesso**. Com esse token de 60
   dias no Explorer, rode `me/accounts?fields=name,access_token`: o
   `access_token` da sua Página é o `META_ACCESS_TOKEN` (no depurador: "Expira: Nunca").
7. Coloque `META_ACCESS_TOKEN` e `IG_USER_ID` no `.env` e nos Secrets do GitHub.

#### Renovação a cada 90 dias

Mesmo com o token sem validade, a Meta limita o **acesso a dados** a 90 dias
desde o último login no app. O coletor verifica isso a cada execução e mostra um
aviso (também no resumo do GitHub Actions) quando faltarem 10 dias ou menos.
Para renovar, repita os passos 3 e 6 e atualize o `.env` e o Secret
`META_ACCESS_TOKEN`.

O coletor respeita os limites de uso da API: desacelera quando os cabeçalhos
`X-App-Usage` / `X-Business-Use-Case-Usage` passam de 75% e tenta de novo nos
erros de limite.

### Reclame Aqui: se o site mudar

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
| `META_ACCESS_TOKEN` | token de Página da Meta (seção Instagram) |
| `IG_USER_ID` | ID da sua conta profissional do Instagram |

O workflow aplica as migrações e o `sync-config` em produção antes de coletar.
Portanto, o que estiver na `main` é o que vale para o banco de produção.

## 7. Painéis

### Dashboard local

```powershell
uv run monitor painel            # gera dados/painel.html e abre no navegador
uv run monitor painel --no-abrir
```

A página é um arquivo HTML autocontido (funciona sem internet), com abas de
visão geral (última coleta de cada fonte e comparativo por instituição), lojas,
Consumidor.gov.br, Reclame Aqui, Instagram (seguidores, posts e curtidas por mês)
e evolução no tempo. O filtro "Destacar instituição" vale para todas as abas, e
cada gráfico tem o botão "Ver tabela". Para atualizar, rode o comando de novo.

O painel lê o banco de `PAINEL_DATABASE_URL`; sem ela, usa a `DATABASE_URL` do
`.env` (dev). O topo da página diz de onde vieram os dados. Para ler a produção
com segurança, crie um usuário somente leitura no branch `production` do Neon
(**SQL Editor**, com o branch production selecionado), trocando a senha:

```sql
CREATE ROLE painel_leitura WITH LOGIN PASSWORD 'troque-esta-senha';
GRANT CONNECT ON DATABASE neondb TO painel_leitura;
GRANT USAGE ON SCHEMA public TO painel_leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO painel_leitura;
-- Tabelas e views criadas depois (novas migrações) também ficam legíveis:
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO painel_leitura;
```

Depois, em **Connect**, escolha o branch production e o usuário
`painel_leitura`, copie a conexão direta (sem `-pooler`) e coloque no `.env` como
`PAINEL_DATABASE_URL=...`. A mesma conexão serve para Looker Studio, Metabase ou
Power BI.

### Ferramentas de BI

Conecte a ferramenta de BI ao Neon (de preferência com o usuário somente
leitura acima) e use as views:

| View                        | Conteúdo                                                        |
|-----------------------------|-----------------------------------------------------------------|
| `vw_metricas_atuais`        | último valor de cada métrica por perfil ativo                   |
| `vw_metricas_mensais`       | último snapshot de cada mês por perfil e métrica                |
| `vw_instagram_posts`        | posts do Instagram com data e a contagem mais recente de curtidas |

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
