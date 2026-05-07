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
2. EXTENSAO + POLYGON_INPUT [LIMITE borda polígono]
3. EXTENSAO + LIMITE [medir pontas até borda]
4. EXTENSAO + LIMITE [estender pontas < EXTENSAO]
5. SPACING [padronizar linhas]
6. SENSOR_LIMIT [perpendiculares primários]
7. Vizinhança [cortar sensores]
8. Vértices [agrupar vizinhos E/D]
9. keySec [segmentar por vizinhança]
10. MIN_SEGMENT [corrigir grupos pequenos]
11. Particionar [dividir linhas por keySec]
12. keySec (2) [índice espacial segmentos]
13. Sensores Secundários [perpendiculares por segmento]
14. Votos vizinhos [moda E e D por segmento]
15. Output + MatchJudge [alimentar camada julgamento]
16. MatchJudge [pares válidos e inválidos]
17. SimpleConnection [conectar geometrias]
18. Classificar Cstatus [normal/duplicado]
19. Classificar Final [valid/maxVertex/transpose/x]
20. PAIR_CONN_OUTPUT [conexões finais]

## Produtos

- LIMITE_OUTPUT [bordas polígono em linha]
- OUTPUT [linhas padronizadas segmentadas]
- PERP_OUTPUT [sensores primários]
- VERT_OUTPUT [vértices agrupados]
- SEC_PERP_OUTPUT [sensores secundários]
- PAIR_CONN_OUTPUT [conexões por par]