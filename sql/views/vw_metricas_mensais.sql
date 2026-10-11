-- Último snapshot de cada mês por perfil e métrica, para gráficos de evolução.
-- "mes" é o primeiro dia do mês da data_referencia.
CREATE OR REPLACE VIEW vw_metricas_mensais AS
SELECT DISTINCT ON (s.perfil_id, s.metrica_codigo, date_trunc('month', s.data_referencia))
    date_trunc('month', s.data_referencia)::date AS mes,
    i.id            AS instituicao_id,
    i.nome          AS instituicao,
    i.nome_curto    AS instituicao_nome_curto,
    i.segmento      AS instituicao_segmento,
    pl.codigo       AS plataforma_codigo,
    pl.nome         AS plataforma,
    pl.tipo         AS plataforma_tipo,
    p.id            AS perfil_id,
    p.identificador AS perfil_identificador,
    p.rotulo        AS perfil_rotulo,
    p.ativo         AS perfil_ativo,
    m.codigo        AS metrica_codigo,
    m.descricao     AS metrica,
    m.unidade       AS metrica_unidade,
    s.valor,
    s.valor_texto,
    s.data_referencia,
    s.periodo_inicio,
    s.periodo_fim,
    s.coletado_em
FROM snapshots_metricas s
JOIN perfis p       ON p.id = s.perfil_id
JOIN instituicoes i ON i.id = p.instituicao_id
JOIN plataformas pl ON pl.codigo = p.plataforma_codigo
JOIN metricas m     ON m.codigo = s.metrica_codigo
ORDER BY
    s.perfil_id,
    s.metrica_codigo,
    date_trunc('month', s.data_referencia),
    s.data_referencia DESC,
    s.coletado_em DESC;
