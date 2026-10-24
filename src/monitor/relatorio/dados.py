"""Monta as tabelas do relatório de um mês, com a comparação ao mês anterior.

Usa o mesmo dicionário que o painel (`monitor.painel.carregar_dados`). O valor de
cada indicador num mês é o do último levantamento até o fim daquele mês.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

PLATAFORMAS = {
    "app_store": "App Store",
    "google_play": "Google Play",
    "consumidor_gov": "Consumidor.gov.br",
    "reclame_aqui": "Reclame Aqui",
    "instagram": "Instagram",
}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


@dataclass(frozen=True)
class Coluna:
    titulo: str
    formato: str  # nota | pct | contagem | dias | texto | decimal
    sentido: str = "maior"  # maior | menor | volume (sem melhor/pior)
    grupo: str | None = None
    escala: int | None = None  # 5 ou 10, para notas


@dataclass
class Linha:
    rotulo: str
    instituicao: str
    valores: list[Any]
    anteriores: list[Any]


@dataclass
class Tabela:
    id: str
    titulo: str
    colunas: list[Coluna]
    linhas: list[Linha]
    janela: str | None = None
    janela_anterior: str | None = None
    nota: str | None = None
    rotulo_linha: str = "Instituição"


@dataclass
class Relatorio:
    mes: str  # AAAA-MM
    titulo_mes: str
    data_ref: date | None
    data_anterior: date | None
    gerado_em: str
    origem: str
    resumo: Tabela
    tabelas: list[Tabela]
    kpis: list[tuple[str, str, str]]
    top_posts: list[dict[str, Any]]
    lojas_grafico: list[tuple[str, float | None, float | None]]
    historico_mensal: list[list[Any]] = field(default_factory=list)
    todos_levantamentos: list[list[Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Registro:
    ref: date
    valor: float | None
    texto: str | None
    ini: date | None
    fim: date | None


def _d(iso: str | None) -> date | None:
    return date.fromisoformat(iso[:10]) if iso else None


def fim_do_mes(mes: str) -> date:
    ano, m = (int(x) for x in mes.split("-"))
    return date(ano, m, calendar.monthrange(ano, m)[1])


def mes_anterior(mes: str) -> str:
    ano, m = (int(x) for x in mes.split("-"))
    return f"{ano - 1}-12" if m == 1 else f"{ano}-{m - 1:02d}"


def nome_mes(mes: str) -> str:
    ano, m = (int(x) for x in mes.split("-"))
    return f"{MESES[m - 1]} de {ano}"


def fmt_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _br(numero: float, casas: int) -> str:
    return f"{numero:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def formatar(valor: Any, formato: str) -> str:
    if valor is None:
        return "—"
    if formato == "texto":
        return str(valor)
    if formato == "contagem":
        return _br(valor, 0)
    if formato == "pct":
        return _br(valor, 1) + "%"
    if formato == "dias":
        return _br(valor, 1) + " dias"
    if formato == "nota":
        return _br(valor, 2)
    return _br(valor, 2)


def variacao(atual: Any, anterior: Any, coluna: Coluna) -> tuple[str, str] | None:
    """Texto da variação e a classe: melhor | pior | neutro."""
    if coluna.formato == "texto" or atual is None or anterior is None:
        return None
    dif = atual - anterior
    casas = 0 if coluna.formato == "contagem" else 1 if coluna.formato in ("pct", "dias") else 2
    if round(abs(dif), casas) == 0:
        return "=", "neutro"
    seta = "▲" if dif > 0 else "▼"
    unidade = {"pct": " p.p.", "dias": " d"}.get(coluna.formato, "")
    texto = f"{seta} {_br(abs(dif), casas)}{unidade}"
    if coluna.sentido == "volume":
        return texto, "neutro"
    melhor = dif > 0 if coluna.sentido == "maior" else dif < 0
    return texto, "melhor" if melhor else "pior"


class Base:
    def __init__(self, dados: dict[str, Any]) -> None:
        self.dados = dados
        self.inst = {i[0]: {"id": i[0], "nome": i[1], "curto": i[2]} for i in dados["instituicoes"]}
        self.perfis = {
            p[0]: {"id": p[0], "inst": p[1], "plat": p[2], "ident": p[3], "rotulo": p[4]}
            for p in dados["perfis"]
            if p[1] in self.inst
        }
        series: dict[tuple[int, str], list[Registro]] = defaultdict(list)
        for perfil, metrica, ref, valor, texto, ini, fim in dados["historico"]:
            lista = series[(perfil, metrica)]
            registro = Registro(_d(ref), valor, texto, _d(ini), _d(fim))
            if lista and lista[-1].ref == registro.ref:
                lista[-1] = registro
            else:
                lista.append(registro)
        self.series = series
        self.datas = sorted({r.ref for lista in series.values() for r in lista})

    def nome_inst(self, inst_id: int) -> str:
        return self.inst[inst_id]["nome"]

    def nome_perfil(self, perfil: dict[str, Any]) -> str:
        base = self.nome_inst(perfil["inst"])
        return f"{base} · {perfil['rotulo']}" if perfil["rotulo"] else base

    def perfis_de(self, plat: str) -> list[dict[str, Any]]:
        return sorted(
            (p for p in self.perfis.values() if p["plat"] == plat),
            key=lambda p: self.nome_perfil(p).casefold(),
        )

    def instituicoes(self) -> list[dict[str, Any]]:
        return sorted(self.inst.values(), key=lambda i: i["nome"].casefold())

    def vigente(self, perfil_id: int, metrica: str, ate: date | None) -> Registro | None:
        if ate is None:
            return None
        achado = None
        for registro in self.series.get((perfil_id, metrica), []):
            if registro.ref > ate:
                break
            achado = registro
        return achado

    def data_ate(self, limite: date) -> date | None:
        anteriores = [d for d in self.datas if d <= limite]
        return anteriores[-1] if anteriores else None

    def agregado(self, plat: str, metrica: str, inst_id: int, ate: date | None,
                 modo: str = "media", peso: str | None = None) -> float | None:
        pares = []
        for p in self.perfis.values():
            if p["plat"] != plat or p["inst"] != inst_id:
                continue
            r = self.vigente(p["id"], metrica, ate)
            w = self.vigente(p["id"], peso, ate) if peso else None
            if r and r.valor is not None and (not peso or (w and w.valor)):
                pares.append((r.valor, w.valor if peso and w else 1))
        if not pares:
            return None
        if modo == "soma":
            return sum(v for v, _ in pares)
        total = sum(w for _, w in pares)
        return sum(v * w for v, w in pares) / total if total else None

    def texto(self, plat: str, metrica: str, inst_id: int, ate: date | None) -> str | None:
        for p in self.perfis.values():
            if p["plat"] == plat and p["inst"] == inst_id:
                r = self.vigente(p["id"], metrica, ate)
                return r.texto if r else None
        return None

    def janela(self, plat: str, metrica: str, ate: date | None) -> str | None:
        for p in self.perfis_de(plat):
            r = self.vigente(p["id"], metrica, ate)
            if r:
                if r.ini:
                    return f"Janela {fmt_data(r.ini)} a {fmt_data(r.fim)} · coleta de {fmt_data(r.ref)}"
                return f"Coleta de {fmt_data(r.ref)}"
        return None

    def posts_na_janela(self, perfil_id: int, ini: date | None, fim: date | None) -> list[list[Any]]:
        if not ini or not fim:
            return []
        return [p for p in self.dados["posts"]
                if p[0] == perfil_id and ini <= date.fromisoformat(p[1]) <= fim]


# ------------------------------------------------------------------ tabelas

def _tabela_por_perfil(base: Base, tid: str, titulo: str, plat: str,
                       metricas: list[tuple[str, Coluna]], ref: date | None, ant: date | None,
                       nota: str) -> Tabela:
    linhas = []
    for p in base.perfis_de(plat):
        valores, anteriores = [], []
        for metrica, coluna in metricas:
            atual = base.vigente(p["id"], metrica, ref)
            anterior = base.vigente(p["id"], metrica, ant)
            campo = "texto" if coluna.formato == "texto" else "valor"
            valores.append(getattr(atual, campo) if atual else None)
            anteriores.append(getattr(anterior, campo) if anterior else None)
        linhas.append(Linha(base.nome_perfil(p), base.nome_inst(p["inst"]), valores, anteriores))
    primeira = metricas[0][0]
    return Tabela(tid, titulo, [c for _, c in metricas], linhas,
                  janela=base.janela(plat, primeira, ref),
                  janela_anterior=base.janela(plat, primeira, ant), nota=nota, rotulo_linha="Perfil")


def montar_relatorio(dados: dict[str, Any], mes: str | None = None, origem: str = "") -> Relatorio:
    base = Base(dados)
    if mes is None:
        mes = base.datas[-1].strftime("%Y-%m") if base.datas else date.today().strftime("%Y-%m")
    ref = base.data_ate(fim_do_mes(mes))
    ant = base.data_ate(fim_do_mes(mes_anterior(mes)))

    # Resumo por instituição
    def ag(plat: str, metrica: str, modo: str = "media", peso: str | None = None):
        return lambda inst, ate: base.agregado(plat, metrica, inst, ate, modo, peso)

    resumo_def = [
        (Coluna("Nota", "nota", grupo="App Store", escala=5), ag("app_store", "nota_media")),
        (Coluna("Nota", "nota", grupo="Google Play", escala=5), ag("google_play", "nota_media")),
        (Coluna("Reclamações", "contagem", "volume", grupo="Consumidor.gov"),
         ag("consumidor_gov", "total_reclamacoes", "soma")),
        (Coluna("Solução", "pct", grupo="Consumidor.gov"),
         ag("consumidor_gov", "pct_resolvidas", "media", "total_reclamacoes")),
        (Coluna("Satisfação (1–5)", "nota", grupo="Consumidor.gov", escala=5),
         ag("consumidor_gov", "nota_consumidor", "media", "total_reclamacoes")),
        (Coluna("Nota (0–10)", "nota", grupo="Reclame Aqui", escala=10), ag("reclame_aqui", "nota_reclame_aqui")),
        (Coluna("Reputação", "texto", grupo="Reclame Aqui"),
         lambda inst, ate: base.texto("reclame_aqui", "status_reputacao", inst, ate)),
        (Coluna("Seguidores", "contagem", grupo="Instagram"), ag("instagram", "seguidores", "soma")),
        (Coluna("Posts no mês", "contagem", "volume", grupo="Instagram"), ag("instagram", "posts_periodo", "soma")),
    ]
    resumo = Tabela(
        "resumo", "Resumo por instituição", [c for c, _ in resumo_def],
        [Linha(i["nome"], i["nome"], [f(i["id"], ref) for _, f in resumo_def],
               [f(i["id"], ant) for _, f in resumo_def]) for i in base.instituicoes()],
        nota="Instituições com mais de um app ou perfil: notas das lojas são média simples; solução e "
             "satisfação do Consumidor.gov são ponderadas pelo total de reclamações; contagens são somadas.",
    )

    # Lojas por instituição (para a tabela e o gráfico de halteres)
    lojas_linhas, grafico = [], []
    for i in base.instituicoes():
        a = base.agregado("app_store", "nota_media", i["id"], ref)
        g = base.agregado("google_play", "nota_media", i["id"], ref)
        a0 = base.agregado("app_store", "nota_media", i["id"], ant)
        g0 = base.agregado("google_play", "nota_media", i["id"], ant)
        lojas_linhas.append(Linha(i["nome"], i["nome"], [a, g], [a0, g0]))
        grafico.append((i["nome"], a, g))
    lojas = Tabela("lojas", "Lojas de apps", [Coluna("App Store", "nota", escala=5),
                                               Coluna("Google Play", "nota", escala=5)],
                   lojas_linhas, janela=base.janela("app_store", "nota_media", ref),
                   janela_anterior=base.janela("app_store", "nota_media", ant),
                   nota="Nota média exibida na loja do Brasil (média dos apps quando a instituição tem mais de um).")
    lojas_apps = Tabela(
        "lojas_apps", "Lojas de apps por app",
        [Coluna("App Store", "nota", escala=5), Coluna("Google Play", "nota", escala=5)],
        [], janela=lojas.janela, janela_anterior=lojas.janela_anterior, rotulo_linha="App")
    apps: dict[tuple[int, str], list[Any]] = {}
    for indice, plat in enumerate(("app_store", "google_play")):
        for p in base.perfis_de(plat):
            chave = (p["inst"], p["rotulo"] or "")
            linha = apps.setdefault(chave, [base.nome_perfil(p), base.nome_inst(p["inst"]), [None, None], [None, None]])
            atual, anterior = base.vigente(p["id"], "nota_media", ref), base.vigente(p["id"], "nota_media", ant)
            linha[2][indice] = atual.valor if atual else None
            linha[3][indice] = anterior.valor if anterior else None
    lojas_apps.linhas = [Linha(*v) for v in sorted(apps.values(), key=lambda v: v[0].casefold())]

    consumidor = _tabela_por_perfil(base, "consumidor_gov", "Consumidor.gov.br", "consumidor_gov", [
        ("total_reclamacoes", Coluna("Reclamações", "contagem", "volume")),
        ("pct_resolvidas", Coluna("Índice de solução", "pct")),
        ("nota_consumidor", Coluna("Satisfação (1–5)", "nota", escala=5)),
        ("pct_respondidas", Coluna("Respondidas", "pct")),
        ("tempo_resposta_dias", Coluna("Prazo médio", "dias", "menor")),
    ], ref, ant, "Indicadores do ano corrente exibidos no perfil de cada empresa no Consumidor.gov.br.")

    reclame = _tabela_por_perfil(base, "reclame_aqui", "Reclame Aqui", "reclame_aqui", [
        ("nota_reclame_aqui", Coluna("Nota (0–10)", "nota", escala=10)),
        ("status_reputacao", Coluna("Reputação", "texto")),
        ("total_reclamacoes", Coluna("Reclamações", "contagem", "volume")),
        ("pct_respondidas", Coluna("Respondidas", "pct")),
        ("pct_resolvidas", Coluna("Resolvidas", "pct")),
        ("pct_voltaria_negocio", Coluna("Voltariam", "pct")),
        ("nota_consumidor", Coluna("Nota consumidor", "nota", escala=10)),
        ("tempo_resposta_dias", Coluna("Tempo resposta", "dias", "menor")),
        ("aguardando_resposta", Coluna("Aguardando", "contagem", "menor")),
    ], ref, ant, "Painel dos últimos 6 meses do Reclame Aqui, capturado pelo botão do navegador.")

    # Instagram: seguidores e posts da janela "último mês inteiro" de cada levantamento.
    def numeros_ig(perfil_id: int, ate: date | None) -> list[Any]:
        seg = base.vigente(perfil_id, "seguidores", ate)
        janela = base.vigente(perfil_id, "posts_periodo", ate)
        posts = base.posts_na_janela(perfil_id, janela.ini if janela else None, janela.fim if janela else None)
        visiveis = [p[3] for p in posts if p[3] is not None]
        return [
            seg.valor if seg else None,
            janela.valor if janela else None,
            sum(visiveis) if visiveis else None,
            sum(visiveis) / len(visiveis) if visiveis else None,
            len(posts) - len(visiveis) if posts else None,
        ]

    instagram = Tabela(
        "instagram", "Instagram",
        [Coluna("Seguidores", "contagem"), Coluna("Posts no mês", "contagem", "volume"),
         Coluna("Curtidas no mês", "contagem"), Coluna("Curtidas por post", "contagem"),
         Coluna("Posts com curtidas ocultas", "contagem", "volume")],
        [Linha(base.nome_perfil(p) + f" (@{p['ident']})", base.nome_inst(p["inst"]),
               numeros_ig(p["id"], ref), numeros_ig(p["id"], ant)) for p in base.perfis_de("instagram")],
        janela=base.janela("instagram", "posts_periodo", ref),
        janela_anterior=base.janela("instagram", "posts_periodo", ant),
        nota="Seguidores na data da coleta. Posts e curtidas do último mês inteiro antes da coleta; "
             "curtidas ocultas não entram nas somas (nunca contam como zero).", rotulo_linha="Perfil")

    # Posts mais curtidos da janela do Instagram
    top = []
    for p in base.perfis_de("instagram"):
        janela = base.vigente(p["id"], "posts_periodo", ref)
        for post in base.posts_na_janela(p["id"], janela.ini if janela else None, janela.fim if janela else None):
            top.append({"perfil": base.nome_perfil(p), "data": date.fromisoformat(post[1]), "curtidas": post[3],
                        "ocultas": post[4], "comentarios": post[5], "tipo": post[6], "link": post[7]})
    top.sort(key=lambda x: -(x["curtidas"] or -1))

    # KPIs da capa
    def media(valores):
        v = [x for x in valores if x is not None]
        return sum(v) / len(v) if v else None

    col = {c.grupo + c.titulo if c.grupo else c.titulo: k for k, c in enumerate(resumo.colunas)}
    kpis = [
        ("Instituições monitoradas", formatar(len(resumo.linhas), "contagem"), ""),
        ("App Store · nota média", formatar(media([l.valores[col["App StoreNota"]] for l in resumo.linhas]), "nota"), "média das instituições"),
        ("Google Play · nota média", formatar(media([l.valores[col["Google PlayNota"]] for l in resumo.linhas]), "nota"), "média das instituições"),
        ("Consumidor.gov · solução", formatar(media([l.valores[col["Consumidor.govSolução"]] for l in resumo.linhas]), "pct"), "média das instituições"),
        ("Reclame Aqui · nota", formatar(media([l.valores[col["Reclame AquiNota (0–10)"]] for l in resumo.linhas]), "nota"), "média das instituições"),
        ("Instagram · seguidores", formatar(sum(l.valores[col["InstagramSeguidores"]] or 0 for l in resumo.linhas) or None, "contagem"), "soma dos perfis"),
    ]

    # Histórico: último valor de cada mês e todos os levantamentos (formato longo)
    rotulos = {m[0]: m[1] for m in dados["metricas"]}
    todos, ultimo_do_mes = [], {}
    for (perfil_id, metrica), lista in base.series.items():
        p = base.perfis.get(perfil_id)
        if not p:
            continue
        for r in lista:
            linha = [r.ref, base.nome_inst(p["inst"]), PLATAFORMAS.get(p["plat"], p["plat"]),
                     p["rotulo"] or p["ident"], rotulos.get(metrica, metrica), metrica, r.valor, r.texto, r.ini, r.fim]
            todos.append(linha)
            ultimo_do_mes[(perfil_id, metrica, r.ref.strftime("%Y-%m"))] = linha
    todos.sort(key=lambda l: (l[0], l[1], l[2], l[3], l[5]))
    mensal = sorted(([k[2], *v[1:], v[0]] for k, v in ultimo_do_mes.items()), key=lambda l: (l[0], l[1], l[2], l[3], l[5]))

    return Relatorio(
        mes=mes, titulo_mes=nome_mes(mes), data_ref=ref, data_anterior=ant,
        gerado_em=dados.get("gerado_em", ""), origem=origem, resumo=resumo,
        tabelas=[lojas, lojas_apps, consumidor, reclame, instagram], kpis=kpis, top_posts=top,
        lojas_grafico=grafico, historico_mensal=mensal, todos_levantamentos=todos,
    )
