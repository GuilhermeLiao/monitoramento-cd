"""Leitura e validação do config/instituicoes.yaml."""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

_CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")


class ConfigInvalida(ValueError):
    pass


class PerfilConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    identificador: str = Field(min_length=1)
    rotulo: str | None = None
    metadados: dict[str, Any] = Field(default_factory=dict)

    @field_validator("identificador", mode="before")
    @classmethod
    def _id_como_texto(cls, valor: Any) -> Any:
        # IDs numéricos da App Store costumam vir sem aspas no YAML.
        return str(valor) if isinstance(valor, int) and not isinstance(valor, bool) else valor


class InstituicaoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(min_length=1)
    nome_curto: str = Field(pattern=r"^[a-z0-9_]+$")
    cnpj: str | None = None
    segmento: str | None = None
    perfis: dict[str, list[PerfilConfig]] = Field(default_factory=dict)

    @field_validator("cnpj")
    @classmethod
    def _normalizar_cnpj(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        bruto = re.sub(r"[./\-\s]", "", valor).upper()
        if not _CNPJ.fullmatch(bruto):
            raise ValueError("CNPJ deve ter 14 caracteres (ex.: 00.000.000/0001-00)")
        return f"{bruto[:2]}.{bruto[2:5]}.{bruto[5:8]}/{bruto[8:12]}-{bruto[12:]}"


def _duplicados(valores: list[Any]) -> list[Any]:
    vistos: set[Any] = set()
    repetidos = []
    for valor in valores:
        if valor in vistos and valor not in repetidos:
            repetidos.append(valor)
        vistos.add(valor)
    return repetidos


def validar_config(dados: Any) -> list[InstituicaoConfig]:
    # Arquivo só com comentários vira None: é uma configuração vazia válida.
    instituicoes = TypeAdapter(list[InstituicaoConfig]).validate_python(dados or [])

    erros = []
    if rep := _duplicados([i.nome_curto for i in instituicoes]):
        erros.append(f"nome_curto repetido: {rep}")
    if rep := _duplicados([i.cnpj for i in instituicoes if i.cnpj]):
        erros.append(f"cnpj repetido: {rep}")
    chaves_perfis = [
        (plataforma, perfil.identificador)
        for inst in instituicoes
        for plataforma, perfis in inst.perfis.items()
        for perfil in perfis
    ]
    if rep := _duplicados(chaves_perfis):
        erros.append(f"perfil repetido (plataforma, identificador): {rep}")
    if erros:
        raise ConfigInvalida("; ".join(erros))
    return instituicoes


def carregar_config(caminho: Path) -> list[InstituicaoConfig]:
    with caminho.open(encoding="utf-8") as arquivo:
        return validar_config(yaml.safe_load(arquivo))
