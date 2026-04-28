# Plano de Ação — Linha Mestra (Em Massa) — Modo Default
## Proximidade × Proximidade | Sem ID | Sem Grupo

---

## 1. Visão Geral do Fluxo

```
INPUT (Layer de curvas)
  │
  ├─ ETAPA 0: Zerar atributos, gerar ID_Mae único (string: "L0", "L1", ... "L50")
  │
  ├─ ETAPA 1: 1ª CONSULTA — Perpendiculares de sensoriamento
  │     │  Para cada vértice de cada linha (1000 partições), lança raios ±90°
  │     │  Cada raio que toca uma linha INPUT → grava contato
  │     │  Output: ID_Mae, ID_Vertice (ex: "L7_V0"), ID_Par, ID_Vizinho (ID_Mae da linha tocada),
  │     │          Azimute, Distância, Lado (E/D), Coord
  │     └─ Perpendiculares são cortadas no ponto de toque (metade pra cada lado)
  │
  ├─ ETAPA 2: FRAGMENTAÇÃO — Quebra por mudança de vizinhança
  │     │  Varre vértices sequencialmente
  │     │  Se conjunto de vizinhos muda → quebra a linha
  │     │  Ex: 50 linhas originais → ~150 segmentos fragmentados
  │     │  Output: segmentos com novo ID (ex: "S0", "S1", ... "S150")
  │     └─ RESET de IDs após fragmentação
  │
  ├─ ETAPA 3: 2ª CONSULTA — Perpendiculares sobre linhas fragmentadas
  │     │  MESMO processo da ETAPA 1, mas tendo como INPUT os segmentos fragmentados
  │     │  Output: ID_Mae (NOVO), ID_Vertice (NOVO), ID_Vizinho (ID do segmento fragmentado),
  │     │          Azimute, Distância, Lado, Coord
  │     └─ Gera também OUTPUT de VÉRTICES
  │
  └─ ETAPA 4: PROCESSAMENTO DE PARES (Proximidade × Proximidade)
        │  ConnectionJudge.solve_nearest_with_criteria()
        │  Gera Linha Mestra e Conexões (outputs já existentes)
        └─ OUTPUT 3: Perpendiculares do processamento (já implementado)
```

---

## 2. Sistema de IDs

### Regras:
1. **Ao entrar na ferramenta**: apagar qualquer campo ID existente, criar campo `ID_Mae` limpo
2. **ID_Mae**: string sequencial por ordem de entrada (ex: `"L0"`, `"L1"`, ..., `"L50"`)
3. **ID_Vertice**: `"{ID_Mae}_V{indice}"` (ex: `"L7_V0"`, `"L7_V1"`, ..., `"L7_V100"`)
4. **ID_Segmento** (pós-fragmentação): `"S{indice_global}"` (ex: `"S0"`, `"S1"`, ..., `"S150"`)
5. **Vértices pós-fragmentação**: `"{ID_Segmento}_V{indice}"` (ex: `"S42_V0"`)

### Mapeamento:
| Momento | ID Linha | ID Vértice |
|---------|----------|------------|
| Entrada | `L7` | `L7_V0`, `L7_V1`, ... |
| Pós-quebra | `S42` (filho de L7) | `S42_V0`, `S42_V1`, ... |

---

## 3. Estrutura dos Outputs de Consulta

### OUTPUT_CONSULTA_1 (1ª Consulta — Sensores)
| Campo | Tipo | Exemplo | Descrição |
|-------|------|---------|-----------|
| `id_mae` | String | `"L7"` | ID da linha original |
| `id_vertice` | String | `"L7_V42"` | ID do vértice na linha original |
| `id_par` | Int | 1 | Par processado |
| `id_vizinho` | String | `"L15"` | ID_Mae da linha que o raio tocou |
| `azimute_local` | Double | 45.3 | Azimute da linha no vértice |
| `azimute_raio` | Double | 135.3 | Direção do raio (+90 ou -90) |
| `lado` | String | `"esquerdo"` | Lado do sensor |
| `distancia_vizinho` | Double | 23.7 | Distância até o vizinho |
| `coord_x` | Double | -46.12 | Coord X do ponto de origem |
| `coord_y` | Double | -23.45 | Coord Y do ponto de origem |

### OUTPUT_CONSULTA_2 (2ª Consulta — Pós-Fragmentação)
Mesmo schema, mas:
- `id_mae` = ID do segmento fragmentado (ex: `"S42"`)
- `id_vertice` = ID do vértice no segmento (ex: `"S42_V7"`)
- `id_vizinho` = ID do segmento fragmentado que foi tocado (ex: `"S88"`)

### OUTPUT_VERTICES (Novo)
| Campo | Tipo | Exemplo | Descrição |
|-------|------|---------|-----------|
| `id_vertice` | String | `"L7_V42"` | ID do vértice |
| `id_linha` | String | `"L7"` | ID da linha mãe |
| `indice` | Int | 42 | Posição na polyline |
| `coord_x` | Double | -46.12 | Coord X |
| `coord_y` | Double | -23.45 | Coord Y |

---

## 4. Regras de Fragmentação

- Cada vértice tem um conjunto de vizinhos (IDs das linhas que o raio tocou)
- Lado esquerdo e lado direito são tratados **separadamente**
- Se o conjunto de vizinhos **muda** entre vértices consecutivos → quebra
- Cada fragmento tem **no máximo 1 vizinho por lado** (1 esquerdo, 1 direito)
- Quebrou? Reseta IDs e gera nova consulta

---

## 5. Parâmetros do Algoritmo (Atualizados)

| Parâmetro | Nome | Tipo |
|-----------|------|------|
| INPUT | Camada de Linhas | FeatureSource |
| ORDER_FIELD | Campo de Ordenação (Opcional) | Field |
| GROUP_FIELD | Campo de Agrupamento (Opcional) | Field |
| PARTICOES | Número de Partições | Integer (default 1000) |
| ESTILO_CONEXAO | Estilo de Conexão | Enum |
| ESTILO_LINHA_MESTRA | Estilo da Linha Mestra | Enum |
| CRITERIO_PROXIMIDADE | Critério de Proximidade | Enum |
| RESOLVER_ORFAOS_PONTAS | Resolver órfãos | Boolean |
| ESPACAMENTO | Espaçamento Fixo | Double |
| ALCANCE_SENSOR | Alcance do Sensor | Double |
| REDUCAO_FILTRO | Redução Filtro Cruzamento | Double (Advanced) |
| OUTPUT | Linhas Mestras | FeatureSink |
| CONEXAO_OUTPUT | Conexões | FeatureSink |
| OUTPUT_CONSULTA_1 | Consulta: Sensores 1ª Varredura | FeatureSink (optional) |
| OUTPUT_CONSULTA_2 | Consulta: Sensores 2ª Varredura | FeatureSink (optional) |
| OUTPUT_SEGMENTOS | Segmentos Fragmentados | FeatureSink (optional) |
| OUTPUT_VERTICES | Vértices | FeatureSink (optional) |
| OUTPUT_PERP_PROC | Perpendiculares do Processamento | FeatureSink (optional) |

---

## 6. Observações Técnicas

- **Não usar buffer** (`sensores_buffer`): escrever direto no sink durante a varredura
- **Perpendiculares cortadas**: metade pra cada lado quando tocam uma linha
- **QgsSpatialIndex**: funciona com features criadas manualmente no QGIS 3.16? Testar.
- **Alcance 400m**: suficiente para cruzar várias linhas; perpendiculares podem se cruzar
- **Objetivo final**: preencher tudo com conexões, casando pares de linhas (Proximidade × Proximidade)