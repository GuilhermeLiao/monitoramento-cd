# Monitor de reputação digital

Coleta semanal de indicadores públicos de reputação de instituições financeiras
brasileiras (lojas de apps, Reclame Aqui, Consumidor.gov.br, Instagram) em um
PostgreSQL no Neon, com views prontas para Looker Studio, Metabase ou Power BI.

Nenhum dado pessoal de consumidor é armazenado: só métricas e atributos categóricos.

> Estado atual: coletores das lojas de apps (`app_store` e `google_play`) prontos,
> gravando a nota média de cada app. Os demais ainda não foram implementados.

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

## 4. Comandos

```powershell
uv run monitor coletar <coletor>       # roda um coletor (app_store, google_play)
uv run monitor coletar lojas           # roda app_store e google_play
uv run monitor coletar todos           # roda todos
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

Migrações:

```powershell
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic revision -m "descricao"   # nova migração (escrita à mão)
```

## 5. Testes

```powershell
uv run pytest
uv run pytest -m live    # opcional: consulta um app real em cada loja, pela rede
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
| `vw_consumidor_gov_periodo` | base diária somável do consumidor.gov para qualquer intervalo   |

Em `vw_consumidor_gov_periodo`, filtre o intervalo em `data_finalizacao`, some as
colunas e só então divida (por exemplo, nota média = `SUM(soma_notas) / SUM(qtd_notas)`).

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
