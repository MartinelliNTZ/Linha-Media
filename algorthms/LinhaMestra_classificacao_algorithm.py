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

        d1 = inter_pt.distance(secondary['pts'][0])
        d2 = inter_pt.distance(secondary['pts'][1])
        max_dist = max(d1, d2)
        step = max_dist / 9.0

        # Calcular vetor unitário perpendicular à primária para o offset
        dx = primary['pts'][1].x() - primary['pts'][0].x()
        dy = primary['pts'][1].y() - primary['pts'][0].y()
        p_len = primary['len']
        ux, uy = -dy/p_len, dx/p_len # Vetor perpendicular normalizado

        # OUTPUT 2: Classificadores
        fields_class = source.fields()
        fields_class.append(QgsField('offset_id', QVariant.Int))
        (sink_class, dest_class) = self.parameterAsSink(parameters, self.OUTPUT_CLASSIFIERS, context, fields_class, QgsWkbTypes.LineString, source.sourceCrs())

        classifier_lines = []
        for i in range(-10, 11):
            off_pts = VectorUtils.translate_line(primary['pts'], ux * step * i, uy * step * i)
            classifier_lines.append(off_pts)
            f = QgsFeature(fields_class)
            f.setGeometry(QgsGeometry.fromPolylineXY(off_pts))
            f.setAttributes([None]*len(source.fields()) + [i])
            sink_class.addFeature(f)

        # 4. Escaneamento e OUTPUT 3
        fields_lines = source.fields()
        fields_lines.append(QgsField('tipo_line', QVariant.String))
        fields_lines.append(QgsField('id_spatial', QVariant.String))
        (sink_lines, dest_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, fields_lines, QgsWkbTypes.LineString, source.sourceCrs())

        # Regra de sentido: Qual ponto da linha de offset é o "Início"?
        # Ex: N*S = Começa no Norte.
        def get_scan_start_pt(line_pts, axis_name):
            if 'N' in axis_name and 'S' in axis_name: return max(line_pts, key=lambda p: p.y())
            if 'L' in axis_name and 'O' in axis_name: return min(line_pts, key=lambda p: p.x()) # Oeste
            if 'NO' in axis_name: return min(line_pts, key=lambda p: p.x() - p.y())
            return line_pts[0]

        contour_features = list(source.getFeatures())
        classification_results = {f.id(): [] for f in contour_features}

        for c_idx, c_line in enumerate(classifier_lines):
            c_geom = QgsGeometry.fromPolylineXY(c_line)
            start_pt = get_scan_start_pt(c_line, primary['name'])
            
            hits = []
            for feat in contour_features:
                inter = c_geom.intersection(feat.geometry())
                if not inter.isEmpty():
                    # Pega o ponto de impacto mais próximo do início da varredura
                    impact_pt = inter.asMultiPoint()[0] if inter.isMultipart() else inter.asPoint()
                    dist_scan = start_pt.distance(impact_pt)
                    hits.append((feat.id(), dist_scan))
            
            # Ordena quem a linha de offset tocou primeiro
            hits.sort(key=lambda x: x[1])
            for rank, (fid, _) in enumerate(hits, 1):
                classification_results[fid].append(f"L{c_idx-10}_R{rank}")

        # Salvar Curvas Finalizadas
        for feat in contour_features:
            out_f = QgsFeature(fields_lines)
            out_f.setGeometry(feat.geometry())
            
            tipo, _, _ = VectorUtils.classify_line_morphology(feat.geometry(), threshold)
            ids_spat = ",".join(classification_results[feat.id()])
            
            attrs = feat.attributes()
            attrs.append(tipo)
            attrs.append(ids_spat)
            out_f.setAttributes(attrs)
            sink_lines.addFeature(out_f)

        return {
            self.OUTPUT_LINES: dest_lines,
            self.OUTPUT_AXES: dest_axes,
            self.OUTPUT_CLASSIFIERS: dest_class
        }