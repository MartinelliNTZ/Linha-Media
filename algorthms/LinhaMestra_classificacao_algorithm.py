# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsProcessingParameterNumber,
                       QgsWkbTypes,
                       QgsGeometry,
                       QgsFeature,
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
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_AXES, self.tr('Eixos Cardeais'), QgsProcessing.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_CLASSIFIERS, self.tr('Linhas Classificadoras (Offsets)'), QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)

        # 1. Obter Pontos Extremos e Criar Eixos
        geoms = [f.geometry() for f in source.getFeatures()]
        pts = VectorUtils.get_8_cardinal_points(geoms)
        
        axis_pairs = [
            ('N*S', [pts['N'], pts['S']]),
            ('L*O', [pts['L'], pts['O']]),
            ('NO*SE', [pts['NO'], pts['SE']]),
            ('SO*NE', [pts['SO'], pts['NE']])
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
        inter_pt = VectorUtils.get_line_intersection(primary['pts'], secondary['pts'])
        if not inter_pt: inter_pt = VectorUtils.get_midpoint(primary['pts'][0], primary['pts'][1])

        # OUTPUT 2: Classificadores
        fields_class = source.fields()
        fields_class.append(QgsField('offset_id', QVariant.Int))
        fields_class.append(QgsField('axis_type', QVariant.String))
        (sink_class, dest_class) = self.parameterAsSink(parameters, self.OUTPUT_CLASSIFIERS, context, fields_class, QgsWkbTypes.LineString, source.sourceCrs())

        # Gerar 21 Offsets da Primária (Varredura Lateral - lclas)
        primary_offsets = []
        d1_s = inter_pt.distance(secondary['pts'][0])
        d2_s = inter_pt.distance(secondary['pts'][1])
        max_dist_s = max(d1_s, d2_s)
        step_s = max_dist_s / 9.0

        dx_p = primary['pts'][1].x() - primary['pts'][0].x()
        dy_p = primary['pts'][1].y() - primary['pts'][0].y()
        ux_p, uy_p = -dy_p/primary['len'], dx_p/primary['len']

        for i in range(-10, 11):
            off_pts = VectorUtils.translate_line(primary['pts'], ux_p * step_s * i, uy_p * step_s * i)
            primary_offsets.append(off_pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(off_pts))
            f.setAttributes([None]*len(source.fields()) + [i, 'PRIMARY'])
            sink_class.addFeature(f)

        # Gerar 21 Offsets da Secundária (Varredura Longitudinal - pclas)
        secondary_offsets = []
        d1_p = inter_pt.distance(primary['pts'][0])
        d2_p = inter_pt.distance(primary['pts'][1])
        max_dist_p = max(d1_p, d2_p)
        step_p = max_dist_p / 9.0

        dx_s = secondary['pts'][1].x() - secondary['pts'][0].x()
        dy_s = secondary['pts'][1].y() - secondary['pts'][0].y()
        ux_s, uy_s = -dy_s/secondary['len'], dx_s/secondary['len']

        for i in range(-10, 11):
            off_pts = VectorUtils.translate_line(secondary['pts'], ux_s * step_p * i, uy_s * step_p * i)
            secondary_offsets.append(off_pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(off_pts))
            f.setAttributes([None]*len(source.fields()) + [i, 'SECONDARY'])
            sink_class.addFeature(f)

        # 4. Escaneamento e OUTPUT 3
        fields_lines = source.fields()
        fields_lines.append(QgsField('tipo_line', QVariant.String))
        
        # Adiciona os 21 + 21 campos de classificação
        for i in range(21):
            fields_lines.append(QgsField(f'lclas{i}', QVariant.Int))
        for i in range(21):
            fields_lines.append(QgsField(f'pclas{i}', QVariant.Int))
            
        fields_lines.append(QgsField('soma_l', QVariant.Double))
        fields_lines.append(QgsField('media_l', QVariant.Double))
        fields_lines.append(QgsField('soma_p', QVariant.Double))
        fields_lines.append(QgsField('media_p', QVariant.Double))

        (sink_lines, dest_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, fields_lines, QgsWkbTypes.LineString, source.sourceCrs())

        # Regra de sentido: Qual ponto da linha de offset é o "Início"?
        # Ex: N*S = Começa no Norte.
        def get_scan_start_pt(line_pts, axis_name):
            if axis_name == 'N*S': return max(line_pts, key=lambda p: p.y())
            if axis_name == 'L*O': return min(line_pts, key=lambda p: p.x()) # Oeste
            if axis_name == 'NO*SE': return min(line_pts, key=lambda p: p.x() - p.y())
            if axis_name == 'SO*NE': return max(line_pts, key=lambda p: p.x() + p.y()) # Nordeste
            return line_pts[0]

        contour_features = list(source.getFeatures())
        
        # Estruturas para guardar as notas
        results_l = {f.id(): {i: 0 for i in range(21)} for f in contour_features}
        results_p = {f.id(): {i: 0 for i in range(21)} for f in contour_features}

        # Escaneamento Varredura Lateral (Offsets da Primária -> lclas)
        for c_idx, c_line in enumerate(primary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, primary['name'])
            hits = []
            for feat in contour_features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    impact_pt = inter.asMultiPoint()[0] if inter.isMultipart() else inter.asPoint()
                    hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_l[fid][c_idx] = rank

        # Escaneamento Varredura Longitudinal (Offsets da Secundária -> pclas)
        for c_idx, c_line in enumerate(secondary_offsets):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, secondary['name'])
            hits = []
            for feat in contour_features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    impact_pt = inter.asMultiPoint()[0] if inter.isMultipart() else inter.asPoint()
                    hits.append((feat.id(), start_pt.distance(impact_pt)))
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                results_p[fid][c_idx] = rank

        # Salvar Curvas Finalizadas
        for feat in contour_features:
            out_f = QgsFeature(fields_lines)
            out_f.setGeometry(feat.geometry())
            
            tipo, _, _ = VectorUtils.classify_line_morphology(feat.geometry(), threshold)
            
            # Coleta as notas lclas e pclas
            notas_l = [results_l[feat.id()][i] for i in range(21)]
            notas_p = [results_p[feat.id()][i] for i in range(21)]
            
            soma_l = sum(notas_l)
            hits_l = len([n for n in notas_l if n > 0])
            media_l = soma_l / hits_l if hits_l > 0 else 0
            
            soma_p = sum(notas_p)
            hits_p = len([n for n in notas_p if n > 0])
            media_p = soma_p / hits_p if hits_p > 0 else 0

            attrs = feat.attributes()
            attrs.append(tipo)
            
            attrs.extend(notas_l)
            attrs.extend(notas_p)
            attrs.extend([soma_l, media_l, soma_p, media_p])
            
            out_f.setAttributes(attrs)
            sink_lines.addFeature(out_f)

        return {
            self.OUTPUT_LINES: dest_lines,
            self.OUTPUT_AXES: dest_axes,
            self.OUTPUT_CLASSIFIERS: dest_class
        }