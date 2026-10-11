-- Base diária e somável do consumidor.gov: uma linha por perfil e data de finalização.
-- No BI, filtre o intervalo em data_finalizacao, some as colunas e divida:
--   % respondidas     = SUM(respondidas) / SUM(total_reclamacoes)
--   % resolvidas      = SUM(resolvidas) / SUM(avaliadas)
--   nota média        = SUM(soma_notas) / SUM(qtd_notas)
--   tempo médio (dias) = SUM(soma_tempo_resposta_dias) / SUM(qtd_tempo_resposta)
-- Nunca tire média de médias diárias: o resultado sai errado.
-- Pressupõe avaliacao gravada como 'Resolvida' / 'Não Resolvida' / 'Não Avaliada'.
CREATE OR REPLACE VIEW vw_consumidor_gov_periodo AS
SELECT
    r.data_finalizacao,
    i.id            AS instituicao_id,
    i.nome          AS instituicao,
    i.nome_curto    AS instituicao_nome_curto,
    i.segmento      AS instituicao_segmento,
    pl.codigo       AS plataforma_codigo,
    pl.nome         AS plataforma,
    p.id            AS perfil_id,
    p.identificador AS perfil_identificador,
    p.rotulo        AS perfil_rotulo,
    count(*)                                              AS total_reclamacoes,
    count(*) FILTER (WHERE r.respondida)                  AS respondidas,
    count(*) FILTER (WHERE r.avaliacao = 'Resolvida')     AS resolvidas,
    count(*) FILTER (WHERE r.avaliacao IN ('Resolvida', 'Não Resolvida')) AS avaliadas,
    coalesce(sum(r.nota_consumidor), 0)                   AS soma_notas,
    count(r.nota_consumidor)                              AS qtd_notas,
    coalesce(sum(r.tempo_resposta_dias), 0)               AS soma_tempo_resposta_dias,
    count(r.tempo_resposta_dias)                          AS qtd_tempo_resposta
FROM reclamacoes_consumidor_gov r
JOIN perfis p       ON p.id = r.perfil_id
JOIN instituicoes i ON i.id = p.instituicao_id
JOIN plataformas pl ON pl.codigo = p.plataforma_codigo
GROUP BY r.data_finalizacao, i.id, pl.codigo, p.id;
