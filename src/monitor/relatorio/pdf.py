"""Exporta o relatório para PDF: monta um HTML de impressão e usa o Edge/Chrome do
computador (modo headless) para gerar o arquivo. Só abre um arquivo local; não acessa sites."""

import os
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path

from monitor.relatorio.dados import Relatorio, Tabela, fmt_data, formatar, variacao

CANDIDATOS_WINDOWS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


class NavegadorAusente(RuntimeError):
    pass


def localizar_navegador() -> str:
    preferido = os.environ.get("NAVEGADOR_PDF")
    if preferido and Path(preferido).exists():
        return preferido
    for caminho in CANDIDATOS_WINDOWS:
        if Path(caminho).exists():
            return caminho
    for nome in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        if achado := shutil.which(nome):
            return achado
    raise NavegadorAusente(
        "Não encontrei Edge nem Chrome para gerar o PDF. Defina NAVEGADOR_PDF com o caminho "
        "do executável ou abra o HTML do relatório e use Imprimir > Salvar como PDF."
    )


ESTILO = """
@page { size: A4 landscape; margin: 14mm 14mm 16mm;
  @bottom-left { content: "Monitor de reputação digital"; font: 8pt Arial, sans-serif; color: #8a93a3; }
  @bottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt Arial, sans-serif; color: #8a93a3; } }
* { box-sizing: border-box; }
body { margin: 0; font: 9pt/1.4 Arial, "Segoe UI", sans-serif; color: #1d2433; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1 { font-size: 22pt; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 14pt; margin: 0 0 2px; }
.capa { padding: 8mm 0 4mm; border-bottom: 2px solid #2a78d6; margin-bottom: 8mm; }
.capa .mes { font-size: 13pt; color: #2a78d6; font-weight: bold; }
.grafico svg { display: block; width: 100%; max-height: 125mm; }
.sub { color: #5b6475; font-size: 9pt; margin: 2px 0 0; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4mm; margin: 6mm 0 8mm; }
.kpi { background: #f4f6f9; border-radius: 3mm; padding: 4mm; }
.kpi .r { color: #5b6475; font-size: 8pt; }
.kpi .v { font-size: 17pt; font-weight: bold; margin: 1mm 0; }
.kpi .d { color: #8a93a3; font-size: 7.5pt; }
section { break-before: page; }
section.primeira { break-before: auto; }
.janela { display: inline-block; background: #eef2f8; color: #5b6475; border-radius: 99px; padding: 1px 8px; font-size: 8pt; margin: 3px 4px 6px 0; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; margin-top: 3mm; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #eef2f8; color: #3c4556; font-size: 7.5pt; font-weight: bold; text-align: right; padding: 5px 6px; vertical-align: bottom; }
th:first-child, td:first-child { text-align: left; }
th .g { display: block; color: #8a93a3; font-weight: normal; }
td { padding: 4px 6px; border-bottom: 1px solid #e6e9ee; text-align: right; white-space: nowrap; }
td:first-child { white-space: normal; }
tbody tr:nth-child(even) td { background: #fafbfc; }
td .v { font-weight: bold; }
td .x { display: block; font-size: 7pt; color: #8a93a3; }
td .melhor { color: #0a7d0a; } td .pior { color: #c13030; }
td.vazio .v { color: #b0b6c1; font-weight: normal; }
.nota { color: #8a93a3; font-size: 7.5pt; margin-top: 3mm; }
.legenda { font-size: 8pt; color: #5b6475; margin: 2mm 0; }
.legenda i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin: 0 4px 0 10px; vertical-align: -1px; }
svg text { font-family: Arial, sans-serif; }
a { color: #2a78d6; text-decoration: none; }
"""


def _tabela_html(tabela: Tabela, com_anterior: bool) -> str:
    cab = [f"<th>{escape(tabela.rotulo_linha)}</th>"]
    for c in tabela.colunas:
        grupo = f'<span class="g">{escape(c.grupo)}</span>' if c.grupo else ""
        cab.append(f"<th>{grupo}{escape(c.titulo)}</th>")
    corpo = []
    for linha in tabela.linhas:
        celulas = [f"<td>{escape(linha.rotulo)}</td>"]
        for k, c in enumerate(tabela.colunas):
            atual = linha.valores[k]
            texto = formatar(atual, c.formato)
            extra = ""
            if com_anterior:
                v = variacao(atual, linha.anteriores[k], c)
                if v:
                    extra = f'<span class="x {v[1]}">{escape(v[0])}</span>'
                elif c.formato == "texto" and linha.anteriores[k] and linha.anteriores[k] != atual:
                    extra = f'<span class="x">antes: {escape(str(linha.anteriores[k]))}</span>'
            classe = ' class="vazio"' if atual is None else ""
            celulas.append(f'<td{classe}><span class="v">{escape(texto)}</span>{extra}</td>')
        corpo.append("<tr>" + "".join(celulas) + "</tr>")
    return f"<table><thead><tr>{''.join(cab)}</tr></thead><tbody>{''.join(corpo)}</tbody></table>"


def _halteres_svg(itens: list[tuple[str, float | None, float | None]]) -> str:
    validos = [(n, a, g) for n, a, g in itens if a is not None or g is not None]
    if not validos:
        return ""
    validos.sort(key=lambda x: -sum(v for v in x[1:] if v is not None) / len([v for v in x[1:] if v is not None]))
    todos = [v for _, a, g in validos for v in (a, g) if v is not None]
    x0 = max(1.0, int((min(todos) - 0.05) * 2) / 2)
    x1 = 5.0
    larg, nome_w, val_w, alt = 1000, 190, 60, 15
    area = larg - nome_w - val_w - 20
    pos = lambda v: nome_w + 10 + (v - x0) / (x1 - x0) * area  # noqa: E731
    altura = 26 + alt * len(validos)
    partes = [f'<svg viewBox="0 0 {larg} {altura}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    passo = 0.5 if x1 - x0 <= 2 else 1
    v = x0
    while v <= x1 + 1e-9:
        x = pos(v)
        partes.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="18" y2="{altura}" stroke="#e6e9ee"/>')
        partes.append(f'<text x="{x:.1f}" y="12" font-size="10" fill="#8a93a3" text-anchor="middle">{str(v).replace(".", ",").rstrip("0").rstrip(",")}</text>')
        v += passo
    for i, (nome, a, g) in enumerate(validos):
        y = 26 + i * alt + alt / 2 - 4
        partes.append(f'<text x="{nome_w}" y="{y + 4:.1f}" font-size="10.5" fill="#3c4556" text-anchor="end">{escape(nome)}</text>')
        if a is not None and g is not None:
            partes.append(f'<line x1="{pos(a):.1f}" x2="{pos(g):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="#c9ced6" stroke-width="2"/>')
        for valor, cor in ((a, "#2a78d6"), (g, "#eb6834")):
            if valor is not None:
                partes.append(f'<circle cx="{pos(valor):.1f}" cy="{y:.1f}" r="5" fill="{cor}" stroke="#fff" stroke-width="1.5"/>')
        media = [v for v in (a, g) if v is not None]
        partes.append(f'<text x="{larg - 6}" y="{y + 4:.1f}" font-size="10.5" fill="#1d2433" text-anchor="end">{formatar(sum(media) / len(media), "nota")}</text>')
    partes.append("</svg>")
    return "".join(partes)


def montar_html(rel: Relatorio) -> str:
    com_anterior = rel.data_anterior is not None
    comparacao = (f"Variações em relação ao levantamento de {fmt_data(rel.data_anterior)} (mês anterior)."
                  if com_anterior else "Ainda não há levantamento do mês anterior: as variações aparecem a partir do próximo mês.")
    kpis = "".join(f'<div class="kpi"><div class="r">{escape(r)}</div><div class="v">{escape(v)}</div><div class="d">{escape(d)}</div></div>'
                   for r, v, d in rel.kpis)

    def janelas(t: Tabela) -> str:
        partes = []
        if t.janela:
            partes.append(f'<span class="janela">Atual: {escape(t.janela)}</span>')
        if t.janela_anterior and com_anterior:
            partes.append(f'<span class="janela">Mês anterior: {escape(t.janela_anterior)}</span>')
        return "".join(partes)

    def secao(t: Tabela, antes: str = "", depois: str = "", classe: str = "") -> str:
        nota = f'<p class="nota">{escape(t.nota)}</p>' if t.nota else ""
        tabela = _tabela_html(t, com_anterior)
        if antes:  # gráfico ocupa a página; a tabela começa na seguinte
            tabela = f'<div style="break-before: page">{tabela}</div>'
        return (f'<section class="{classe}"><h2>{escape(t.titulo)}</h2>{janelas(t)}{antes}'
                f"{tabela}{nota}{depois}</section>")

    por_id = {t.id: t for t in rel.tabelas}
    lojas = por_id["lojas"]
    grafico = ('<div class="legenda"><i style="background:#2a78d6"></i>App Store<i style="background:#eb6834"></i>Google Play'
               ' · ordenado pela média das duas lojas</div><div class="grafico">' + _halteres_svg(rel.lojas_grafico) + "</div>")
    tipos = {"IMAGE": "imagem", "VIDEO": "vídeo", "CAROUSEL_ALBUM": "carrossel"}
    linhas_posts = "".join(
        f"<tr><td>{escape(p['perfil'])}</td><td>{fmt_data(p['data'])}</td><td>{escape(tipos.get(p['tipo'], p['tipo'] or '—'))}</td>"
        f"<td><span class='v'>{'ocultas' if p['curtidas'] is None else formatar(p['curtidas'], 'contagem')}</span></td>"
        f"<td>{formatar(p['comentarios'], 'contagem')}</td>"
        f"<td>{'<a href=\"' + escape(p['link']) + '\">abrir</a>' if (p['link'] or '').startswith('https://www.instagram.com/') else '—'}</td></tr>"
        for p in rel.top_posts[:15])
    posts = ("<h2 style='margin-top:8mm'>Posts mais curtidos</h2><table><thead><tr><th>Perfil</th><th>Data</th><th>Tipo</th>"
             f"<th>Curtidas</th><th>Comentários</th><th>Link</th></tr></thead><tbody>{linhas_posts}</tbody></table>") if linhas_posts else ""

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de reputação · {escape(rel.titulo_mes)}</title><style>{ESTILO}</style></head><body>
<div class="capa"><h1>Relatório de reputação digital</h1><div class="mes">{escape(rel.titulo_mes[:1].upper() + rel.titulo_mes[1:])}</div>
<p class="sub">Levantamento de {fmt_data(rel.data_ref)} · {escape(comparacao)} Gerado em {escape(rel.gerado_em)}.</p></div>
<div class="kpis">{kpis}</div>
{secao(rel.resumo, classe="primeira")}
{secao(lojas, antes=grafico)}
{secao(por_id["consumidor_gov"])}
{secao(por_id["reclame_aqui"])}
{secao(por_id["instagram"], depois=posts)}
</body></html>"""


def exportar_pdf(rel: Relatorio, caminho: Path, manter_html: bool = False) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    html_path = caminho.with_suffix(".html")
    html_path.write_text(montar_html(rel), encoding="utf-8")
    navegador = localizar_navegador()
    with tempfile.TemporaryDirectory(prefix="monitor-pdf-") as perfil:
        subprocess.run(
            [navegador, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
             f"--user-data-dir={perfil}", f"--print-to-pdf={caminho.resolve()}", html_path.resolve().as_uri()],
            check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    if not caminho.exists():
        raise RuntimeError(f"o navegador não gerou o PDF; abra {html_path} e imprima como PDF")
    if not manter_html:
        html_path.unlink(missing_ok=True)
    return caminho
