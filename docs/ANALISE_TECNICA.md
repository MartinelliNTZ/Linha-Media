# Análise Técnica - LinhaMestra

## Sumário Executivo

O plugin **LinhaMestra** é uma ferramenta QGIS especializada para processamento de linhas agrícolas,主要用于 manejo de lavouras de soja. O sistema implementa 6 algoritmos principais que trabalham em conjunto para gerar, numerar e manipular linhas mestras e perpendiculares.

## Estrutura de Diretórios

```
linhamestra/
├── __init__.py                    # Inicialização do plugin
├── LinhaMestra.py                 # Classe principal do plugin
├── LinhaMestra_provider.py        # Provider de algoritmos QGIS
├── metadata.txt                   # Metadados do plugin
├── pb_tool.cfg                    # Configuração do Plugin Builder
├── algorthms/                     # Algoritmos de processamento
│   ├── LinhaMestra_algorithm.py   # Algoritmo base de linha mestra
│   ├── LinhaMestra_numeracao_algorithm.py  # Numeração de linhas
│   ├── LinhaMestra_perpendicular_algorithm.py  # Gerador de perpendiculares
│   ├── LinhaMestra_massa_algorithm.py  # Processamento em massa
│   ├── LinhaMestra_extensao_algorithm.py  # Extensão/redução de linhas
│   └── LinhaMestra_corte_algorithm.py  # Corte de feições
└── core/                          # Módulos utilitários
    ├── vector_utils.py            # Utilitários vetoriais
    ├── geometry_utils.py          # Utilitários de geometria
    └── connection_judge.py        # Lógica de conectividade
```

## Análise Detalhada dos Componentes

### 1. LinhaMestra.py (Plugin Principal)

Este é o ponto de entrada do plugin QGIS. Implementa a classe `LinhaMestraPlugin` que:

- Inicializa o provider de algoritmos via `initProcessing()`
- Registra o provider no `QgsApplication.processingRegistry()`
- Remove o provider quando o plugin é descarregado via `unload()`

**Código relevante:**

```python
class LinhaMestraPlugin(object):
    def __init__(self):
        self.provider = None

    def initProcessing(self):
        """Init Processing provider for QGIS >= 3.8."""
        self.provider = LinhaMestraProvider()
        QingApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        QingApplication.processingRegistry().removeProvider(self.provider)
```

### 2. LinhaMestra_provider.py (Provider)

O provider é responsável por registrar todos os algoritmos no toolbox de processamento do QGIS. Ele:

- Herda de `QgsProcessingProvider`
- Implementa `loadAlgorithms()` para adicionar os 6 algoritmos
- Define ID, nome, ícone e nome longo do provider

**Algoritmos registrados:**

| Algoritmo | Classe | Função |
|-----------|--------|--------|
| LinhaMestra | LinhaMestraAlgorithm | Gera linha mestra básica |
| Numeração | LinhaMestraNumeracaoAlgorithm | Numera linhas de soja |
| Perpendicular | LinhaPerpendicularMediaAlgorithm | Gera perpendiculares |
| Massa | LinhaMestraMassaAlgorithm | Processamento em massa |
| Extensão | LinhaMestraExtensaoAlgorithm | Ajusta comprimento |
| Corte | LinhaMestraCorteAlgorithm | Corta feições |

### 3. Módulo Core - VectorUtils

O `VectorUtils` é o módulo mais importante do sistema, contendo ~600 linhas de código utilitário. Principais funções:

#### 3.1 Orientação de Linhas

```python
@staticmethod
def orient_northwest(geom):
    """Inverte a linha se o final for mais ao Norte/Oeste que o início."""
    # Critério NO: Menor X (Oeste), se empate, maior Y (Norte)
    def score_no(pt):
        return (pt.x(), -pt.y())
```

Esta função é crucial para garantir consistência na direção das linhas antes do processamento.

#### 3.2 Alinhamento de Pares

```python
@staticmethod
def align_line_pair(geom1, geom2):
    """
    Prepara o 'casamento' das linhas:
    1. Orienta a primeira para Noroeste.
    2. Orienta a segunda para que seu início seja o mais próximo possível do início da primeira.
    """
```

#### 3.3 Análise de Retidão

```python
@staticmethod
def analyze_straightness(geom, threshold):
    """Analisa se a linha é reta e retorna (is_straight, avg_az, max_dev)."""
```

Esta função é usada para classificar linhas como "RETA" ou "CURVA" no algoritmo de numeração.

#### 3.4 Geração de Elementos da Linha Mestra

```python
@staticmethod
def generate_linhamestra_elements(geom1, geom2, partitions, feedback=None):
    """
    Orquestra o fluxo completo de geração da linha mestra.
    Retorna (mestra, conexoes, perpendiculares, mais_proximo_1, mais_proximo_2).
    """
```

#### 3.5 Geração de Perpendiculares

```python
@staticmethod
def generate_perpendiculars_from_line_vertices(input_line_geom, ...):
    """
    Gera linhas perpendiculares em cada vértice de uma geometria de linha.
    A direção da perpendicular é a bissetriz do ângulo formado pelos segmentos adjacentes.
    """
```

### 4. Módulo Core - ConnectionJudge

Este módulo implementa a lógica de conectividade avançada, incluindo o tratamento de vértices órfãos.

#### 4.1 Geração de Conexões com Resolução de Órfãos

```python
@staticmethod
def generate_nearest_with_orphans(base_geom, target_geom, target_n, resolve_endpoints=True):
    """
    Gera conexões de menor distância garantindo que nenhum vértice da linha alvo fique órfão.
    Usa amostragem uniforme baseada em target_n para garantir densidade.
    """
```

**Lógica do Juiz:**
1. **Passo 1**: Conecta cada ponto da base ao ponto mais próximo no alvo
2. **Passo 2**: Identifica vértices órfãos (não alcançados)
3. **Passo 3**: Aplica lógica especial para órfãos:
   - Caso A: Órfãos no início - conecta ao primeiro ponto atingido
   - Caso B: Órfãos no fim - conecta ao último ponto atingido
   - Caso C: Órfãos no meio - conecta ao centroide dos vizinhos

#### 4.2 Decisão de Base por Critério

```python
@staticmethod
def solve_nearest_with_criteria(geom1, geom2, criteria_idx, target_n, resolve_endpoints=True):
    """
    Executa o julgamento para decidir qual linha será a base conforme o critério.
    """
```

**Critérios disponíveis:**
| Índice | Critério | Descrição |
|--------|----------|-----------|
| 0 | Ponto na Ponta -> Meio | Usa lógica de sincronismo |
| 1 | Menor Tamanho | Linha mais curta é base |
| 2 | Maior Tamanho | Linha mais longa é base |
| 3 | Menor Ângulo | Linha mais curva é base |
| 4 | Maior Ângulo | Linha mais reta é base |

### 5. Módulo Core - GeometryUtils

Módulo mais simples, focado na manipulação de geometrias.

```python
class VectorLayerGeometry:
    @staticmethod
    def adjust_line_length(geometry, delta):
        """
        Estende ou reduz uma linha em ambas as extremidades.
        delta > 0: Estende a linha para fora.
        delta < 0: Reduz a linha para dentro (trim).
        """
```

## Análise dos Algoritmos

### LinhaMestraAlgorithm

Algoritmo base que gera linha mestra a partir de duas camadas de linhas.

**Fluxo de processamento:**

1. **Entrada**: Duas camadas de linhas (opcionalmente combinadas em uma)
2. **Alinhamento**: Usa `VectorUtils.align_line_pair()` para orientar as linhas
3. **Particionamento**: Calcula número de partições dinâmico baseado nos vértices
4. **Geração**: Escolhe estilo de conexão e linha mestra
5. **Saída**: Linhas mestras e conexões

**Parâmetros principais:**

```python
PARTICOES = 'PARTICOES'           # Número de partições
ESTILO_CONEXAO = 'ESTILO_CONEXAO'  # Tipo de conexão
ESTILO_LINHA_MESTRA = 'ESTILO_LINHA_MESTRA'  # Tipo de linha mestra
CRITERIO_PROXIMIDADE = 'CRITERIO_PROXIMIDADE'  # Critério de escolha
RESOLVER_ORFAOS_PONTAS = 'RESOLVER_ORFAOS_PONTAS'  # Tratar órfãos
ESPACAMENTO = 'ESPACAMENTO'       # Espaçamento fixo
```

**Estilos de Conexão:**
- `0`: Proximidade - conecta ao ponto mais próximo
- `1`: Perpendicular - usa direção perpendicular
- `2`: Conexão Direta - ponto a ponto
- `3`: Espaçamento Fixo - 1:1 com distância fixa

**Estilos de Linha Mestra:**
- `0`: Interpolação (Ponto a Ponto)
- `1`: Proximidade (Média Espacial)
- `2`: Espaçamento Fixo (1:1)

### LinhaMestraNumeracaoAlgorithm

Algoritmo especializado para numeração de linhas de soja.

**Fluxo de processamento:**

1. **Etapa 1 - Classificação**:
   - Analisa cada linha usando `analyze_straightness()`
   - Classifica como "RETA" ou "CURVA"
   - Calcula azimute médio

2. **Etapa 1 - Juntar Segmentos**:
   - Identifica linhas retas com azimutes próximos
   - Une segmentos da mesma passada

3. **Etapa 2 - Dividir em Grupos**:
   - Agrupa passadas com azimutes similares
   - Identifica blocos direcionais (ex: Chapadão, Bicos)

4. **Etapa 2 - Numerar**:
   - Ordena linhas por projeção espacial
   - Atribui número sequencial dentro de cada grupo

**Fórmula de Projeção Espacial:**
```python
valor = -x * sin(azimute) + y * cos(azimute)
```

### LinhaPerpendicularMediaAlgorithm

Gera linhas perpendiculares em cada vértice da linha de entrada.

**Dois cenários de uso:**

1. **Com Linhas Mães**:
   - Recebe 2 linhas mães
   - Calcula intersecção das perpendiculares com as linhas mães
   - Gera perpendiculares que cortam ambas as linhas

2. **Sem Linhas Mães**:
   - Usa distância fixa
   - Gera perpendiculares com comprimento fixo

### LinhaMestraMassaAlgorithm

Versão avançada do algoritmo base que processa múltiplas feições.

**Características:**
- Suporta campo de ordenação
- Suporta campo de agrupamento
- Processa pares sequenciais
- Gera múltiplas saídas (linhas mestras + conexões)

### LinhaMestraExtensaoAlgorithm

Algoritmo simples para ajustar comprimento de linhas.

**Uso:**
- Valores positivos: estendem a linha
- Valores negativos: reduzem (trim) a linha

### LinhaMestraCorteAlgorithm

Algoritmo para dividir feições usando linhas como lâmina.

**Características:**
- Suporta polígonos e linhas como entrada
- Usa `splitGeometry()` do QGIS
- Preserva atributos das feições originais

## Fluxos de Uso Comuns

### Fluxo 1: Geração Básica de Linha Mestra

```
1. Carregar camada com 2 linhas
2. Executar LinhaMestraAlgorithm
3. Configurar partições (ex: 1000)
4. Escolher estilo de conexão
5. Escolher estilo de linha mestra
6. Gerar saída
```

### Fluxo 2: Numeração de Linhas de Soja

```
1. Carregar camada de linhas de soja
2. Executar LinhaMestraNumeracaoAlgorithm
3. Configurar desvio aceitável tipo (ex: 5°)
4. Configurar desvio aceitável sequência (ex: 2°)
5. Configurar tolerância GPS (ex: 0.5m)
6. Gerar saída com campos: grupo_id, seq_num, geomet_tp, azimuth
```

### Fluxo 3: Geração de Perpendiculares

```
1. Carregar camada de linhas
2. (Opcional) Carregar 2 linhas mães
3. Executar LinhaPerpendicularMediaAlgorithm
4. Se sem linhas mães, definir distância fixa
5. Gerar perpendiculares
```

### Fluxo 4: Processamento em Massa

```
1. Carregar camada com múltiplas linhas
2. Definir campo de ordenação (sequência)
3. (Opcional) Definir campo de agrupamento
4. Executar LinhaMestraMassaAlgorithm
5. Gerar linhas mestras + conexões
```

## Considerações Técnicas

### Tratamento de CRS

O sistema lida com diferentes CRS através de:
- Verificação de compatibilidade CRS
- Reprojeção automática quando necessário
- Uso de `QgsCoordinateTransform`

### Tratamento de Geometrias

- Suporte a LineString e MultiLineString
- Conversão automática de tipos
- Tratamento de geometrias vazias

### Performance

- Uso de `QgsFeatureSink.FastInsert` para inserção rápida
- Processamento em chunks quando aplicável
- Feedback de progresso para operações longas

### Limitações Conhecidas

1. Requer exatamente 2 feições para algoritmos de par
2. CRS deve ser consistente ou compatíveis
3. Linhas devem ter direção consistente (orient_northwest)

## Dependências

- QGIS 3.x (testado em 3.16+)
- PyQt5
- qgis.PyQt.QtCore
- qgis.core

## Conclusão

O plugin LinhaMestra é uma ferramenta especializada e bem arquitetada para processamento de linhas agrícolas. A separação entre algoritmos (camada de aplicação) e utilitários (camada de domínio) facilita manutenção e extensão. O módulo ConnectionJudge demonstra implementação sofisticada de lógica de conectividade com tratamento de casos edge (órfãos).