# Contexto para Agente IA - LinhaMestra

Este documento fornece contexto completo para que um agente de IA possa entender, modificar e estender o plugin LinhaMestra do QGIS.

## Identidade do Sistema

- **Nome**: LinhaMestra
- **Tipo**: Plugin QGIS para processamento de linhas agrícolas
- **Finalidade**: Auxiliar no manejo de lavouras de soja através de geração, numeração e manipulação de linhas mestras e perpendiculares
- **Versão**: 1.0 (2026-04-21)
- **Autor**: Iridium
- **Email**: Iridium@gmail.com

## Estrutura de Arquivos

```
linhamestra/
├── LinhaMestra.py              # Classe principal do plugin (ponto de entrada)
├── LinhaMestra_provider.py    # Provider que registra algoritmos no QGIS
├── algorthms/                 # 6 algoritmos de processamento
│   ├── LinhaMestra_algorithm.py           # Algoritmo base
│   ├── LinhaMestra_numeracao_algorithm.py # Numeração de linhas de soja
│   ├── LinhaMestra_perpendicular_algorithm.py  # Gerador de perpendiculares
│   ├── LinhaMestra_massa_algorithm.py     # Processamento em massa
│   ├── LinhaMestra_extensao_algorithm.py # Extensão/redução de linhas
│   └── LinhaMestra_corte_algorithm.py    # Corte de feições
└── core/                      # Módulos de domínio
    ├── vector_utils.py        # ~600 linhas - principal módulo utilitário
    ├── geometry_utils.py      # Manipulação de geometrias
    └── connection_judge.py    # Lógica de conectividade avançada
```

## Conceitos Fundamentais

### Linha Mestra
Linha central que conecta duas linhas paralelas (denominadas "pai" e "mãe"). Serve como referência para operações agrícolas como plantio, pulverização e colheita.

### Pai e Mãe
Duas linhas paralelas que são conectadas pela linha mestra:
- **Linha Pai**: Primeira linha no sentido do processamento
- **Linha Mãe**: Segunda linha paralela

### Passada
Conjunto de linhas retas que formam uma direção de plantio. Exemplo: linhas que vão de leste para oeste no Chapadão.

### Grupo Direcional
Agrupamento de passadas com azimutes similares. Representa áreas de manejo com direção predominante (ex: "Chapadão" = direção principal, "Bicos" = direções secundárias).

### Órfãos
Vértices da linha alvo que não foram conectados automaticamente pelo algoritmo de proximidade. O módulo `ConnectionJudge` implementa lógica especial para resolver esses casos.

### Azimute
Ângulo da linha em relação ao norte, medido em graus (0-360°). Usado para classificar a direção das linhas.

### Projeção Espacial
Fórmula usada para ordenar linhas no sentido perpendicular ao azimute:
```
valor = -x * sin(azimute) + y * cos(azimute)
```

## Algoritmos Disponíveis

### 1. LinhaMestraAlgorithm (ID: linhamestra)
**Propósito**: Algoritmo base para geração de linha mestra a partir de duas camadas de linhas.

**Parâmetros de entrada**:
- `INPUT`: Primeira Camada (ou camada com as 2 linhas) - Tipo: VectorLine
- `INPUT_2`: Segunda Camada (Opcional) - Tipo: VectorLine
- `PARTICOES`: Número de partições (default: 1000)
- `ESTILO_CONEXAO`: Estilo de conexão (0=Proximidade, 1=Perpendicular, 2=Direta, 3=Espaçamento Fixo)
- `ESTILO_LINHA_MESTRA`: Estilo da linha mestra (0=Interpolação, 1=Proximidade, 2=Espaçamento Fixo)
- `CRITERIO_PROXIMIDADE`: Critério de proximidade (0=Sincronismo, 1=Menor Tamanho, 2=Maior Tamanho, 3=Menor Ângulo, 4=Maior Ângulo)
- `RESOLVER_ORFAOS_PONTAS`: Resolver órfãos das pontas (default: False)
- `ESPACAMENTO`: Espaçamento fixo em metros

**Saídas**:
- `OUTPUT`: Linhas mestras geradas
- `CONEXAO_OUTPUT`: Conexões entre as linhas

### 2. LinhaMestraNumeracaoAlgorithm (ID: linhamestra_numeracao)
**Propósito**: Numera linhas de soja identificando passadas e grupos direcionais.

**Parâmetros de entrada**:
- `INPUT`: Camada de Linhas (Soja) - Tipo: VectorLine
- `DESVIO_TIPO`: Desvio Aceitável Tipo em graus (default: 5.0) - para agrupar passadas em grupos
- `DESVIO_SEQ`: Desvio Aceitável Sequência em graus (default: 2.0) - para unir segmentos da mesma passada
- `TOL_GPS`: Tolerância GPS em metros (default: 0.5)

**Saídas**:
- `OUTPUT`: Linhas numeradas com campos adicionais:
  - `grupo_id`: ID do grupo direcional
  - `seq_num`: Número sequencial dentro do grupo
  - `geomet_tp`: Tipo ("RETA" ou "CURVA")
  - `azimuth`: Azimute médio da linha

**Fluxo interno**:
1. Classifica cada linha como RETA ou CURVA
2. Une segmentos de linhas retas com azimutes próximos (mesma passada)
3. Agrupa passadas com azimutes similares (grupos direcionais)
4. Numera linhas dentro de cada grupo por projeção espacial

### 3. LinhaPerpendicularMediaAlgorithm (ID: linha_perpendicular_media)
**Propósito**: Gera linhas perpendiculares em cada vértice de linhas de entrada.

**Parâmetros de entrada**:
- `INPUT_LINE`: Camada de Linhas (para gerar perpendiculares) - Tipo: VectorLine
- `INPUT_LINES_MAES`: Camada de Linhas Mães (Opcional, deve ter 2 feições) - Tipo: VectorLine
- `DISTANCE`: Distância fixa em metros (default: 10.0)

**Cenários**:
- **Com Linhas Mães**: Perpendiculares cortam ambas as linhas mães
- **Sem Linhas Mães**: Perpendiculares com comprimento fixo

**Saídas**:
- `OUTPUT`: Linhas perpendiculares geradas com campos:
  - `original_id`: ID da feição original
  - `vertex_id`: Índice do vértice

### 4. LinhaMestraMassaAlgorithm (ID: linhamestra_gerador_massa)
**Propósito**: Gera linhas mestras em massa para múltiplas feições ordenadas.

**Parâmetros de entrada**:
- `INPUT`: Camada de Linhas - Tipo: VectorLine
- `ORDER_FIELD`: Campo de ordenação (sequência)
- `GROUP_FIELD`: Campo de agrupamento (opcional)
- `PARTICOES`: Número de partições
- `ESTILO_CONEXAO`: Estilo de conexão
- `ESTILO_LINHA_MESTRA`: Estilo da linha mestra
- `CRITERIO_PROXIMIDADE`: Critério de proximidade
- `RESOLVER_ORFAOS_PONTAS`: Resolver órfãos
- `ESPACAMENTO`: Espaçamento fixo
- `REDUCAO_FILTRO`: Redução para filtro de cruzamento (avançado)

**Saídas**:
- `OUTPUT`: Linhas mestras com campos: grupo, par_id, dist_mae
- `CONEXAO_OUTPUT`: Conexões com campos: grupo, id_conexao, id_pai, id_mae, id_origem

### 5. LinhaMestraExtensaoAlgorithm (ID: linhamestra_extensao)
**Propósito**: Estende ou reduz linhas por valor fixo em ambas as extremidades.

**Parâmetros de entrada**:
- `INPUT`: Camada de Linhas - Tipo: VectorLine
- `DELTA`: Valor de ajuste em metros (default: -0.01)
  - Positivo: estende a linha
  - Negativo: reduz (trim) a linha

**Saídas**:
- `OUTPUT`: Linhas ajustadas

### 6. LinhaMestraCorteAlgorithm (ID: linhamestra_corte)
**Propósito**: Corta (divide) polígonos ou linhas usando camada de linhas como lâmina.

**Parâmetros de entrada**:
- `INPUT`: Camada de Entrada (Polígonos ou Linhas) - Tipo: VectorAnyGeometry
- `CUTTER`: Camada de Corte (Linhas) - Tipo: VectorLine

**Saídas**:
- `OUTPUT`: Feições cortadas

## Módulos Core

### VectorUtils (core/vector_utils.py)

Módulo principal com funções utilitárias para manipulação de geometrias vetoriais.

**Funções principais**:

| Função | Descrição |
|--------|-----------|
| `orient_northwest(geom)` | Inverte linha se final for mais ao Norte/Oeste |
| `align_line_pair(geom1, geom2)` | Alinha par de linhas para processamento |
| `analyze_straightness(geom, threshold)` | Analisa se linha é reta (RETORNA: is_straight, avg_az, max_dev) |
| `get_line_azimuths(geom)` | Retorna lista de azimutes de todos os segmentos |
| `calculate_internal_angle(p1, p2, p3)` | Calcula ângulo interno em p2 |
| `get_line_straightness_score(geom)` | Mede "abertura" da linha (média de ângulos) |
| `get_projection_value(point, azimuth_deg)` | Calcula valor de projeção espacial |
| `decide_base_by_endpoint(geom1, geom2)` | Decide qual linha é base (lógica sincronismo) |
| `align_by_endpoint_logic(geom1, geom2)` | Determina Pai/Mãe e alinhamento |
| `get_points_at_interval(geom, interval)` | Gera pontos a cada intervalo fixo |
| `get_equidistant_points(geom, num_points)` | Gera pontos uniformemente espaçados |
| `calculate_interpolation_data(geom1, geom2, particoes)` | Gera dados de interpolação |
| `generate_linhamestra_elements(geom1, geom2, partitions)` | Orquestra geração completa |
| `generate_perpendiculars_from_line_vertices(...)` | Gera perpendiculares em vértices |
| `generate_1to1_connections(geom_pai, geom_mae, interval)` | Gera conexões 1:1 |
| `generate_mestra_from_connections(connection_results)` | Gera linha mestra a partir de conexões |
| `filter_connections(connections, g1, g2, crs, reducao)` | Filtra conexões por cruzamento |
| `create_feature(geometry, fields, attributes)` | Cria feição com geometria e atributos |
| `reproject_geometry(geom, source_crs, target_crs, context)` | Reprojeta geometria |
| `reverse_geometry(geom)` | Inverte direção da geometria |
| `get_midpoint(p1, p2)` | Calcula ponto médio |

### ConnectionJudge (core/connection_judge.py)

Módulo especializado em lógica de conectividade avançada.

**Funções principais**:

| Função | Descrição |
|--------|-----------|
| `generate_nearest_with_orphans(base_geom, target_geom, target_n, resolve_endpoints)` | Gera conexões com resolução de órfãos |
| `solve_nearest_with_criteria(geom1, geom2, criteria_idx, target_n, resolve_endpoints)` | Decide base por critério |
| `_find_nearest_vertex_index(point, vertices)` | Auxiliar: encontra vértice mais próximo |

**Lógica de Resolução de Órfãos**:
1. Conecta pontos da base aos pontos mais próximos do alvo
2. Identifica vértices não alcançados (órfãos)
3. Aplica tratamento especial:
   - Órfãos no início: conecta ao primeiro ponto atingido
   - Órfãos no fim: conecta ao último ponto atingido
   - Órfãos no meio: conecta ao centroide dos vizinhos

### VectorLayerGeometry (core/geometry_utils.py)

Módulo para manipulação de geometrias.

**Funções principais**:

| Função | Descrição |
|--------|-----------|
| `adjust_line_length(geometry, delta)` | Estende/reduz linha em ambas extremidades |

## Casos de Uso Comuns

### Caso 1: Gerar linha mestra básica
```python
# 1. Carregar camada com 2 linhas
# 2. Executar LinhaMestraAlgorithm
# 3. Configurar partições = 1000
# 4. Escolher ESTILO_CONEXAO = 0 (Proximidade)
# 5. Escolher ESTILO_LINHA_MESTRA = 1 (Proximidade)
```

### Caso 2: Numerar linhas de soja
```python
# 1. Carregar camada de linhas
# 2. Executar LinhaMestraNumeracaoAlgorithm
# 3. DESVIO_TIPO = 5° (para grupos)
# 4. DESVIO_SEQ = 2° (para passadas)
# 5. TOL_GPS = 0.5m
```

### Caso 3: Gerar perpendiculares com linhas mães
```python
# 1. Carregar camada de linhas
# 2. Carregar 2 linhas mães
# 3. Executar LinhaPerpendicularMediaAlgorithm
```

### Caso 4: Processamento em massa
```python
# 1. Carregar camada com múltiplas linhas
# 2. Definir ORDER_FIELD = "sequencia"
# 3. Definir GROUP_FIELD = "talhao" (opcional)
# 4. Executar LinhaMestraMassaAlgorithm
```

## Padrões de Código

### Padrão 1: Algoritmo QGIS
Todos os algoritmos seguem o padrão QGIS Processing:
```python
class NomeAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    
    def initAlgorithm(self, config):
        # Define parâmetros
        
    def processAlgorithm(self, parameters, context, feedback):
        # Lógica de processamento
        return {self.OUTPUT: dest_id}
    
    def name(self):
        return 'id_do_algoritmo'
    
    def displayName(self):
        return self.tr('Nome Display')
    
    def group(self):
        return self.tr('Linha Mestra')
    
    def groupId(self):
        return 'linhamestra'
```

### Padrão 2: Funções Estáticas
Módulos core usam métodos estáticos para facilitar uso sem instância:
```python
class VectorUtils:
    @staticmethod
    def orient_northwest(geom):
        # ...
```

### Padrão 3: Retorno de Múltiplos Valores
Funções retornam dicionários ou tuplas para flexibilidade:
```python
# Retorno como dicionário
return {
    'geom': geometria,
    'dist': distancia,
    'id': id
}
```

## Extensibilidade

Para adicionar novo algoritmo:
1. Criar arquivo em `algorthms/NovoAlgoritmo_algorithm.py`
2. Implementar classe herdando de `QgsProcessingAlgorithm`
3. Registrar em `LinhaMestra_provider.py`

Para adicionar nova função utilitária:
1. Adicionar em `core/vector_utils.py` ou criar novo módulo em `core/`
2. Manter como método estático quando possível

## Referências Técnicas

- **QGIS Processing Framework**: https://qgis.org/py-docs/
- **Plugin Builder**: http://g-sherman.github.io/Qgis-Plugin-Builder/
- **QgsProcessingAlgorithm**: Classe base para algoritmos
- **QgsGeometry**: Manipulação de geometrias
- **QgsFeatureSink**: Inserção eficiente de feições

## Notas de Implementação

1. **CRS**: Sempre verificar compatibilidade de CRS entre camadas
2. **Geometrias Vazias**: Tratar casos de geometrias vazias ou nulas
3. **Feedback**: Usar feedback.pushInfo() para logs e feedback.setProgress() para progresso
4. **Cancelamento**: Verificar feedback.isCanceled() em loops longos
5. **Performance**: Usar FastInsert para inserção rápida de feições