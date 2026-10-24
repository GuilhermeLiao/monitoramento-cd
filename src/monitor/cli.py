import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from monitor.coletores import COLETORES, GRUPOS
from monitor.coletores.executor import executar_coletor
from monitor.coletores.reclame_aqui import ArquivoInvalido, ReclameAquiImportador
from monitor.config_loader import ConfigInvalida, carregar_config
from monitor.db import repositorios as repo
from monitor.db.session import criar_fabrica_sessoes
from monitor.logging_config import configurar_logging
from monitor.settings import FUSO_REFERENCIA, get_settings

app = typer.Typer(no_args_is_help=True, help="Monitor de reputação digital.")
log = logging.getLogger("monitor.cli")


@app.callback()
def _principal() -> None:
    try:
        configurar_logging(get_settings().log_level)
    except ValidationError as erro:
        typer.echo("Configuração ausente: defina DATABASE_URL no .env ou no ambiente.", err=True)
        raise typer.Exit(2) from erro


@app.command()
def coletar(
    coletor: Annotated[str, typer.Argument(help="Nome do coletor, 'lojas' ou 'todos'.")],
) -> None:
    """Executa um coletor (ou todos). Sai com código 1 se algum falhar em todos os perfis."""
    if coletor == "todos":
        nomes = sorted(COLETORES)
        if not nomes:
            typer.echo("Nenhum coletor implementado ainda.")
            return
    elif coletor in GRUPOS:
        nomes = list(GRUPOS[coletor])
    elif coletor in COLETORES:
        nomes = [coletor]
    else:
        typer.echo(
            f"Coletor desconhecido: {coletor}. "
            f"Disponíveis: {sorted([*COLETORES, *GRUPOS]) or 'nenhum'}",
            err=True,
        )
        raise typer.Exit(2)

    fabrica = criar_fabrica_sessoes()
    falhou = False
    for nome in nomes:
        try:
            resultado = executar_coletor(COLETORES[nome](), fabrica)
        except Exception:  # noqa: BLE001 - um coletor quebrado não impede os demais
            log.exception("falha ao executar coletor", extra={"coletor": nome})
            typer.echo(f"{nome}: erro antes de processar os perfis (veja o log)")
            falhou = True
            continue
        typer.echo(
            f"{nome}: {resultado.status} "
            f"({resultado.perfis_ok} ok, {resultado.perfis_erro} com erro)"
        )
        for erro in resultado.erros:
            typer.echo(f"      {erro['identificador']}: {erro['tipo']}: {erro['mensagem']}")
        falhou = falhou or resultado.falhou_tudo
    if falhou:
        raise typer.Exit(1)


@app.command("importar-reclame-aqui")
def importar_reclame_aqui(
    arquivo: Annotated[
        Path, typer.Argument(help="Arquivo .json baixado pelo botão do Reclame Aqui.")
    ],
) -> None:
    """Grava os indicadores do Reclame Aqui capturados pelo botão do navegador."""
    try:
        importador = ReclameAquiImportador(arquivo)
    except ArquivoInvalido as erro:
        typer.echo(str(erro), err=True)
        raise typer.Exit(2) from erro
    typer.echo(f"{len(importador.slugs)} empresas no arquivo.")
    resultado = executar_coletor(importador, criar_fabrica_sessoes())
    typer.echo(
        f"reclame_aqui: {resultado.status} "
        f"({resultado.perfis_ok} ok, {resultado.perfis_erro} com erro)"
    )
    for erro in resultado.erros:
        typer.echo(f"      {erro['identificador']}: {erro['tipo']}: {erro['mensagem']}")
    if resultado.falhou_tudo:
        raise typer.Exit(1)


@app.command("botao-reclame-aqui")
def botao_reclame_aqui(
    saida: Annotated[
        Path, typer.Option(help="Onde gravar a página de instalação do botão.")
    ] = Path("dados/botao_reclame_aqui.html"),
) -> None:
    """Gera a página que instala o botão de captura do Reclame Aqui no navegador."""
    config = carregar_config(get_settings().config_path)
    slugs = sorted(
        {
            perfil.identificador.lower()
            for inst in config
            for perfil in inst.perfis.get("reclame_aqui", [])
        }
    )
    modelo = (Path(__file__).parent / "ferramentas" / "botao_reclame_aqui.html").read_text(
        encoding="utf-8"
    )
    pagina = (
        modelo.replace("__SLUGS__", json.dumps(slugs))
        .replace("__TOTAL__", str(len(slugs)))
        .replace("__GERADO_EM__", datetime.now(FUSO_REFERENCIA).strftime("%d/%m/%Y"))
    )
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(pagina, encoding="utf-8")
    typer.echo(f"Página gerada em {saida.resolve()} ({len(slugs)} empresas). Abra no navegador.")


@app.command("sync-config")
def sync_config(
    arquivo: Annotated[
        Path | None, typer.Option(help="YAML de instituições (padrão: CONFIG_PATH).")
    ] = None,
) -> None:
    """Valida o YAML e sincroniza instituições e perfis com o banco."""
    caminho = arquivo or get_settings().config_path
    try:
        config = carregar_config(caminho)
        with criar_fabrica_sessoes().begin() as sessao:
            resumo = repo.sincronizar_config(sessao, config)
    except (ValidationError, ConfigInvalida, FileNotFoundError) as erro:
        typer.echo(f"Configuração inválida em {caminho}:\n{erro}", err=True)
        raise typer.Exit(2) from erro
    typer.echo(
        f"{resumo.instituicoes} instituições e {resumo.perfis} perfis sincronizados; "
        f"{resumo.instituicoes_inativadas} instituições e {resumo.perfis_inativados} perfis "
        "inativados."
    )


@app.command("limpar-brutos")
def limpar_brutos(
    dias: Annotated[int, typer.Option(min=1, help="Remove respostas mais antigas que N dias.")] = 180,
) -> None:
    """Apaga respostas brutas antigas para caber no limite de 0,5 GB do Neon."""
    with criar_fabrica_sessoes().begin() as sessao:
        removidas = repo.limpar_respostas_brutas(sessao, dias)
    typer.echo(f"{removidas} respostas brutas com mais de {dias} dias removidas.")


@app.command()
def status(
    limite: Annotated[int, typer.Option(min=1, help="Quantas execuções mostrar.")] = 10,
) -> None:
    """Mostra as últimas execuções e as falhas por perfil."""
    with criar_fabrica_sessoes()() as sessao:
        execucoes = repo.ultimas_execucoes(sessao, limite)
    if not execucoes:
        typer.echo("Nenhuma execução registrada.")
        return
    for e in execucoes:
        inicio = e.iniciado_em.astimezone(FUSO_REFERENCIA).strftime("%d/%m/%Y %H:%M")
        typer.echo(
            f"#{e.id}  {inicio}  {e.coletor:<16} {e.status:<13} "
            f"ok={e.perfis_ok} erro={e.perfis_erro}"
        )
        for erro in e.detalhes.get("erros", []):
            typer.echo(f"      {erro['identificador']}: {erro['tipo']}: {erro['mensagem']}")


if __name__ == "__main__":
    app()
