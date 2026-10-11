"""Executor comum: abre a execução, roda o coletor perfil a perfil e registra o resultado."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from monitor.coletores.base import Coletor
from monitor.db import repositorios as repo
from monitor.settings import FUSO_REFERENCIA

log = logging.getLogger(__name__)


@dataclass
class ResultadoExecucao:
    execucao_id: int
    coletor: str
    status: str
    perfis_ok: int = 0
    perfis_erro: int = 0
    erros: list[dict[str, Any]] = field(default_factory=list)

    @property
    def falhou_tudo(self) -> bool:
        return self.status == "erro"


def executar_coletor(coletor: Coletor, fabrica: sessionmaker[Session]) -> ResultadoExecucao:
    data_referencia = datetime.now(FUSO_REFERENCIA).date()

    with fabrica.begin() as sessao:
        execucao_id = repo.abrir_execucao(sessao, coletor.nome)
        perfis = repo.perfis_ativos(sessao, coletor.plataforma)

    contexto = {"coletor": coletor.nome, "execucao_id": execucao_id}
    log.info("execucao iniciada", extra={**contexto, "perfis": len(perfis)})
    if not perfis:
        log.warning("nenhum perfil ativo para a plataforma", extra=contexto)

    ok = 0
    erros: list[dict[str, Any]] = []
    for perfil in perfis:
        try:
            resultado = coletor.coletar(perfil)
            # Uma transação por perfil: a falha de um não desfaz o que os outros gravaram.
            with fabrica.begin() as sessao:
                repo.upsert_snapshots(
                    sessao, execucao_id, perfil.id, resultado.metricas, data_referencia
                )
                repo.gravar_respostas_brutas(
                    sessao, execucao_id, perfil.id, resultado.respostas_brutas
                )
                coletor.gravar_registros(sessao, execucao_id, perfil, resultado.registros)
            ok += 1
            log.info(
                "perfil coletado",
                extra={**contexto, "perfil_id": perfil.id, "metricas": len(resultado.metricas)},
            )
        except Exception as erro:  # noqa: BLE001 - isolamento por perfil é o objetivo
            erros.append(
                {
                    "perfil_id": perfil.id,
                    "identificador": perfil.identificador,
                    "tipo": type(erro).__name__,
                    "mensagem": str(erro)[:500],
                }
            )
            log.exception("falha no perfil", extra={**contexto, "perfil_id": perfil.id})

    if not erros:
        status = "sucesso"
    elif ok == 0:
        status = "erro"
    else:
        status = "parcial"

    with fabrica.begin() as sessao:
        repo.finalizar_execucao(sessao, execucao_id, status, ok, len(erros), {"erros": erros})

    log.info(
        "execucao finalizada",
        extra={**contexto, "status": status, "perfis_ok": ok, "perfis_erro": len(erros)},
    )
    return ResultadoExecucao(execucao_id, coletor.nome, status, ok, len(erros), erros)
