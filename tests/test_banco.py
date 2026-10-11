"""Testes que precisam do Postgres (branch dev do Neon). Ver conftest.py."""

from datetime import date
from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text

from monitor.coletores.base import (
    Coletor,
    PerfilAlvo,
    RegistroMetrica,
    RespostaBrutaColetada,
    ResultadoColeta,
)
from monitor.coletores.executor import executar_coletor
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo
from monitor.db.models import Base, Execucao, Instituicao, Perfil, RespostaBruta, SnapshotMetrica

CONFIG = [
    {
        "nome": "Banco Exemplo",
        "nome_curto": "exemplo",
        "cnpj": "00.000.000/0001-00",
        "perfis": {
            "app_store": [
                {"identificador": "111", "rotulo": "App PF"},
                {"identificador": "222", "rotulo": "App PJ"},
            ],
            "instagram": [{"identificador": "bancoexemplo"}],
        },
    },
    {
        "nome": "Outro Banco",
        "nome_curto": "outro",
        "perfis": {"app_store": [{"identificador": "333"}]},
    },
]


def _sincronizar(fabrica, config=CONFIG):
    with fabrica.begin() as sessao:
        return repo.sincronizar_config(sessao, validar_config(config))


def _contar(fabrica, modelo, *filtros):
    with fabrica() as sessao:
        return sessao.scalar(select(func.count()).select_from(modelo).where(*filtros))


class ColetorFalso(Coletor):
    nome = "falso"
    plataforma = "app_store"

    def __init__(self, falhar_em=(), nota="4.5"):
        self.falhar_em = set(falhar_em)
        self.nota = nota

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        if perfil.identificador in self.falhar_em:
            raise RuntimeError(f"falha simulada em {perfil.identificador}")
        return ResultadoColeta(
            metricas=[
                RegistroMetrica("nota_media", Decimal(self.nota)),
                # Valor desconhecido fica nulo, nunca zero.
                RegistroMetrica("total_avaliacoes", None),
            ],
            respostas_brutas=[RespostaBrutaColetada("https://exemplo.test", {"ok": True})],
        )


# ------------------------------------------------------------------- migrações


def test_modelos_batem_com_as_migracoes(engine):
    with engine.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_views_existem(engine):
    with engine.connect() as conexao:
        for view in ("vw_metricas_atuais", "vw_metricas_mensais", "vw_consumidor_gov_periodo"):
            conexao.execute(text(f"SELECT * FROM {view} LIMIT 0"))


def test_downgrade_e_upgrade(engine, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    with engine.connect() as conexao:
        restantes = conexao.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name <> 'alembic_version'"
            )
        )
    assert restantes == 0
    command.upgrade(alembic_cfg, "head")


# ----------------------------------------------------------------- sync-config


def test_sync_config_idempotente(fabrica):
    primeiro = _sincronizar(fabrica)
    segundo = _sincronizar(fabrica)
    assert (primeiro.instituicoes, primeiro.perfis) == (2, 4)
    assert (segundo.instituicoes_inativadas, segundo.perfis_inativados) == (0, 0)
    assert _contar(fabrica, Instituicao) == 2
    assert _contar(fabrica, Perfil) == 4


def test_sync_config_inativa_o_que_saiu_do_yaml(fabrica):
    _sincronizar(fabrica)
    resumo = _sincronizar(fabrica, CONFIG[:1])
    assert (resumo.instituicoes_inativadas, resumo.perfis_inativados) == (1, 1)
    assert _contar(fabrica, Perfil) == 4
    assert _contar(fabrica, Perfil, Perfil.ativo) == 3
    assert _contar(fabrica, Instituicao, Instituicao.ativo) == 1

    # Voltar ao YAML reativa.
    _sincronizar(fabrica)
    assert _contar(fabrica, Perfil, Perfil.ativo) == 4


# -------------------------------------------------------------------- executor


def test_duas_execucoes_no_mesmo_dia_nao_duplicam_snapshots(fabrica):
    _sincronizar(fabrica)
    executar_coletor(ColetorFalso(nota="4.5"), fabrica)
    segunda = executar_coletor(ColetorFalso(nota="4.7"), fabrica)

    # 3 perfis de app_store x 2 métricas, mesmo após duas execuções.
    assert _contar(fabrica, SnapshotMetrica) == 6
    with fabrica() as sessao:
        notas = sessao.execute(
            select(SnapshotMetrica.valor, SnapshotMetrica.execucao_id).where(
                SnapshotMetrica.metrica_codigo == "nota_media"
            )
        ).all()
        desconhecidos = sessao.scalars(
            select(SnapshotMetrica.valor).where(
                SnapshotMetrica.metrica_codigo == "total_avaliacoes"
            )
        ).all()
    assert {(n.valor, n.execucao_id) for n in notas} == {(Decimal("4.7"), segunda.execucao_id)}
    assert desconhecidos == [None, None, None]


def test_snapshot_com_periodo_diferente_e_outra_linha(fabrica):
    _sincronizar(fabrica)
    with fabrica.begin() as sessao:
        execucao_id = repo.abrir_execucao(sessao, "teste")
        perfil = repo.perfis_ativos(sessao, "instagram")[0]
        hoje = date(2026, 10, 12)
        for _ in range(2):
            repo.upsert_snapshots(
                sessao,
                execucao_id,
                perfil.id,
                [
                    RegistroMetrica("seguidores", 1000),
                    RegistroMetrica(
                        "posts_periodo",
                        8,
                        periodo_inicio=date(2026, 9, 1),
                        periodo_fim=date(2026, 9, 30),
                    ),
                    RegistroMetrica(
                        "posts_periodo",
                        3,
                        periodo_inicio=date(2026, 10, 1),
                        periodo_fim=date(2026, 10, 12),
                    ),
                ],
                hoje,
            )
    assert _contar(fabrica, SnapshotMetrica) == 3


def test_erro_em_um_perfil_nao_derruba_os_outros(fabrica):
    _sincronizar(fabrica)
    resultado = executar_coletor(ColetorFalso(falhar_em={"222"}), fabrica)

    assert (resultado.status, resultado.perfis_ok, resultado.perfis_erro) == ("parcial", 2, 1)
    assert not resultado.falhou_tudo
    assert _contar(fabrica, SnapshotMetrica) == 4
    assert _contar(fabrica, RespostaBruta) == 2
    with fabrica() as sessao:
        execucao = sessao.get(Execucao, resultado.execucao_id)
    assert execucao.status == "parcial"
    assert execucao.finalizado_em is not None
    (erro,) = execucao.detalhes["erros"]
    assert erro["identificador"] == "222"
    assert erro["tipo"] == "RuntimeError"


def test_todos_os_perfis_com_erro(fabrica):
    _sincronizar(fabrica)
    resultado = executar_coletor(ColetorFalso(falhar_em={"111", "222", "333"}), fabrica)
    assert resultado.status == "erro"
    assert resultado.falhou_tudo
    assert _contar(fabrica, SnapshotMetrica) == 0


def test_limpar_respostas_brutas(fabrica):
    _sincronizar(fabrica)
    executar_coletor(ColetorFalso(), fabrica)
    with fabrica.begin() as sessao:
        sessao.execute(
            text(
                "UPDATE respostas_brutas SET coletado_em = now() - interval '200 days' "
                "WHERE perfil_id = (SELECT min(perfil_id) FROM respostas_brutas)"
            )
        )
    with fabrica.begin() as sessao:
        assert repo.limpar_respostas_brutas(sessao, 180) == 1
    assert _contar(fabrica, RespostaBruta) == 2
