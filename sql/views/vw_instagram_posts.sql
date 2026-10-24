-- Posts do Instagram com a contagem mais recente de curtidas e comentários.
-- curtidas nula com curtidas_ocultas = true: o perfil esconde as curtidas (não é zero).
CREATE OR REPLACE VIEW vw_instagram_posts AS
SELECT DISTINCT ON (po.id)
    i.id            AS instituicao_id,
    i.nome          AS instituicao,
    i.nome_curto    AS instituicao_nome_curto,
    p.id            AS perfil_id,
    p.identificador AS perfil_username,
    p.rotulo        AS perfil_rotulo,
    po.media_id,
    po.publicado_em,
    (po.publicado_em AT TIME ZONE 'America/Sao_Paulo')::date AS data_publicacao,
    date_trunc('month', po.publicado_em AT TIME ZONE 'America/Sao_Paulo')::date AS mes_publicacao,
    po.tipo_midia,
    po.permalink,
    s.curtidas,
    s.curtidas_ocultas,
    s.comentarios,
    s.data_coleta,
    s.idade_post_dias
FROM posts_instagram po
JOIN perfis p       ON p.id = po.perfil_id
JOIN instituicoes i ON i.id = p.instituicao_id
JOIN snapshots_posts_instagram s ON s.post_id = po.id
WHERE p.ativo AND i.ativo
ORDER BY po.id, s.data_coleta DESC, s.coletado_em DESC;
