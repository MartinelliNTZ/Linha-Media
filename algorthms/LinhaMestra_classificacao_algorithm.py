# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsWkbTypes,
                       QgsGeometry,
                       QgsFeature,
                       QgsFields,
                       QgsPointXY,
                       QgsField)
import math
from ..core.vector_utils import VectorUtils

class LinhaMestraClassificacaoAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT_LINES = 'OUTPUT_LINES'
    OUTPUT_AXES = 'OUTPUT_AXES'
    OUTPUT_CLASSIFIERS = 'OUTPUT_CLASSIFIERS'
    THRESHOLD = 'THRESHOLD'
    AXIS_MODE = 'AXIS_MODE'

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
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_AXES, self.tr('Eixos Cardeais'), QgsProcessing.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_CLASSIFIERS, self.tr('Linhas Classificadoras (Offsets)'), QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        axis_mode = self.parameterAsInt(parameters, self.AXIS_MODE, context)
        features = list(source.getFeatures())

        # 1. Obter Pontos Extremos e Criar Eixos
        real_pts = VectorUtils.get_8_cardinal_points([f.geometry() for f in features])
        extent = source.sourceExtent()
        mp = extent.center()

        if axis_mode == 1: # Eixos Fixos
            # Para NS e LO: Ortogonalidade perfeita, mas com dimensões reais dos dados
            half_h = (real_pts['N'].y() - real_pts['S'].y()) / 2.0
            half_w = (real_pts['L'].x() - real_pts['O'].x()) / 2.0
            
            # Para Diagonais: Vetor real centralizado no MP da camada
            def get_centered_pair(p1, p2, center):
                vx, vy = (p2.x() - p1.x()) / 2.0, (p2.y() - p1.y()) / 2.0
                return [QgsPointXY(center.x() - vx, center.y() - vy), 
                        QgsPointXY(center.x() + vx, center.y() + vy)]

            pts = {
                'NS': [QgsPointXY(mp.x(), mp.y() + half_h), QgsPointXY(mp.x(), mp.y() - half_h)],
                'LO': [QgsPointXY(mp.x() + half_w, mp.y()), QgsPointXY(mp.x() - half_w, mp.y())],
                'NOSE': get_centered_pair(real_pts['NO'], real_pts['SE'], mp),
                'SONE': get_centered_pair(real_pts['SO'], real_pts['NE'], mp)
            }
        else: # Ponto a Ponto
            pts = {
                'NS': [real_pts['N'], real_pts['S']],
                'LO': [real_pts['L'], real_pts['O']],
                'NOSE': [real_pts['NO'], real_pts['SE']],
                'SONE': [real_pts['SO'], real_pts['NE']]
            }

        axis_pairs = [
            ('N*S', pts['NS']),
            ('L*O', pts['LO']),
            ('NO*SE', pts['NOSE']),
            ('SO*NE', pts['SONE'])
        ]

        # OUTPUT 1: Eixos
        fields_axes = source.fields()
        fields_axes.append(QgsField('Name', QVariant.String))
        fields_axes.append(QgsField('Length', QVariant.Double))
        (sink_axes, dest_axes) = self.parameterAsSink(parameters, self.OUTPUT_AXES, context, fields_axes, QgsWkbTypes.LineString, source.sourceCrs())

        sorted_axes = []
        for name, pair in axis_pairs:
            dist = pair[0].distance(pair[1])
            sorted_axes.append({'name': name, 'pts': pair, 'len': dist})
            f = QgsFeature(fields_axes)
            f.setGeometry(QgsGeometry.fromPolylineXY(pair))
            f.setAttributes([None]*len(source.fields()) + [name, dist])
            sink_axes.addFeature(f)

        # 2. Determinar Primária e Secundária
        sorted_axes.sort(key=lambda x: x['len'], reverse=True)
        primary = sorted_axes[0]
        # A secundária é o par ortogonal (N*S com L*O ou NO*SE com SO*NE)
        secondary = next(x for x in sorted_axes if x['name'] != primary['name'] and (
            (primary['name'] in ['N*S', 'L*O'] and x['name'] in ['N*S', 'L*O']) or
            (primary['name'] in ['NO*SE', 'SO*NE'] and x['name'] in ['NO*SE', 'SO*NE'])
        ))

        # 3. Ponto de Cruzamento e Offsets
        # Vetores de passo baseados no deslocamento total do eixo oposto dividido por 20 (21 linhas)
        v_step_pri = QgsPointXY(
            (secondary['pts'][0].x() - secondary['pts'][1].x()) / 20.0,
            (secondary['pts'][0].y() - secondary['pts'][1].y()) / 20.0
        )
        
        v_step_sec = QgsPointXY(
            (primary['pts'][0].x() - primary['pts'][1].x()) / 20.0,
            (primary['pts'][0].y() - primary['pts'][1].y()) / 20.0
        )

        # Centralização: as linhas base (i=0) já estão centralizadas no 'mp' geral
        # primary['pts'] e secondary['pts'] no modo axis_mode=1 já saem do centro mp

        # OUTPUT 2: Classificadores
        fields_class = source.fields()
        fields_class.append(QgsField('offset_id', QVariant.Int))
        fields_class.append(QgsField('axis_type', QVariant.String))
        (sink_class, dest_class) = self.parameterAsSink(parameters, self.OUTPUT_CLASSIFIERS, context, fields_class, QgsWkbTypes.LineString, source.sourceCrs())

        # Gerar 21 Offsets da Primária (Varredura - lnPri) -> Movem-se ao longo da Secundária
        primary_offsets = []
        for i in range(-10, 11):
            # i=0 é o centro, i=-10 é uma ponta da secundária, i=10 é a outra ponta
            off_pts = VectorUtils.translate_line(primary['pts'], v_step_pri.x() * i, v_step_pri.y() * i)
            primary_offsets.append(off_pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(off_pts))
            f.setAttributes([None]*len(source.fields()) + [i, 'PRIMARY'])
            sink_class.addFeature(f)

        # Gerar 21 Offsets da Secundária (Varredura - lnSec) -> Movem-se ao longo da Primária
        secondary_offsets = []
        for i in range(-10, 11):
            off_pts = VectorUtils.translate_line(secondary['pts'], v_step_sec.x() * i, v_step_sec.y() * i)
            secondary_offsets.append(off_pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(off_pts))
            f.setAttributes([None]*len(source.fields()) + [i, 'SECONDARY'])
            sink_class.addFeature(f)

        # 4. Escaneamento e OUTPUT 3
        # Limpeza de Schema: Evita erro de "Value is not a number" ignorando campos de classificações anteriores
        output_fields = QgsFields()
        skip_names = ['tipo_line', 'soma_pri', 'media_pri', 'soma_sec', 'media_sec']
        skip_names += [f'lnPri{i}' for i in range(21)] + [f'lnSec{i}' for i in range(21)]
        
        indices_originais = []
        for i, field in enumerate(source.fields()):
            if field.name() not in skip_names:
                output_fields.append(field)
                indices_originais.append(i)

        fields_lines = output_fields
        fields_lines.append(QgsField('tipo_line', QVariant.String))
        
        # Nomes dos atributos atualizados: lnPri0...20 e lnSec0...20
        for i in range(21):
            fields_lines.append(QgsField(f'lnPri{i}', QVariant.Int))
        for i in range(21):
            fields_lines.append(QgsField(f'lnSec{i}', QVariant.Int))
            
        fields_lines.append(QgsField('soma_pri', QVariant.Double))
        fields_lines.append(QgsField('media_pri', QVariant.Double))
        fields_lines.append(QgsField('soma_sec', QVariant.Double))
        fields_lines.append(QgsField('media_sec', QVariant.Double))

        (sink_lines, dest_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, fields_lines, QgsWkbTypes.LineString, source.sourceCrs())

        def get_scan_start_pt(line_pts, axis_name):
            """Define o ponto zero da régua de escaneamento baseada na regra cardinal."""
            if axis_name == 'N*S': return max(line_pts, key=lambda p: p.y()) # Começa no Norte
            if axis_name == 'L*O': return min(line_pts, key=lambda p: p.x()) # Começa no Oeste
            if axis_name == 'NO*SE': return min(line_pts, key=lambda p: (p.x() - p.y())) # Noroeste
            if axis_name == 'SO*NE': return max(line_pts, key=lambda p: (p.x() + p.y())) # Nordeste (topo direito)
            return line_pts[0]

        contour_features = features
        
        # Estruturas para guardar as notas
        results_l = {f.id(): {i: 0 for i in range(21)} for f in contour_features}
        results_p = {f.id(): {i: 0 for i in range(21)} for f in contour_features}

        # Escaneamento Varredura Lateral (lnPri)
        for c_idx, c_line in enumerate(primary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, primary['name'])
            hits = []
            for feat in contour_features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    # Pega o ponto de intersecção mais próximo do início do escaneamento
                    impact_pt = VectorUtils._get_closest_point(inter, start_pt)
                    if impact_pt:
                        hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_l[fid][c_idx] = rank

        # Escaneamento Varredura Longitudinal (lnSec)
        for c_idx, c_line in enumerate(secondary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, secondary['name'])
            hits = []
            for feat in contour_features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    impact_pt = VectorUtils._get_closest_point(inter, start_pt)
                    if impact_pt:
                        hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_p[fid][c_idx] = rank

        # Salvar Curvas Finalizadas
        for feat in contour_features:
            out_f = QgsFeature(fields_lines)
            out_f.setGeometry(feat.geometry())
            
            # Classificação Morfológica (Tipo de Curva)
            tipo, _, _ = VectorUtils.classify_line_morphology(feat.geometry(), threshold)
            
            notas_l = [results_l[feat.id()][i] for i in range(21)]
            notas_p = [results_p[feat.id()][i] for i in range(21)]
            
            soma_l = sum(notas_l)
            hits_l = len([n for n in notas_l if n > 0])
            media_pri = soma_l / hits_l if hits_l > 0 else 0
            
            soma_p = sum(notas_p)
            hits_p = len([n for n in notas_p if n > 0])
            media_sec = soma_p / hits_p if hits_p > 0 else 0

            # CONSTRUÇÃO DA LISTA DE ATRIBUTOS (Ordem Crítica)
            new_attrs = [feat.attribute(idx) for idx in indices_originais]
            new_attrs.append(tipo) # tipo_line
            new_attrs.extend(notas_l) # lnPri0...20
            new_attrs.extend(notas_p) # lnSec0...20
            new_attrs.extend([soma_l, media_pri, soma_p, media_sec]) # Estatísticas
            
            out_f.setAttributes(new_attrs)
            sink_lines.addFeature(out_f)

        return {
            self.OUTPUT_LINES: dest_lines,
            self.OUTPUT_AXES: dest_axes,
            self.OUTPUT_CLASSIFIERS: dest_class
        }