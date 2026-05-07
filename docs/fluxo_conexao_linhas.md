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
 Tranformar borda do poligono em linha LIMITE - OUTPUT
MEDIR A DISTANCIA DE TODAS AS PONTAS DA INPUT ATE O PONTO MAIS PROXIMO do limite
ver qual pontas estao a menos do que a EXTENSAO de distancia, 
extender pontas menores que (EXTENSAO) usar a distancia do limite como valor de extensaoja foi calculado da praa usa
segue demais passos
3. SPACING [padronizar linhas]
4. SENSOR_LIMIT [gerar perpendiculares]
5. Vizinhança [cortar sensores]
6. Vértices [agrupar vizinhos]
7. keySec [segmentar vértices]
8. MIN_SEGMENT [corrigir grupos pequenos]
9. Particionar [dividir linhas]
10. Sensores Secundários [gerar por segmento]
11. MatchJudge [validar pares]
12. SimpleConnection [conectar segmentos]

## Produtos

- OUTPUT [linhas padronizadas]
- PERP_OUTPUT [sensores primários]
- VERT_OUTPUT [vértices]
- SEC_PERP_OUTPUT [sensores secundários]
- PAIR_CONN_OUTPUT [conexões por par]