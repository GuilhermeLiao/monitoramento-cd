"""Interface que todo coletor segue. A orquestração fica em executor.py."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PerfilAlvo:
    id: int
    instituicao_id: int
    plataforma_codigo: str
    identificador: str
    rotulo: str | None = None
    metadados: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegistroMetrica:
    """Um valor de métrica. `valor=None` significa "não foi possível obter":
    nunca use zero no lugar de desconhecido."""

    metrica_codigo: str
    valor: Decimal | int | float | None = None
    valor_texto: str | None = None
    # Preencha os dois quando a métrica cobre uma janela; deixe nulos para valor do momento.
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    # Padrão: dia da execução no fuso America/Sao_Paulo.
    data_referencia: date | None = None


@dataclass(frozen=True)
class RespostaBrutaColetada:
    origem: str
    payload: dict[str, Any]


@dataclass
class ResultadoColeta:
    metricas: list[RegistroMetrica] = field(default_factory=list)
    respostas_brutas: list[RespostaBrutaColetada] = field(default_factory=list)
    # Registros específicos da fonte (reclamações, posts); gravados por gravar_registros.
    registros: list[Any] = field(default_factory=list)


class Coletor(ABC):
    nome: ClassVar[str]
    plataforma: ClassVar[str]

    @abstractmethod
    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        """Busca os dados de um perfil. Não acessa o banco. Qualquer exceção é
        registrada como erro só deste perfil; os demais continuam."""

    def gravar_registros(
        self, sessao: Session, execucao_id: int, perfil: PerfilAlvo, registros: list[Any]
    ) -> None:
        """Grava `ResultadoColeta.registros` nas tabelas da fonte. Roda na mesma
        transação das métricas do perfil. Sobrescreva se o coletor devolver registros."""
        if registros:
            raise NotImplementedError(
                f"O coletor {self.nome} devolveu registros mas não implementa gravar_registros"
            )
