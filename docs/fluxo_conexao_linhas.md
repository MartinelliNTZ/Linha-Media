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
5. SPACING [padronizar INPUT]
6. SPACING [padronizar LIMITE]
7. LIMITE no índice [detectável, sem sensores]
8. SENSOR_LIMIT [perpendiculares só INPUT]
9. Vizinhança [cortar sensores + LIMITE]
10. Vértices [agrupar vizinhos E/D]
11. keySec [segmentar por vizinhança]
12. MIN_SEGMENT [corrigir grupos pequenos]
13. Particionar [dividir linhas por keySec]
14. LIMITE no índice secundário
15. Sensores Secundários [só segmentos + LIMITE]
16. Votos vizinhos [moda E e D por segmento]
17. Output + MatchJudge [incluir LIMITE is_limite=1]
18. MatchJudge [pares válidos e inválidos]
19. LIMITE sempre keyMother [forçar mãe]
20. SimpleConnection [conectar father/mother]
21. Classificar Cstatus [normal/duplicado]
22. Classificar Final [valid/maxVertex/transpose/x]
23. PAIR_CONN_OUTPUT [conexões finais]

## Produtos

- LIMITE_OUTPUT [bordas polígono em linha]
- OUTPUT [linhas padronizadas segmentadas]
- PERP_OUTPUT [sensores primários]
- VERT_OUTPUT [vértices agrupados]
- SEC_PERP_OUTPUT [sensores secundários]
- PAIR_CONN_OUTPUT [conexões por par]