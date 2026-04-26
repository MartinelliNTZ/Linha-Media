# Diretrizes de Engenharia - Agente LinhaMestra

> **Papel**: Engenheiro Sênior de Software  
> **Objetivo**: Definir diretrizes para desenvolvimento, refatoração e extensão do plugin LinhaMestra

---

## 1. Princípios Fundamentais

### 1.1 O Que FAZER ✅

- **Clean Code**: Código limpo, legível e autoexplicativo
- **Single Responsibility**: Cada classe/função tem uma única responsabilidade
- **DRY (Don't Repeat Yourself)**: Extrair código repetido para abstrações reutilizáveis
- **Dependência Injetada**: Preferir composição sobre herança profunda
- **Testabilidade**: Código que pode ser testado isoladamente
- **Documentação**: Docstrings em todas as classes e funções públicas

### 1.2 O Que NÃO FAZER ❌

- **Não** criar classes monolíticas com múltiplas responsabilidades
- **Não** duplicar lógica de negócio entre algoritmos
- **Não** hardcodar valores que podem ser configuráveis
- **Não** misturar lógica de apresentação com lógica de domínio
- **Não** usar variáveis com nomes genéricos (`temp`, `data`, `aux`)
- **Não** comentar código complexo - refatorar para clareza

---

## 2. Arquitetura e Separação de Responsabilidades

### 2.1 Camadas Definidas

```
┌─────────────────────────────────────────────────────────┐
│                    ALGORITMOS                           │
│  (LinhaMestra_algorithm.py, etc.)                       │
│  - Definem parâmetros de entrada/saída                 │
│  - Orquestram fluxo de execução                        │
│  - Delegam lógica para módulos core                    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    CORE (Domínio)                       │
│  (vector_utils.py, connection_judge.py, etc.)           │
│  - Lógica de negócio pura                               │
│  - Sem dependência de QGIS Processing                  │
│  - Reutilizável entre algoritmos                       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 INFRAESTRUTURA                          │
│  (geometry_utils.py, etc.)                              │
│  - Operações de baixo nível                             │
│  - wrappers de API QGIS                                │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Responsabilidades por Módulo

| Módulo | Responsabilidade | O que deve conter |
|--------|-------------------|-------------------|
| `algorthms/*` | Orquestração | Definição de parâmetros, fluxo de execução, delegação |
| `core/vector_utils.py` | Geometria vetorial | Operações com linhas, alinhamento, análise |
| `core/connection_judge.py` | Conectividade | Lógica de conexão entre linhas |
| `core/geometry_utils.py` | Geometria genérica | Operações de ajuste, manipulação básica |

---

## 3. Regras de Clean Code

### 3.1 Nomenclatura

```python
# ❌ RUIM - Nomes genéricos
def process(data):
    temp = []
    for x in data:
        temp.append(x * 2)
    return temp

# ✅ BOM - Nomes descritivos
def calculate_line_distances(lines: list[QgsGeometry]) -> list[float]:
    """
    Calcula distâncias entre linhas consecutivas.
    
    Args:
        lines: Lista de geometrias de linhas a processar
        
    Returns:
        Lista de distâncias calculadas
    """
    distances = []
    for line in lines:
        distance = line.length()
        distances.append(distance)
    return distances
```

### 3.2 Funções Pequenas

```python
# ❌ RUIM - Função grande com múltiplas responsabilidades
def process_algorithm(self, parameters, context, feedback):
    # Validação
    source = self.parameterAsSource(...)
    if source is None:
        raise ...
    # Extração
    features = list(source.getFeatures())
    # Processamento
    for f in features:
        # 100 linhas de lógica...
    # Escrita
    sink = ...
    for r in results:
        sink.addFeature(r)
    return {...}

# ✅ BOM - Funções pequenas delegando para módulos core
def processAlgorithm(self, parameters, context, feedback):
    source = self._validate_and_get_source(parameters, context)
    features = self._extract_features(source)
    processed = self._process_features(features, feedback)
    return self._write_results(processed, parameters, context)
```

### 3.3 Type Hints

```python
# ✅ BOM - Usar type hints
from typing import Optional, list[dict]

def align_lines(
    geom1:QgisGeometry, 
    geom2:QgisGeometry, 
    target_partitions: int
) -> tuple[QgisGeometry, QgisGeometry]:
    """Alinha duas geometrias para processamento."""
    ...
```

---

## 4. Padrões de Código

### 4.1 Padrão para Algoritmos QGIS

```python
# filepath: algorthms/exemplo_algorithm.py
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    # ... outros imports necessários
)
from ..core.vector_utils import VectorUtils
from ..core.connection_judge import ConnectionJudge


class ExemploAlgorithm(QgsProcessingAlgorithm):
    """
    Algoritmo de exemplo demonstrando o padrão correto.
    
    Descrição breve do propósito do algoritmo.
    """
    
    # Constantes de parâmetros
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    
    def initAlgorithm(self, config=None):
        """Configura os parâmetros de entrada e saída."""
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Descrição do parâmetro'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Nome da saída'),
                QgsProcessing.TypeVectorLine
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Executa o processamento principal."""
        # 1. Validação e extração
        source = self._get_source(parameters, context)
        
        # 2. Processamento (delegar para core)
        results = self._process(source, feedback)
        
        # 3. Escrita
        return self._write_output(results, parameters, context)

    def _get_source(self, parameters, context):
        """Valida e retorna a fonte de dados."""
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )
        return source

    def _process(self, source, feedback):
        """Lógica de processamento específica."""
        results = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                break
            # Processamento...
            results.append(feature)
        return results

    def _write_output(self, results, parameters, context):
        """Escreve os resultados no sink de saída."""
        fields = source.fields()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, 
            fields, source.wkbType(), source.sourceCrs()
        )
        for result in results:
            sink.addFeature(result)
        return {self.OUTPUT: dest_id}

    # Métodos obrigatórios
    def name(self):
        return 'exemplo_algoritmo'

    def displayName(self):
        return self.tr('Nome de Exibição')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def createInstance(self):
        return ExemploAlgorithm()
```

### 4.2 Padrão para Módulos Core

```python
# filepath: core/exemplo_utils.py
from qgis.core import QgisGeometry, QgisPointXY
from typing import Optional


class GeometryHelper:
    """
    Helper para operações geométricas.
    
    Responsabilidade única: manipulação de geometrias lineares.
    """
    
    @staticmethod
    def calculate_centroid(geom: QgisGeometry) -> Optional[QgsPointXY]:
        """
        Calcula o centroide de uma geometria.
        
        Args:
            geom: Geometria para calcular centroide
            
        Returns:
            PontoXY do centroide ou None se inválida
        """
        if geom is None or geom.isEmpty():
            return None
        centroid = geom.centroid()
        if centroid.isEmpty():
            return None
        return centroid.asPoint()
    
    @staticmethod
    def get_equidistant_points(
        geom: QgisGeometry, 
        num_points: int
    ) -> list[QgsPointXY]:
        """
        Gera pontos uniformemente espaçados na geometria.
        """
        if geom.isEmpty() or num_points < 2:
            return []
            
        length = geom.length()
        points = []
        for i in range(num_points):
            distance = (length / (num_points - 1)) * i
            interpolated = geom.interpolate(distance)
            if not interpolated.isNull():
                pt = interpolated.asPoint()
                points.append(QgsPointXY(pt.x(), pt.y()))
        return points
```

---

## 5. Plano de Refatoração

### 5.1 Ações Imediatas

#### 5.1.1 Extrair Constantes Compartilhadas

**Problema**: Constantes duplicadas entre algoritmos
**Solução**: Criar módulo de constantes

```python
# filepath: core/constants.py
from enum import Enum


class ConnectionStyle(Enum):
    """Estilos de conexão entre linhas."""
    PROXIMITY = 0
    PERPENDICULAR = 1
    DIRECT = 2
    FIXED_SPACING = 3


class MasterLineStyle(Enum):
    """Estilos de geração da linha mestra."""
    INTERPOLATION = 0
    PROXIMITY = 1
    FIXED_SPACING = 2


class ProximityCriteria(Enum):
    """Critérios para escolha da linha base."""
    SYNCHRONISM = 0
    SMALLER_LENGTH = 1
    LARGER_LENGTH = 2
    SMALLER_ANGLE = 3
    LARGER_ANGLE = 4


# Constantes globais
DEFAULT_PARTITIONS = 1000
DEFAULT_SPACING = 1.0
DEFAULT_DISTANCE = 10.0
```

#### 5.1.2 Criar Factory de Parâmetros

**Problema**: Configuração de parâmetros repetida em cada algoritmo
**Solução**: Criar helper para definição de parâmetros

```python
# filepath: core/parameter_factory.py
from qgis.core import (
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessing,
)


class ParameterFactory:
    """Factory para criação padronizada de parâmetros."""
    
    @staticmethod
    def create_line_source_param(name, description, optional=False):
        return QgsProcessingParameterFeatureSource(
            name,
            description,
            [QgsProcessing.TypeVectorLine],
            optional=optional
        )
    
    @staticmethod
    def create_output_line_param(name, description):
        return QgsProcessingParameterFeatureSink(
            name,
            description,
            QgsProcessing.TypeVectorLine
        )
    
    @staticmethod
    def create_enum_param(name, description, options, default=0):
        return QgsProcessingParameterEnum(
            name,
            description,
            options=options,
            defaultValue=default
        )
    
    @staticmethod
    def create_number_param(
        name, description, 
        min_val=None, max_val=None, 
        default=None, is_integer=True
    ):
        param_type = (
            QgsProcessingParameterNumber.Integer 
            if is_integer 
            else QgsProcessingParameterNumber.Double
        )
        param = QgsProcessingParameterNumber(name, description, type=param_type)
        if min_val is not None:
            param.setMinimum(min_val)
        if max_val is not None:
            param.setMaximum(max_val)
        if default is not None:
            param.setDefaultValue(default)
        return param
```

#### 5.1.3 Extrair Lógica de Validação

**Problema**: Validação de entrada repetida
**Solução**: Criar módulo de validação

```python
# filepath: core/validators.py
from qgis.core import QgsProcessingException


class InputValidator:
    """Validador de entradas para algoritmos."""
    
    @staticmethod
    def validate_two_features(source, source2=None, context=None):
        """
        Valida seleção de 2 feições.
        
        Returns:
            tuple: (feat1, feat2, crs)
            
        Raises:
            QgisProcessingException: Se validação falhar
        """
        from ..core.vector_utils import VectorUtils
        
        features = list(source.getFeatures())
        
        if source2 is None:
            if len(features) != 2:
                raise QgisProcessingException(
                    'Selecione exatamente 2 feições'
                )
            return features[0], features[1], source.sourceCrs()
        
        features2 = list(source2.getFeatures())
        if len(features) != 1 or len(features2) != 1:
            raise QgisProcessingException(
                'Selecione 1 feição em cada camada'
            )
        
        feat1, feat2 = features[0], features2[0]
        if source.sourceCrs() != source2.sourceCrs():
            # Reprojetar se necessário
            pass
            
        return feat1, feat2, source.sourceCrs()
```

### 5.2 Ações de Médio Prazo

#### 5.2.1 Refatorar Provider

**Objetivo**: Provider mais limpo e delegação de responsabilidades

```python
# filepath: LinhaMestra_provider.py (refatorado)
from qgis.core import QgsProcessingProvider
from .algorthms import (
    LinhaMestraAlgorithm,
    LinhaMestraNumeracaoAlgorithm,
    # ...
)


class LinhaMestraProvider(QgsProcessingProvider):
    """Provider do plugin LinhaMestra."""
    
    # Mapeamento de algoritmos
    _ALGORITHMS = {
        'linhamestra': LinhaMestraAlgorithm,
        'linhamestra_numeracao': LinhaMestraNumeracaoAlgorithm,
        # ...
    }
    
    def loadAlgorithms(self):
        """Carrega todos os algoritmos registrados."""
        for algo_class in self._ALGORITHMS.values():
            self.addAlgorithm(algo_class())
    
    # ... métodos restantes
```

#### 5.2.2 Criar Classe Base para Algoritmos

```python
# filepath: core/base_algorithm.py
from qgis.core import QgsProcessingAlgorithm
from qgis.PyQt.QtCore import QCoreApplication


class BaseLinhaMestraAlgorithm(QgsProcessingAlgorithm):
    """Classe base para algoritmos LinhaMestra."""
    
    GROUP = 'Linha Mestra'
    GROUP_ID = 'linhamestra'
    
    def group(self):
        return self.tr(self.GROUP)
    
    def groupId(self):
        return self.GROUP_ID
    
    def _validate_source(self, parameters, param_name, context):
        """Valida fonte de dados."""
        source = self.parameterAsSource(parameters, param_name, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, param_name)
            )
        return source
    
    def _create_standard_fields(self, *field_names):
        """Cria campos padrão para saída."""
        from qgis.core import QgsFields, QgsField, QVariant
        fields = QgsFields()
        for name in field_names:
            fields.append(QgsField(name, QVariant.String))
        return fields
```

---

## 6. Regras para o Agente

### 6.1 Antes de Escrever Código

1. **Analisar o contexto**: Ler arquivos relacionados antes de modificar
2. **Identificar padrões**: Verificar se existe função similar já implementada
3. **Verificar duplicação**: Não criar código que já existe em utils
4. **Planejar ação**: Definir steps antes de executar

### 6.2 Durante a Implementação

1. **Usar nomes descritivos**: `calculate_line_centroid` não `calc`
2. **Adicionar docstrings**: Explicar propósito, args e return
3. **Tratar edge cases**: Geometrias vazias, None, CRS diferentes
4. **Usar type hints**: Especialmente em funções públicas
5. **Manter funções pequenas**: Máximo 30-40 linhas por função

### 6.3 Após Implementar

1. **Verificar sintaxe**: Ignorar erros de import QGIS
2. **Revisar nomenclatura**: Seguir convenções do projeto
3. **Testar mentalmente**: Executar fluxo na cabeça
4. **Documentar**: Atualizar AGENT_CONTEXT.md se necessário

### 6.4 Estrutura de Commits

```
feat: adiciona novo algoritmo de extensão
fix: corrige problema de CRS em perpendicular
refactor: extrai validação para InputValidator
docs: atualiza contexto do agente
```

---

## 7. Checklist de Revisão

Antes de finalizar qualquer alteração:

- [ ] Código segue Clean Code?
- [ ] Função tem responsabilidade única?
- [ ] Não há duplicação de código?
- [ ] Nomes são descritivos?
- [ ] Docstrings presentes?
- [ ] Type hints onde aplicável?
- [ ] Edge cases tratados?
- [ ] Conflitos de dependência resolvidos?
- [ ] Contexto do agente atualizado?

---

## 8. Referências

- [Clean Code](https://www.google.com/search?q=clean+code+robert+martin) - Robert C. Martin
- [QGIS Processing Framework](https://qgis.org/py-docs/)
- [PEP 8 - Style Guide](https://www.python.org/dev/peps/pep-0008/)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)