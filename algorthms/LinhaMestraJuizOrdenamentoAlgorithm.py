# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterEnum,
                       QgsWkbTypes,
                       QgsFeature,
                       QgsFields,
                       QgsField)


# ==============================================================================
# REGRAS CARDINAIS
#   N*S   → maior Y primeiro  (Norte vence Sul)
#   L*O   → menor X primeiro  (Oeste vence Leste)
#   NO*SE → menor X primeiro  (NO vence SE — componente X dominante)
#   SO*NE → maior Y primeiro  (NE vence SO — componente Y dominante)
#
# Eixo perpendicular de desempate:
#   N*S   → L*O  (Oeste vence)
#   L*O   → N*S  (Norte vence)
#   NO*SE → SO*NE (NE vence: maior Y)
#   SO*NE → NO*SE (NO vence: menor X)
# ==============================================================================

REGRAS = {
    'N*S':   {'pri': lambda cx, cy: -cy,  'sec': lambda cx, cy:  cx},
    'L*O':   {'pri': lambda cx, cy:  cx,  'sec': lambda cx, cy: -cy},
    'NO*SE': {'pri': lambda cx, cy:  cx,  'sec': lambda cx, cy: -cy},
    'SO*NE': {'pri': lambda cx, cy: -cy,  'sec': lambda cx, cy:  cx},
}

PERPENDICULAR = {
    'N*S':   'L*O',
    'L*O':   'N*S',
    'NO*SE': 'SO*NE',
    'SO*NE': 'NO*SE',
}


class LinhaMestraJuizOrdenamentoAlgorithm(QgsProcessingAlgorithm):
    """
    JUIZ DE ORDENAMENTO ESPACIAL
    ─────────────────────────────
    Responsabilidade única: receber as curvas classificadas e devolvê-las
    com o campo `ordem_espacial` preenchido.

    O juiz NÃO usa soma nem média. Ele constrói a distribuição espacial
    de cada curva a partir dos julgamentos individuais (lnPri / lnSec),
    usando posição ponderada pelo inverso do rank, e desempata pela
    regra cardinal do eixo escolhido.
    """

    INPUT        = 'INPUT'
    PRIMARY_AXIS = 'PRIMARY_AXIS'
    OUTPUT       = 'OUTPUT'

    AXIS_OPTIONS = ['N*S', 'L*O', 'NO*SE', 'SO*NE']

    def tr(self, s):
        return QCoreApplication.translate('LinhaMestraJuizOrdenamentoAlgorithm', s)

    def createInstance(self):
        return LinhaMestraJuizOrdenamentoAlgorithm()

    def name(self):
        return 'linhamestra_juiz_ordenamento'

    def displayName(self):
        return self.tr('Juiz de Ordenamento Espacial de Curvas')

    def group(self):
        return self.tr('Linha Mestra - Especial')

    def groupId(self):
        return 'linhamestra'

    def initAlgorithm(self, config):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            self.tr('Curvas Classificadas'),
            [QgsProcessing.TypeVectorLine]
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.PRIMARY_AXIS,
            self.tr('Eixo Primário'),
            options=self.AXIS_OPTIONS,
            defaultValue=0
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            self.tr('Curvas Ordenadas'),
            QgsProcessing.TypeVectorLine
        ))

    # ──────────────────────────────────────────────────────────────────
    # MÉTODOS INTERNOS DO JUIZ
    # ──────────────────────────────────────────────────────────────────

    def _detectar_ncols(self, source, prefixo):
        """Conta quantas colunas lnPriX ou lnSecX existem na camada."""
        nomes = [f.name() for f in source.fields()]
        i = 0
        while '%s%d' % (prefixo, i) in nomes:
            i += 1
        return i

    def _posicao_ponderada(self, feat, prefixo, n_cols):
        """
        Constrói a posição contínua da curva no eixo indicado.

        Regra:
          - Lê lnPriX (ou lnSecX) para i in 0..n_cols-1
          - Ignora índices com rank == 0  (curva não foi tocada ali)
          - Peso de cada índice = 1 / rank
            (rank 1 = posição mais extrema = mais peso)
          - Retorna (covered_indices, posicao_ponderada)
            Se nenhum índice foi tocado, retorna ([], None)
        """
        covered = []
        soma_peso = 0.0
        soma_idx  = 0.0

        for i in range(n_cols):
            nome = '%s%d' % (prefixo, i)
            try:
                val  = feat[nome]
                rank = int(val) if val not in (None, '', 'NULL') else 0
            except (KeyError, TypeError, ValueError):
                rank = 0

            if rank > 0:
                covered.append(i)
                peso       = 1.0 / rank
                soma_idx  += i * peso
                soma_peso += peso

        if not covered:
            return [], None

        return covered, soma_idx / soma_peso

    def _centroide(self, feat):
        """Retorna (cx, cy) do centroide da geometria."""
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return None, None
        pt = geom.centroid().asPoint()
        return pt.x(), pt.y()

    def _comprimento(self, feat):
        """Comprimento da linha pela geometria."""
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return 0.0
        return geom.length()

    def _construir_perfil(self, feat, n_pri, n_sec):
        """
        Monta o perfil espacial completo de uma curva.
        Retorna um dict com tudo que o juiz precisa para julgar.
        """
        pri_covered, pri_pos = self._posicao_ponderada(feat, 'lnPri', n_pri)
        sec_covered, sec_pos = self._posicao_ponderada(feat, 'lnSec', n_sec)
        cx, cy = self._centroide(feat)

        return {
            'fid':         feat.id(),
            'feat':        feat,
            # distribuição no eixo primário
            'pri_pos':     pri_pos,
            'pri_min':     min(pri_covered) if pri_covered else None,
            'pri_max':     max(pri_covered) if pri_covered else None,
            # distribuição no eixo secundário
            'sec_pos':     sec_pos,
            'sec_min':     min(sec_covered) if sec_covered else None,
            'sec_max':     max(sec_covered) if sec_covered else None,
            # geometria
            'cx':          cx,
            'cy':          cy,
            'comprimento': self._comprimento(feat),
            # resultado
            'ordem':       None,
        }

    def _chave_ordenamento(self, perfil, regra_pri, regra_sec):
        """
        Chave de ordenamento em quatro níveis de cascata:
          1. Posição no eixo primário  (regra cardinal primária)
          2. Posição no eixo secundário (regra cardinal secundária)
          3. Centroide X/Y pelo primário (fallback geométrico)
          4. Centroide X/Y pelo secundário (desempate final / fragmentos)
        """
        cx = perfil['cx'] or 0.0
        cy = perfil['cy'] or 0.0

        # nível 1: posição ponderada no primário
        if perfil['pri_pos'] is not None:
            k1 = regra_pri(perfil['pri_pos'], 0.0)
        else:
            k1 = regra_pri(cx, cy)

        # nível 2: posição ponderada no secundário
        if perfil['sec_pos'] is not None:
            k2 = regra_sec(perfil['sec_pos'], 0.0)
        else:
            k2 = regra_sec(cx, cy)

        # níveis 3 e 4: centroide geométrico real
        k3 = regra_pri(cx, cy)
        k4 = regra_sec(cx, cy)

        return (k1, k2, k3, k4)

    def _julgar(self, perfis, eixo_primario, feedback):
        """
        Atribui `ordem` a cada perfil.

        EPSILON = 0.5 unidades de índice de grid.
        Duas curvas com |pos_a - pos_b| < EPSILON no primário
        são consideradas empatadas → vai para o secundário.
        Empate em ambos → são fragmentos da mesma curva →
        desempate final pelo centroide geométrico real.
        """
        EPSILON = 0.5

        regras = REGRAS[eixo_primario]
        perp   = PERPENDICULAR[eixo_primario]

        # Funções de chave para cada nível
        # O eixo primário recebe a posição contínua como "cx" e cy=0
        # A regra lambda(cx,cy) está calibrada para isso
        def regra_pri_pos(pos):
            return regras['pri'](pos, 0.0)

        def regra_sec_pos(pos):
            return REGRAS[perp]['pri'](pos, 0.0)

        def regra_pri_geo(cx, cy):
            return regras['pri'](cx, cy)

        def regra_sec_geo(cx, cy):
            return REGRAS[perp]['pri'](cx, cy)

        def chave(p):
            cx = p['cx'] or 0.0
            cy = p['cy'] or 0.0

            k1 = regra_pri_pos(p['pri_pos']) if p['pri_pos'] is not None else regra_pri_geo(cx, cy)
            k2 = regra_sec_pos(p['sec_pos']) if p['sec_pos'] is not None else regra_sec_geo(cx, cy)
            k3 = regra_pri_geo(cx, cy)
            k4 = regra_sec_geo(cx, cy)
            return (k1, k2, k3, k4)

        perfis_ordenados = sorted(perfis, key=chave)

        # Atribui ordens com detecção de empate por EPSILON
        ordem_atual = 1
        chave_anterior = None

        for p in perfis_ordenados:
            c = chave(p)

            if chave_anterior is not None:
                # empate absoluto nos 4 níveis = fragmento → mesmo grupo
                # empate apenas nos dois primeiros → mesma faixa espacial → próxima ordem
                k1_diff = abs(c[0] - chave_anterior[0])
                k2_diff = abs(c[1] - chave_anterior[1])

                if k1_diff >= EPSILON or k2_diff >= EPSILON:
                    ordem_atual += 1

            p['ordem'] = ordem_atual
            chave_anterior = c

        # Segundo passe: dentro de grupos com mesma ordem (fragmentos),
        # re-ordena pelos níveis 3 e 4 (centroide geométrico) e atribui
        # números consecutivos distintos
        from itertools import groupby

        resultado_final = []
        contador = 1

        for _, grupo in groupby(sorted(perfis_ordenados, key=lambda p: p['ordem']),
                                key=lambda p: p['ordem']):
            membros = list(grupo)
            if len(membros) == 1:
                membros[0]['ordem'] = contador
                resultado_final.append(membros[0])
                contador += 1
            else:
                sub = sorted(membros, key=lambda p: (
                    regra_pri_geo(p['cx'] or 0.0, p['cy'] or 0.0),
                    regra_sec_geo(p['cx'] or 0.0, p['cy'] or 0.0)
                ))
                for p in sub:
                    p['ordem'] = contador
                    resultado_final.append(p)
                    fid_str  = str(p['fid'])
                    ord_str  = str(contador)
                    feedback.pushInfo('  [Fragmento] FID=%s -> Ordem=%s' % (fid_str, ord_str))
                    contador += 1

        return resultado_final

    # ──────────────────────────────────────────────────────────────────
    # PROCESSO PRINCIPAL
    # ──────────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        source       = self.parameterAsSource(parameters, self.INPUT, context)
        axis_idx     = self.parameterAsInt(parameters, self.PRIMARY_AXIS, context)
        eixo_primario = self.AXIS_OPTIONS[axis_idx]

        feedback.pushInfo('Eixo primario: %s' % eixo_primario)

        # Detecta dimensões do grid a partir da camada
        n_pri = self._detectar_ncols(source, 'lnPri')
        n_sec = self._detectar_ncols(source, 'lnSec')
        feedback.pushInfo('Grid: %d linhas primarias, %d linhas secundarias' % (n_pri, n_sec))

        # Carrega todas as features e monta perfis
        features  = list(source.getFeatures())
        perfis    = []
        orfaos    = []

        for feat in features:
            p = self._construir_perfil(feat, n_pri, n_sec)

            if p['pri_pos'] is None and p['sec_pos'] is None:
                # Curva sem nenhuma intersecção no grid → julga só por centroide
                orfaos.append(p)
                feedback.pushInfo('  [Orfao] FID=%s sem interseccoes no grid' % str(p['fid']))
            else:
                perfis.append(p)

        # Julgamento principal
        feedback.pushInfo('=== JULGAMENTO (%d curvas + %d orfas) ===' % (len(perfis), len(orfaos)))
        julgados = self._julgar(perfis, eixo_primario, feedback)

        # Órfãos ordenados por centroide puro, adicionados ao final
        regras = REGRAS[eixo_primario]
        perp   = PERPENDICULAR[eixo_primario]

        maior_ordem = max((p['ordem'] for p in julgados), default=0)
        orfaos_ord  = sorted(
            orfaos,
            key=lambda p: (
                regras['pri'](p['cx'] or 0.0, p['cy'] or 0.0),
                REGRAS[perp]['pri'](p['cx'] or 0.0, p['cy'] or 0.0)
            )
        )
        for p in orfaos_ord:
            maior_ordem += 1
            p['ordem'] = maior_ordem
            feedback.pushInfo('  [Orfao] FID=%s -> Ordem=%s' % (str(p['fid']), str(maior_ordem)))

        todos = julgados + orfaos_ord

        # Log resultado final
        feedback.pushInfo('=== RESULTADO FINAL ===')
        for p in sorted(todos, key=lambda x: x['ordem']):
            pri_str = ('%.2f' % p['pri_pos']) if p['pri_pos'] is not None else 'N/A'
            sec_str = ('%.2f' % p['sec_pos']) if p['sec_pos'] is not None else 'N/A'
            cx_str  = ('%.1f' % p['cx'])      if p['cx']      is not None else 'N/A'
            cy_str  = ('%.1f' % p['cy'])      if p['cy']      is not None else 'N/A'
            feedback.pushInfo(
                '  Ordem=%-3s FID=%-3s pri_pos=%-8s sec_pos=%-8s cx=%-12s cy=%s' % (
                    str(p['ordem']), str(p['fid']),
                    pri_str, sec_str, cx_str, cy_str
                )
            )

        # Schema de saída: copia campos da entrada + ordem_espacial
        skip = {'ordem_espacial'}
        output_fields   = QgsFields()
        indices_origem  = []

        for i, field in enumerate(source.fields()):
            if field.name() not in skip:
                output_fields.append(field)
                indices_origem.append(i)

        output_fields.append(QgsField('ordem_espacial', QVariant.Int))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            output_fields, QgsWkbTypes.LineString, source.sourceCrs()
        )

        # Escreve features com ordem atribuída
        perfil_por_fid = {p['fid']: p for p in todos}

        for feat in features:
            p     = perfil_por_fid.get(feat.id())
            out_f = QgsFeature(output_fields)
            out_f.setGeometry(feat.geometry())

            attrs = [feat.attribute(i) for i in indices_origem]
            attrs.append(p['ordem'] if p else None)
            out_f.setAttributes(attrs)
            sink.addFeature(out_f)

        return {self.OUTPUT: dest_id}