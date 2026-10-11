from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from monitor.coletores.base import PerfilAlvo, RegistroMetrica, RespostaBrutaColetada
from monitor.config_loader import ConfigInvalida, InstituicaoConfig
from monitor.db.models import (
    Execucao,
    Instituicao,
    Perfil,
    Plataforma,
    RespostaBruta,
    SnapshotMetrica,
)

# ---------------------------------------------------------------- configuração


@dataclass
class ResumoSync:
    instituicoes: int = 0
    perfis: int = 0
    instituicoes_inativadas: int = 0
    perfis_inativados: int = 0


def sincronizar_config(sessao: Session, config: list[InstituicaoConfig]) -> ResumoSync:
    """Upsert de instituições e perfis; o que saiu do YAML fica inativo, nunca é apagado."""
    plataformas = set(sessao.scalars(select(Plataforma.codigo)))
    desconhecidas = {p for inst in config for p in inst.perfis} - plataformas
    if desconhecidas:
        raise ConfigInvalida(
            f"Plataformas desconhecidas: {sorted(desconhecidas)}. Válidas: {sorted(plataformas)}"
        )

    resumo = ResumoSync()
    ids_instituicoes: list[int] = []
    ids_perfis: list[int] = []

    for inst in config:
        campos = {"nome": inst.nome, "cnpj": inst.cnpj, "segmento": inst.segmento, "ativo": True}
        instituicao_id = sessao.scalar(
            insert(Instituicao)
            .values(nome_curto=inst.nome_curto, **campos)
            .on_conflict_do_update(index_elements=[Instituicao.nome_curto], set_=campos)
            .returning(Instituicao.id)
        )
        ids_instituicoes.append(instituicao_id)

        for plataforma, perfis in inst.perfis.items():
            for perfil in perfis:
                campos_perfil = {
                    "instituicao_id": instituicao_id,
                    "rotulo": perfil.rotulo,
                    "metadados": perfil.metadados,
                    "ativo": True,
                }
                ids_perfis.append(
                    sessao.scalar(
                        insert(Perfil)
                        .values(
                            plataforma_codigo=plataforma,
                            identificador=perfil.identificador,
                            **campos_perfil,
                        )
                        .on_conflict_do_update(
                            constraint="uq_perfis_plataforma_identificador", set_=campos_perfil
                        )
                        .returning(Perfil.id)
                    )
                )

    resumo.instituicoes = len(ids_instituicoes)
    resumo.perfis = len(ids_perfis)
    resumo.perfis_inativados = sessao.execute(
        update(Perfil).where(Perfil.ativo, Perfil.id.not_in(ids_perfis)).values(ativo=False)
    ).rowcount
    resumo.instituicoes_inativadas = sessao.execute(
        update(Instituicao)
        .where(Instituicao.ativo, Instituicao.id.not_in(ids_instituicoes))
        .values(ativo=False)
    ).rowcount
    return resumo


def perfis_ativos(sessao: Session, plataforma: str) -> list[PerfilAlvo]:
    linhas = sessao.scalars(
        select(Perfil)
        .join(Instituicao, Instituicao.id == Perfil.instituicao_id)
        .where(Perfil.plataforma_codigo == plataforma, Perfil.ativo, Instituicao.ativo)
        .order_by(Perfil.id)
    )
    return [
        PerfilAlvo(
            id=p.id,
            instituicao_id=p.instituicao_id,
            plataforma_codigo=p.plataforma_codigo,
            identificador=p.identificador,
            rotulo=p.rotulo,
            metadados=p.metadados,
        )
        for p in linhas
    ]


# ------------------------------------------------------------------- execuções


def abrir_execucao(sessao: Session, coletor: str) -> int:
    execucao = Execucao(coletor=coletor, status="em_andamento")
    sessao.add(execucao)
    sessao.flush()
    return execucao.id


def finalizar_execucao(
    sessao: Session,
    execucao_id: int,
    status: str,
    perfis_ok: int,
    perfis_erro: int,
    detalhes: dict[str, Any],
) -> None:
    sessao.execute(
        update(Execucao)
        .where(Execucao.id == execucao_id)
        .values(
            status=status,
            perfis_ok=perfis_ok,
            perfis_erro=perfis_erro,
            detalhes=detalhes,
            finalizado_em=datetime.now(UTC),
        )
    )


def ultimas_execucoes(sessao: Session, limite: int = 10) -> list[Execucao]:
    return list(
        sessao.scalars(select(Execucao).order_by(Execucao.iniciado_em.desc()).limit(limite))
    )


# ------------------------------------------------------------------- gravações


def upsert_snapshots(
    sessao: Session,
    execucao_id: int,
    perfil_id: int,
    registros: list[RegistroMetrica],
    data_referencia: date,
) -> None:
    """Reexecutar no mesmo dia atualiza o snapshot existente em vez de duplicar."""
    if not registros:
        return
    # Dois registros com a mesma chave no mesmo lote fariam o ON CONFLICT falhar; vale o último.
    por_chave = {}
    for r in registros:
        linha = {
            "execucao_id": execucao_id,
            "perfil_id": perfil_id,
            "metrica_codigo": r.metrica_codigo,
            "data_referencia": r.data_referencia or data_referencia,
            "periodo_inicio": r.periodo_inicio,
            "periodo_fim": r.periodo_fim,
            "valor": r.valor,
            "valor_texto": r.valor_texto,
            "coletado_em": datetime.now(UTC),
        }
        chave = (
            linha["metrica_codigo"],
            linha["data_referencia"],
            linha["periodo_inicio"],
            linha["periodo_fim"],
        )
        por_chave[chave] = linha

    comando = insert(SnapshotMetrica).values(list(por_chave.values()))
    sessao.execute(
        comando.on_conflict_do_update(
            constraint="uq_snapshots_metricas_chave",
            set_={
                coluna: comando.excluded[coluna]
                for coluna in ("execucao_id", "valor", "valor_texto", "coletado_em")
            },
        )
    )


def gravar_respostas_brutas(
    sessao: Session, execucao_id: int, perfil_id: int, respostas: list[RespostaBrutaColetada]
) -> None:
    sessao.add_all(
        RespostaBruta(
            execucao_id=execucao_id, perfil_id=perfil_id, origem=r.origem, payload=r.payload
        )
        for r in respostas
    )


def limpar_respostas_brutas(sessao: Session, dias: int) -> int:
    limite = datetime.now(UTC) - timedelta(days=dias)
    return sessao.execute(delete(RespostaBruta).where(RespostaBruta.coletado_em < limite)).rowcount
