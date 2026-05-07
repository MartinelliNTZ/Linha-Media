# Fluxo Conexão de Linhas

## Parâmetros
- INPUT
- SENSOR_LIMIT
- SPACING
- MIN_SEGMENT
- PTS_PER_VTX
- EXTENSAO
- POLYGON_INPUT

## Etapas

1. INPUT [linhas]
2. POLYGON_INPUT [LIMITE borda polígono linha]
3. EXTENSAO + LIMITE [medir pontas até borda]
4. EXTENSAO + LIMITE [estender pontas < EXTENSAO]
5. SPACING [padronizar linhas INPUT]
6. LIMITE no índice [detectável, sem sensores]
7. SENSOR_LIMIT [perpendiculares só INPUT]
8. Vizinhança [cortar sensores + LIMITE]
9. Vértices [agrupar vizinhos E/D]
10. keySec [segmentar por vizinhança]
11. MIN_SEGMENT [corrigir grupos pequenos]
12. Particionar [dividir linhas por keySec]
13. LIMITE no índice secundário
14. Sensores Secundários [só segmentos, + LIMITE]
15. Votos vizinhos [moda E e D por segmento]
16. Output + MatchJudge [incluir LIMITE is_limite=1]
17. MatchJudge [pares válidos e inválidos]
18. LIMITE sempre keyMother [forçar mãe]
19. SimpleConnection [conectar father/mother]
20. Classificar Cstatus [normal/duplicado]
21. Classificar Final [valid/maxVertex/transpose/x]
22. PAIR_CONN_OUTPUT [conexões finais]

## Produtos

- LIMITE_OUTPUT [bordas polígono em linha]
- OUTPUT [linhas padronizadas segmentadas]
- PERP_OUTPUT [sensores primários]
- VERT_OUTPUT [vértices agrupados]
- SEC_PERP_OUTPUT [sensores secundários]
- PAIR_CONN_OUTPUT [conexões por par]