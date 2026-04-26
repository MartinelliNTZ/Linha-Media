# LinhaMestra - Documentação do Sistema

## Visão Geral do Plugin

LinhaMestra é um plugin QGIS para processamento de linhas agrícolas, desenvolvido para auxiliar no manejo de lavouras de soja. O sistema oferece ferramentas para geração, numeração e manipulação de linhas mestras e perpendiculares.

## Arquitetura do Sistema

```
linhamestra/
├── LinhaMestra.py              # Plugin principal
├── LinhaMestra_provider.py      # Provider de algoritmos
├── algorthms/                  # Algoritmos de processamento
│   ├── LinhaMestra_algorithm.py
│   ├── LinhaMestra_numeracao_algorithm.py
│   ├── LinhaMestra_perpendicular_algorithm.py
│   ├── LinhaMestra_massa_algorithm.py
│   ├── LinhaMestra_extensao_algorithm.py
│   └── LinhaMestra_corte_algorithm.py
└── core/                       # Módulos utilitários
    ├── vector_utils.py
    ├── geometry_utils.py
    └── connection_judge.py
```

## Algoritmos Disponíveis

### 1. LinhaMestraAlgorithm
Gera linha mestra a partir de duas camadas de linhas.

**Parâmetros:**
- Primeira Camada (ou camada com as 2 linhas)
- Segunda Camada (Opcional)
- Número de Partições
- Estilo de Conexão (Proximidade, Perpendicular, Direta, Espaçamento Fixo)
- Estilo da Linha Mestra (Interpolação, Proximidade, Espaçamento Fixo)
- Critério de Proximidade

### 2. LinhaMestraNumeracaoAlgorithm
Numera linhas de soja identificando passadas e grupos direcionais.

**Parâmetros:**
- Camada de Linhas (Soja)
- Desvio Aceitável Tipo (Graus)
- Desvio Aceitável Sequência (Graus)
- Tolerância GPS (Metros)

### 3. LinhaPerpendicularMediaAlgorithm
Gera linhas perpendiculares em vértices de linhas de entrada.

**Parâmetros:**
- Camada de Linhas (para gerar perpendiculares)
- Camada de Linhas Mães (Opcional)
- Distância Fixa

### 4. LinhaMestraMassaAlgorithm
Gera linhas mestras em massa para múltiplas feições.

**Parâmetros:**
- Camada de Linhas
- Campo de Ordenação
- Campo de Agrupamento (Opcional)
- Número de Partições
- Estilos de Conexão e Linha Mestra

### 5. LinhaMestraExtensaoAlgorithm
Estende ou reduz linhas por valor fixo.

**Parâmetros:**
- Camada de Linhas
- Valor de Ajuste (metros)

### 6. LinhaMestraCorteAlgorithm
Corta feições (polígonos ou linhas) usando camada de linhas.

**Parâmetros:**
- Camada de Entrada
- Camada de Corte

## Módulos Core

### VectorUtils (core/vector_utils.py)
Utilitários para manipulação de geometrias vetoriais:
- `orient_northwest()` - Orienta linhas para Noroeste
- `align_line_pair()` - Alinha pares de linhas
- `analyze_straightness()` - Analisa retidão de linhas
- `generate_linhamestra_elements()` - Gera elementos da linha mestra
- `generate_perpendiculars_from_line_vertices()` - Gera perpendiculares

### ConnectionJudge (core/connection_judge.py)
Lógica de conectividade entre camadas:
- `generate_nearest_with_orphans()` - Gera conexões com resolução de órfãos
- `solve_nearest_with_criteria()` - Decide qual linha é base conforme critério

### VectorLayerGeometry (core/geometry_utils.py)
Manipulação de geometrias:
- `adjust_line_length()` - Estende/reduz linhas

## Conceitos Fundamentais

### Linha Mestra
Linha central que conecta duas linhas paralelas (pai e mãe), servindo como referência para operações agrícolas.

### Passada
Conjunto de linhas retas que formam uma direção de plantio (ex: Chapadão, Bicos).

### Grupo Direcional
Agrupamento de passadas com azimutes similares, representando uma área de manejo.

### Órfãos
Vértices da linha alvo que não foram conectados automaticamente - requerem tratamento especial.

## Fluxo de Processamento Típico

1. **Extensão**: Ajustar comprimento das linhas de entrada
2. **Numeração**: Identificar passadas e numerar linhas
3. **Geração Mestra**: Criar linhas mestras conectando as linhas
4. **Perpendiculares**: Gerar linhas perpendiculares nos vértices
5. **Corte**: Dividir feições conforme necessário