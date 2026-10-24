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
@page { size: A4 landscape; margin: 10mm 12mm 13mm;
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
/* Na tela, a mesma largura útil da página impressa (o ajuste de zoom mede aqui). */
@media screen { body { width: 273mm; } }
/* Cada seção ocupa uma página; a tabela é reduzida (zoom) para caber inteira nela. */
section { break-before: page; break-inside: avoid; }
.cabecalho-secao { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 1.5mm; }
.janela { display: inline-block; background: #eef2f8; color: #5b6475; border-radius: 99px; padding: 1px 8px; font-size: 7.5pt; }
.caixa-tabela { transform-origin: top left; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
tr { break-inside: avoid; }
th { background: #eef2f8; color: #3c4556; font-size: 7.5pt; font-weight: bold; text-align: right; padding: 4px 7px; vertical-align: bottom; }
th:first-child, td:first-child { text-align: left; }
th .g { display: block; color: #8a93a3; font-weight: normal; }
td { padding: 2.6px 7px; border-bottom: 1px solid #e6e9ee; text-align: right; white-space: nowrap; font-size: 8.5pt; line-height: 1.3; }
tbody tr:nth-child(even) td { background: #f8f9fb; }
td .v { font-weight: bold; }
td .x { display: inline-block; min-width: 13mm; margin-left: 5px; font-size: 7pt; color: #8a93a3; text-align: left; }
td .melhor { color: #0a7d0a; } td .pior { color: #c13030; }
td.vazio .v { color: #b0b6c1; font-weight: normal; }
.nota { color: #8a93a3; font-size: 7pt; margin: 2mm 0 0; }
.capa-nota { color: #5b6475; font-size: 9pt; line-height: 1.6; max-width: 200mm; }
.capa-nota li { margin-bottom: 1mm; }
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


# Ajusta cada tabela para caber numa página A4 deitada: mede a altura de cada
# seção e aplica zoom. Roda no navegador antes de imprimir.
SCRIPT_AJUSTE = """
<script>
(function () {
  const mm = 96 / 25.4;
  const alturaUtil = (210 - 10 - 13) * mm - 6;  // A4 deitado menos margens da @page
  document.querySelectorAll("section").forEach((sec) => {
    const caixa = sec.querySelector(".caixa-tabela");
    if (!caixa) return;
    const outros = sec.scrollHeight - caixa.scrollHeight;
    const zoom = Math.min(1, (alturaUtil - outros) / caixa.scrollHeight);
    if (zoom < 1) caixa.style.zoom = zoom.toFixed(3);
  });
})();
</script>"""


def _tabela_simples(cabecalho: list[str], linhas: list[list[str]]) -> str:
    cab = "".join(f"<th>{escape(c)}</th>" for c in cabecalho)
    corpo = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in linha) + "</tr>" for linha in linhas)
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table>"


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

    def secao(titulo: str, cabecalho_extra: str, tabela_html: str, nota: str | None) -> str:
        nota_html = f'<p class="nota">{escape(nota)}</p>' if nota else ""
        return (f'<section><div class="cabecalho-secao"><h2>{escape(titulo)}</h2>{cabecalho_extra}</div>'
                f'<div class="caixa-tabela">{tabela_html}</div>{nota_html}</section>')

    def secao_tabela(t: Tabela) -> str:
        return secao(t.titulo, janelas(t), _tabela_html(t, com_anterior), t.nota)

    por_id = {t.id: t for t in rel.tabelas}
    tipos = {"IMAGE": "imagem", "VIDEO": "vídeo", "CAROUSEL_ALBUM": "carrossel"}
    posts = [
        [escape(p["perfil"]), fmt_data(p["data"]), escape(tipos.get(p["tipo"], p["tipo"] or "—")),
         f"<span class='v'>{'ocultas' if p['curtidas'] is None else formatar(p['curtidas'], 'contagem')}</span>",
         formatar(p["comentarios"], "contagem"),
         f"<a href=\"{escape(p['link'])}\">abrir</a>" if (p["link"] or "").startswith("https://www.instagram.com/") else "—"]
        for p in rel.top_posts[:30]
    ]
    secao_posts = secao("Posts mais curtidos", janelas(por_id["instagram"]),
                        _tabela_simples(["Perfil", "Data", "Tipo", "Curtidas", "Comentários", "Link"], posts),
                        "Os 30 posts com mais curtidas na janela do Instagram; a lista completa está no Excel.") if posts else ""
    conteudo = [
        "Resumo por instituição: uma linha por instituição com os principais indicadores de cada fonte.",
        "App Store × Google Play: nota média de cada instituição nas duas lojas, a média e a diferença entre elas.",
        "Consumidor.gov.br: indicadores do ano corrente.",
        "Reclame Aqui: indicadores dos últimos 6 meses.",
        "Instagram: seguidores e posts e curtidas do último mês inteiro, mais os posts mais curtidos.",
    ]
    if com_anterior:
        conteudo.append("Ao lado de cada valor, a variação: ▲ ▼ em verde quando melhora e em vermelho quando piora; "
                        "volumes (reclamações, posts) ficam em cinza.")

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de reputação · {escape(rel.titulo_mes)}</title><style>{ESTILO}</style></head><body>
<div class="capa"><h1>Relatório de reputação digital</h1><div class="mes">{escape(rel.titulo_mes[:1].upper() + rel.titulo_mes[1:])}</div>
<p class="sub">Levantamento de {fmt_data(rel.data_ref)} · {escape(comparacao)} Gerado em {escape(rel.gerado_em)}.</p></div>
<div class="kpis">{kpis}</div>
<div class="capa-nota"><b>Neste relatório</b><ul>{''.join(f'<li>{escape(c)}</li>' for c in conteudo)}</ul></div>
{secao_tabela(rel.resumo)}
{secao_tabela(por_id["lojas"])}
{secao_tabela(por_id["consumidor_gov"])}
{secao_tabela(por_id["reclame_aqui"])}
{secao_tabela(por_id["instagram"])}
{secao_posts}
{SCRIPT_AJUSTE}
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
