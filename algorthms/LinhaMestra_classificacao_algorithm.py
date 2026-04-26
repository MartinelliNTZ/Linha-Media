# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterDefinition,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterBoolean,
                       QgsWkbTypes,
                       QgsGeometry,
                       QgsFeature,
                       QgsFields,
                       QgsPointXY,
                       QgsField,
                       QgsSpatialIndex)
import math
from ..core.vector_utils import VectorUtils
from ..core.JuizOrdenamento import JuizOrdenamento


class LinhaMestraClassificacaoAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT_LINES = 'OUTPUT_LINES'
    OUTPUT_AXES = 'OUTPUT_AXES'
    OUTPUT_CLASSIFIERS = 'OUTPUT_CLASSIFIERS'
    THRESHOLD = 'THRESHOLD'
    AXIS_MODE = 'AXIS_MODE'
    JUDGE_METHOD = 'JUDGE_METHOD'
    N_LINES = 'N_LINES'
    USE_SECONDARY = 'USE_SECONDARY'
    PERP_LENGTH = 'PERP_LENGTH'
    OUTPUT_PERP_SENSORS = 'OUTPUT_PERP_SENSORS'

    def tr(self, string):
        return QCoreApplication.translate('LinhaMestraClassificacaoAlgorithm', string)

    def createInstance(self):
        return LinhaMestraClassificacaoAlgorithm()

    def name(self):
        return 'linhamestra_classificacao'

    def displayName(self):
        return self.tr('Classificador e Numerador de Curvas')

    def group(self):
        return self.tr('Linha Mestra - Especial')

    def groupId(self):
        return 'linhamestra'

    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Camada de Curvas de Nível'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.THRESHOLD,
                self.tr('Tolerância para Retas (Graus)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LINES,
                self.tr('Curvas Classificadas'),
                QgsProcessing.TypeVectorLine
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.AXIS_MODE,
                self.tr('Modo de Geração de Eixos'),
                options=['Ponto a Ponto (Morfologia Real)', 'Eixos Fixos (Grid Ortogonal)'],
                defaultValue=1
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.JUDGE_METHOD,
                self.tr('Método de Julgamento (Juiz)'),
                options=['Arbitrário (Espacial)', 'Borda Count Adaptado (Consenso)', 'Grafo de Precedência (Pairwise)', 'Consenso por Posição Relativa (Normalizado)'],
                defaultValue=3
            )
        )
        param_n_lines = QgsProcessingParameterNumber(
            self.N_LINES,
            self.tr('Número de Linhas do Grid (Resolução)'),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=50,
            minValue=5,
            maxValue=100
        )
        param_n_lines.setFlags(QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param_n_lines)
        param_use_sec = QgsProcessingParameterBoolean(
            self.USE_SECONDARY,
            self.tr('Usar Grid Secundário (Perpendicular) no Julgamento'),
            defaultValue=False
        )
        param_use_sec.setFlags(QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param_use_sec)

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PERP_LENGTH,
                self.tr('Comprimento do Sensor Perpendicular (Total)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=400.0,
                minValue=1.0
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_PERP_SENSORS,
                self.tr('Sensores Perpendiculares (Broken)'),
                QgsProcessing.TypeVectorLine
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_AXES,
                self.tr('Eixos Cardeais'),
                QgsProcessing.TypeVectorLine
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_CLASSIFIERS,
                self.tr('Linhas Classificadoras (Grid)'),
                QgsProcessing.TypeVectorLine
            )
        )

    # ------------------------------------------------------------------
    # HELPERS GEOMÉTRICOS
    # ------------------------------------------------------------------

    def _line_direction_vector(self, p1, p2):
        """Retorna o vetor unitário de p1→p2."""
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length == 0:
            return 0.0, 0.0
        return dx / length, dy / length

    def _perpendicular_unit(self, ux, uy):
        """Vetor perpendicular ao unitário (ux, uy)."""
        return -uy, ux

    def _extend_line_to_bbox(self, cx, cy, ux, uy, bbox_half_diag):
        """
        Dado um ponto central (cx,cy) e direção unitária (ux,uy),
        cria um segmento longo o suficiente para sair do bbox.
        """
        big = bbox_half_diag * 2.0
        p1 = QgsPointXY(cx + ux * big, cy + uy * big)
        p2 = QgsPointXY(cx - ux * big, cy - uy * big)
        return p1, p2

    def _clip_line_to_points(self, center, direction_ux, direction_uy,
                             limit_positive, limit_negative):
        """
        Constrói um eixo que passa em `center` com direção (ux,uy),
        mas cujas pontas são os limites reais dos pontos extremos projetados.

        limit_positive: ponto extremo no sentido positivo do vetor
        limit_negative: ponto extremo no sentido negativo do vetor

        Projeção escalar de cada limite sobre o eixo → comprimento real.
        """
        def proj(pt):
            return ((pt.x() - center.x()) * direction_ux +
                    (pt.y() - center.y()) * direction_uy)

        d_pos = proj(limit_positive)
        d_neg = proj(limit_negative)

        # garante orientação
        if d_pos < d_neg:
            d_pos, d_neg = d_neg, d_pos

        p_pos = QgsPointXY(center.x() + direction_ux * d_pos,
                           center.y() + direction_uy * d_pos)
        p_neg = QgsPointXY(center.x() + direction_ux * d_neg,
                           center.y() + direction_uy * d_neg)
        return p_pos, p_neg

    def _project_all_features_onto_axis(self, features, center, ux, uy):
        """
        Projeta todos os vértices de todas as features sobre o eixo
        e retorna (min_proj, max_proj) — extensão real das curvas nessa direção.
        """
        min_p = float('inf')
        max_p = float('-inf')
        for feat in features:
            geom = feat.geometry()
            for part in geom.asGeometryCollection() or [geom]:
                for pt in part.asPolyline() if not part.isMultipart() else [v for pl in part.asMultiPolyline() for v in pl]:
                    d = (pt.x() - center.x()) * ux + (pt.y() - center.y()) * uy
                    min_p = min(min_p, d)
                    max_p = max(max_p, d)
        return min_p, max_p

    # ------------------------------------------------------------------
    # GRID INTELIGENTE
    # ------------------------------------------------------------------

    def _build_smart_grid(self, features, center, sweep_ux, sweep_uy,
                          line_ux, line_uy, n_lines, bbox_half_diag):
        """
        Cria um grid de `n_lines` linhas paralelas à direção (line_ux, line_uy).

        Estratégia:
        1. Projeta todas as curvas no eixo perpendicular (sweep) para saber
           o intervalo real ocupado pelas curvas.
        2. Divide esse intervalo em (n_lines - 1) espaços iguais.
        3. Mantém o número fixo de linhas para garantir integridade do schema.

        Retorna lista de (offset_id, [QgsPointXY, QgsPointXY]).
        """
        min_proj, max_proj = self._project_all_features_onto_axis(
            features, center, sweep_ux, sweep_uy
        )

        if min_proj == float('inf'):
            # Erro Silencioso identificado: se não houver vértices válidos, o grid falha.
            return []

        total_span = max_proj - min_proj
        
        # Prevenção de divisão por zero se todas as curvas estiverem alinhadas perfeitamente
        if total_span <= 0:
            total_span = 0.001 
            
        step = total_span / (n_lines - 1) if n_lines > 1 else 0.0

        grid_lines = []
        for i in range(n_lines):
            offset_dist = min_proj + i * step
            lx = center.x() + sweep_ux * offset_dist
            ly = center.y() + sweep_uy * offset_dist
            p1 = QgsPointXY(lx + line_ux * bbox_half_diag * 2,
                            ly + line_uy * bbox_half_diag * 2)
            p2 = QgsPointXY(lx - line_ux * bbox_half_diag * 2,
                            ly - line_uy * bbox_half_diag * 2)
            grid_lines.append((i - n_lines // 2, [p1, p2]))

        # Retornamos todas as linhas. Se não houver hit, o rank será 0, 
        # mas o atributo lnPri/lnSec continuará existindo na tabela.
        return grid_lines

    # ------------------------------------------------------------------
    # PROCESSO PRINCIPAL
    # ------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        axis_mode = self.parameterAsInt(parameters, self.AXIS_MODE, context)
        judge_method = self.parameterAsInt(parameters, self.JUDGE_METHOD, context)
        n_lines_param = self.parameterAsInt(parameters, self.N_LINES, context)
        use_secondary_grid = self.parameterAsBool(parameters, self.USE_SECONDARY, context)
        perp_len = self.parameterAsDouble(parameters, self.PERP_LENGTH, context)
        features = list(source.getFeatures())

        extent = source.sourceExtent()
        cx = extent.center().x()
        cy = extent.center().y()
        center = QgsPointXY(cx, cy)

        # diagonal do bbox → comprimento seguro para extensões
        bbox_half_diag = math.hypot(extent.width(), extent.height())

        # ----------------------------------------------------------------
        # 1. PONTOS EXTREMOS REAIS DAS CURVAS
        # ----------------------------------------------------------------
        real_pts = VectorUtils.get_8_cardinal_points([f.geometry() for f in features])
        # real_pts: {'N', 'S', 'L', 'O', 'NE', 'NO', 'SE', 'SO'}

        # ----------------------------------------------------------------
        # 2. DEFINIÇÃO DOS 4 EIXOS CARDEAIS
        #
        # Regra: O eixo PASSA pelo centro da layer (cx, cy).
        #        As PONTAS chegam até os pontos extremos reais da camada.
        #        Isso preserva a ortogonalidade no modo Fixo e a morfologia
        #        real no modo Ponto a Ponto.
        # ----------------------------------------------------------------

        if axis_mode == 1:  # Eixos Fixos (Grid Ortogonal)
            # Direções cardinais puras (unitários fixos)
            axes_def = [
                ('N*S',   QgsPointXY(0,  1),  real_pts['N'],  real_pts['S']),
                ('L*O',   QgsPointXY(1,  0),  real_pts['L'],  real_pts['O']),
                ('NO*SE', QgsPointXY(1, -1),  real_pts['SE'], real_pts['NO']),
                ('SO*NE', QgsPointXY(1,  1),  real_pts['NE'], real_pts['SO']),
            ]
        else:  # Ponto a Ponto (Morfologia Real)
            def unit_vec(pa, pb):
                dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
                length = math.hypot(dx, dy)
                return QgsPointXY(dx / length, dy / length) if length else QgsPointXY(0, 1)

            axes_def = [
                ('N*S',   unit_vec(real_pts['S'], real_pts['N']),  real_pts['N'],  real_pts['S']),
                ('L*O',   unit_vec(real_pts['O'], real_pts['L']),  real_pts['L'],  real_pts['O']),
                ('NO*SE', unit_vec(real_pts['NO'], real_pts['SE']), real_pts['SE'], real_pts['NO']),
                ('SO*NE', unit_vec(real_pts['SO'], real_pts['NE']), real_pts['NE'], real_pts['SO']),
            ]

        # Construção dos segmentos de eixo:
        # passa pelo centro, ponta positiva = limite real, ponta negativa = limite real oposto
        axis_segments = []
        for name, uv, lim_pos, lim_neg in axes_def:
            ux, uy = uv.x(), uv.y()
            # normaliza (para modo fixo já é unitário, mas garante)
            mag = math.hypot(ux, uy)
            if mag > 0:
                ux, uy = ux / mag, uy / mag

            p_pos, p_neg = self._clip_line_to_points(
                center, ux, uy, lim_pos, lim_neg
            )
            length = p_pos.distance(p_neg)
            axis_segments.append({
                'name': name,
                'pts': [p_pos, p_neg],
                'ux': ux, 'uy': uy,
                'len': length
            })

        # ----------------------------------------------------------------
        # OUTPUT 1: Eixos Cardeais
        # ----------------------------------------------------------------
        fields_axes = source.fields()
        fields_axes.append(QgsField('Name', QVariant.String))
        fields_axes.append(QgsField('Length', QVariant.Double))
        (sink_axes, dest_axes) = self.parameterAsSink(
            parameters, self.OUTPUT_AXES, context,
            fields_axes, QgsWkbTypes.LineString, source.sourceCrs()
        )

        for ax in axis_segments:
            f = QgsFeature(fields_axes)
            f.setGeometry(QgsGeometry.fromPolylineXY(ax['pts']))
            f.setAttributes([None] * len(source.fields()) + [ax['name'], ax['len']])
            sink_axes.addFeature(f)

        # ----------------------------------------------------------------
        # 3. DETERMINAÇÃO DO EIXO PRIMÁRIO E SECUNDÁRIO
        #
        # O par é sempre ortogonal entre si:
        #   Par Cardinal:  N*S  <→>  L*O
        #   Par Diagonal: NO*SE <→> SO*NE
        # O eixo MAIS LONGO do par dominante é o PRIMÁRIO.
        # ----------------------------------------------------------------
        pairs = [
            ['N*S', 'L*O'],
            ['NO*SE', 'SO*NE'],
        ]

        # Encontra o par cuja soma de comprimentos é maior (par dominante)
        ax_by_name = {ax['name']: ax for ax in axis_segments}
        best_pair = max(pairs, key=lambda p: (
            ax_by_name[p[0]]['len'] + ax_by_name[p[1]]['len']
        ))

        primary   = max((ax_by_name[n] for n in best_pair), key=lambda a: a['len'])
        secondary = next(ax_by_name[n] for n in best_pair if n != primary['name'])

        feedback.pushInfo(f"Eixo Primário  : {primary['name']} ({primary['len']:.2f})")
        feedback.pushInfo(f"Eixo Secundário: {secondary['name']} ({secondary['len']:.2f})")

        # ----------------------------------------------------------------
        # 4. GRID INTELIGENTE
        #
        # Grid PRIMÁRIO (lnPri):
        #   - Linhas paralelas ao EIXO PRIMÁRIO
        #   - Varredura na direção do EIXO SECUNDÁRIO (perpendicular)
        #   - Espaçamento = extensão real das curvas no eixo secundário / (N-1)
        #
        # Grid SECUNDÁRIO (lnSec):
        #   - Linhas paralelas ao EIXO SECUNDÁRIO
        #   - Varredura na direção do EIXO PRIMÁRIO
        #   - Espaçamento = extensão real das curvas no eixo primário / (N-1)
        # ----------------------------------------------------------------
        # Vetores unitários
        pri_ux, pri_uy = primary['ux'], primary['uy']
        sec_ux, sec_uy = secondary['ux'], secondary['uy']

        if primary['len'] <= 0 or secondary['len'] <= 0:
            raise QgsProcessingException(
                self.tr("Erro no cálculo dos eixos: um dos eixos possui comprimento zero. Verifique as geometrias.")
            )

        # Grid PRIMÁRIO: linhas na direção do primário, varrendo na direção do secundário
        grid_primary = self._build_smart_grid(
            features, center,
            sweep_ux=sec_ux, sweep_uy=sec_uy,   # desloca nesta direção
            line_ux=pri_ux,  line_uy=pri_uy,    # linha tem esta direção
            n_lines=n_lines_param,
            bbox_half_diag=bbox_half_diag
        )

        # Grid SECUNDÁRIO: linhas na direção do secundário, varrendo na direção do primário
        grid_secondary = []
        if use_secondary_grid:
            grid_secondary = self._build_smart_grid(
                features, center,
                sweep_ux=pri_ux, sweep_uy=pri_uy,
                line_ux=sec_ux,  line_uy=sec_uy,
                n_lines=n_lines_param,
                bbox_half_diag=bbox_half_diag
            )

        if len(grid_primary) < n_lines_param or (use_secondary_grid and len(grid_secondary) < n_lines_param):
            feedback.reportError(
                self.tr(f"Aviso: Grid incompleto. Esperado {n_lines_param}, gerado Pri:{len(grid_primary)} Sec:{len(grid_secondary) if use_secondary_grid else 'N/A'}")
            )

        # ----------------------------------------------------------------
        # OUTPUT 2: Linhas do Grid (Classificadores)
        # ----------------------------------------------------------------
        fields_class = source.fields()
        fields_class.append(QgsField('offset_id', QVariant.Int))
        fields_class.append(QgsField('grid_type', QVariant.String))
        (sink_class, dest_class) = self.parameterAsSink(
            parameters, self.OUTPUT_CLASSIFIERS, context,
            fields_class, QgsWkbTypes.LineString, source.sourceCrs()
        )

        primary_offsets   = []
        secondary_offsets = []

        for offset_id, pts in grid_primary:
            primary_offsets.append(pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(pts))
            f.setAttributes([None] * len(source.fields()) + [offset_id, 'PRIMARY'])
            sink_class.addFeature(f)

        for offset_id, pts in grid_secondary:
            secondary_offsets.append(pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(pts))
            f.setAttributes([None] * len(source.fields()) + [offset_id, 'SECONDARY'])
            sink_class.addFeature(f)

        # ----------------------------------------------------------------
        # 5. ESCANEAMENTO E CLASSIFICAÇÃO DAS CURVAS
        # ----------------------------------------------------------------

        def get_scan_start_pt(line_pts, axis_name):
            """Define o ponto zero da régua de escaneamento (regra cardinal)."""
            if axis_name == 'N*S':
                return max(line_pts, key=lambda p: p.y())       # Norte
            if axis_name == 'L*O':
                return min(line_pts, key=lambda p: p.x())       # Oeste
            if axis_name == 'NO*SE':
                return min(line_pts, key=lambda p: p.x() - p.y())  # Noroeste
            if axis_name == 'SO*NE':
                return max(line_pts, key=lambda p: p.x() + p.y())  # Nordeste
            return line_pts[0]

        n_pri = len(primary_offsets)
        n_sec = len(secondary_offsets)

        results_l = {f.id(): {i: 0 for i in range(n_pri)} for f in features}
        results_p = {f.id(): {i: 0 for i in range(n_sec)} for f in features}

        # Varredura pelo Grid Primário (lnPri)
        for c_idx, c_line in enumerate(primary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, primary['name'])
            hits = []
            for feat in features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    impact_pt = VectorUtils._get_closest_point(inter, start_pt)
                    if impact_pt:
                        hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_l[fid][c_idx] = rank

        # Varredura pelo Grid Secundário (lnSec)
        for c_idx, c_line in enumerate(secondary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, secondary['name'])
            hits = []
            for feat in features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    impact_pt = VectorUtils._get_closest_point(inter, start_pt)
                    if impact_pt:
                        hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_p[fid][c_idx] = rank

        # ----------------------------------------------------------------
        # OUTPUT 3: Curvas Classificadas
        # ----------------------------------------------------------------

        # 1. Definir Schema INTERNO (para o Juiz trabalhar)
        skip_names = ['id', 'tipo_line', 'soma_pri', 'media_pri', 'soma_sec', 'media_sec', 'ordem_espacial']
        skip_names += [f'lnPri{i}' for i in range(101)] # Limpa até 100 para segurança
        skip_names += [f'lnSec{i}' for i in range(101)]

        internal_fields = QgsFields()
        indices_originais = []
        for i, field in enumerate(source.fields()):
            if field.name() not in skip_names:
                internal_fields.append(field)
                indices_originais.append(i)

        # Adicionamos os campos temporários necessários para o processamento
        fields_processing = QgsFields(internal_fields)
        fields_processing.append(QgsField('tipo_line', QVariant.String))
        for i in range(n_pri):
            fields_processing.append(QgsField(f'lnPri{i}', QVariant.Int))
        for i in range(n_sec):
            fields_processing.append(QgsField(f'lnSec{i}', QVariant.Int))
        fields_processing.append(QgsField('soma_pri',  QVariant.Double))
        fields_processing.append(QgsField('media_pri', QVariant.Double))
        fields_processing.append(QgsField('soma_sec',  QVariant.Double))
        fields_processing.append(QgsField('media_sec', QVariant.Double))
        fields_processing.append(QgsField('ordem_espacial', QVariant.Int))

        # 2. Definir Schema FINAL (O que o usuário verá)
        fields_final = QgsFields(internal_fields)
        fields_final.append(QgsField('id', QVariant.LongLong))
        fields_final.append(QgsField('tipo_line', QVariant.String))
        fields_final.append(QgsField('ordem_espacial', QVariant.Int))

        (sink_lines, dest_lines) = self.parameterAsSink(
            parameters, self.OUTPUT_LINES, context,
            fields_final, QgsWkbTypes.LineString, source.sourceCrs()
        )

        prepared_features = []
        for feat in features:
            tipo, _, _ = VectorUtils.classify_line_morphology(feat.geometry(), threshold)

            notas_l = [results_l[feat.id()][i] for i in range(n_pri)]
            notas_p = [results_p[feat.id()][i] for i in range(n_sec)]

            soma_l   = sum(notas_l)
            hits_l   = sum(1 for n in notas_l if n > 0)
            media_pri = soma_l / hits_l if hits_l > 0 else 0.0

            soma_p   = sum(notas_p)
            hits_p   = sum(1 for n in notas_p if n > 0)
            media_sec = soma_p / hits_p if hits_p > 0 else 0.0

            out_f = QgsFeature(fields_processing)
            out_f.setGeometry(feat.geometry())
            
            # Garante que o ID da feição seja preservado para o Juiz e Sensores
            out_f.setId(feat.id())

            new_attrs = [feat.attribute(idx) for idx in indices_originais]
            new_attrs.append(tipo)
            new_attrs.extend(notas_l)
            new_attrs.extend(notas_p)
            new_attrs.extend([soma_l, media_pri, soma_p, media_sec])
            new_attrs.append(None)  # Placeholder para ordem_espacial

            out_f.setAttributes(new_attrs)
            prepared_features.append(out_f)

        # ----------------------------------------------------------------
        # 6. JULGAMENTO PELO JUIZ DE ORDENAMENTO
        # ----------------------------------------------------------------
        juiz = JuizOrdenamento(primary['name'], use_secondary_grid)
        ordenados = juiz.julgar(prepared_features, judge_method)

        for out_f, ordem in ordenados:
            if feedback.isCanceled(): break
            
            # Criar feição final com schema limpo
            final_feat = QgsFeature(fields_final)
            final_feat.setGeometry(out_f.geometry())
            
            # Coletar apenas atributos originais + tipo_line + ordem_espacial
            final_attrs = [out_f.attribute(internal_fields.at(i).name()) for i in range(len(internal_fields))]
            final_attrs.append(out_f.id()) # Novo campo ID limpo e sincronizado
            final_attrs.append(out_f.attribute('tipo_line'))
            final_attrs.append(ordem)
            
            final_feat.setAttributes(final_attrs)
            sink_lines.addFeature(final_feat)

        # ----------------------------------------------------------------
        # 7. GERAÇÃO DE SENSORES PERPENDICULARES (Broken & Clipped)
        # ----------------------------------------------------------------
        fields_perp = QgsFields()
        fields_perp.append(QgsField('parent_id', QVariant.LongLong))
        fields_perp.append(QgsField('vertex_id', QVariant.Int))
        fields_perp.append(QgsField('azimuth', QVariant.Double))
        fields_perp.append(QgsField('touch_id', QVariant.LongLong))
        fields_perp.append(QgsField('side', QVariant.String))

        (sink_perp, dest_perp) = self.parameterAsSink(
            parameters, self.OUTPUT_PERP_SENSORS, context,
            fields_perp, QgsWkbTypes.LineString, source.sourceCrs()
        )

        spatial_index = QgsSpatialIndex(source.getFeatures())
        feat_dict = {f.id(): f for f in source.getFeatures()}

        def get_cardinal(az):
            az = az % 360
            if 337.5 <= az or az < 22.5: return 'N'
            if 22.5 <= az < 67.5: return 'NE'
            if 67.5 <= az < 112.5: return 'L'
            if 112.5 <= az < 157.5: return 'SE'
            if 157.5 <= az < 202.5: return 'S'
            if 202.5 <= az < 247.5: return 'SO'
            if 247.5 <= az < 292.5: return 'O'
            if 292.5 <= az < 337.5: return 'NO'
            return ''

        max_ray = perp_len / 2.0

        for f in features:
            if feedback.isCanceled(): break
            geom = f.geometry()
            polyline = list(geom.vertices())
            
            for v_idx, v in enumerate(polyline):
                p_start = QgsPointXY(v.x(), v.y())
                az_local = VectorUtils.get_vertex_azimuth(polyline, v_idx)
                
                # Duas direções perpendiculares (90 graus para cada lado)
                dirs = [(az_local + 90) % 360, (az_local - 90) % 360]
                
                for az_ray in dirs:
                    rad = math.radians(az_ray)
                    p_end_raw = QgsPointXY(p_start.x() + max_ray * math.sin(rad),
                                          p_start.y() + max_ray * math.cos(rad))
                    
                    ray_geom = QgsGeometry.fromPolylineXY([p_start, p_end_raw])
                    candidates = spatial_index.intersects(ray_geom.boundingBox())
                    
                    closest_dist = float('inf')
                    touch_id = -1
                    final_p_end = p_end_raw
                    
                    for c_id in candidates:
                        if c_id == f.id(): continue # Ignora a própria linha
                        
                        inter = ray_geom.intersection(feat_dict[c_id].geometry())
                        if not inter.isEmpty():
                            impact_pt = VectorUtils._get_closest_point(inter, p_start)
                            if impact_pt:
                                d = p_start.distance(impact_pt)
                                # Margem para evitar auto-intersecção em vértices compartilhados
                                if d > 0.001 and d < closest_dist:
                                    closest_dist = d
                                    touch_id = c_id
                                    final_p_end = impact_pt
                    
                    # Criar feição do sensor (segmento da origem até o impacto ou limite)
                    feat_perp = QgsFeature(fields_perp)
                    feat_perp.setGeometry(QgsGeometry.fromPolylineXY([p_start, final_p_end]))
                    feat_perp.setAttributes([
                        f.id(),
                        v_idx + 1,
                        az_ray,
                        touch_id,
                        get_cardinal(az_ray)
                    ])
                    sink_perp.addFeature(feat_perp, QgsFeatureSink.FastInsert)

        return {
            self.OUTPUT_LINES:       dest_lines,
            self.OUTPUT_AXES:        dest_axes,
            self.OUTPUT_CLASSIFIERS: dest_class,
            self.OUTPUT_PERP_SENSORS: dest_perp
        }