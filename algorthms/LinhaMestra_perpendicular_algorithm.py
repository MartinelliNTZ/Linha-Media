# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingException,
                       QgsFeature,
                       QgsGeometry,
                       QgsPointXY,
                       QgsWkbTypes,
                       QgsFields,
                       QgsField,
                       QgsSpatialIndex)
import math
from ..core.vector_utils import VectorUtils

class LinhaPerpendicularMediaAlgorithm(QgsProcessingAlgorithm):
    INPUT_LINE = 'INPUT_LINE'
    INPUT_LINES_MAES = 'INPUT_LINES_MAES'
    DISTANCE = 'DISTANCE'
    TRIM_COLLISION = 'TRIM_COLLISION'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINE,
                self.tr('Camada de Linhas (para gerar perpendiculares)'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINES_MAES,
                self.tr('Camada de Linhas Mães (Opcional - 2 feições)'),
                [QgsProcessing.TypeVectorLine],
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DISTANCE,
                self.tr('Distância Fixa (se não houver Linhas Mães)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=10.0,
                minValue=0.1
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.TRIM_COLLISION,
                self.tr('Cortar segmentos na colisão com outras linhas'),
                defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Linhas Perpendiculares Geradas'),
                QgsProcessing.TypeVectorLine
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_line_source = self.parameterAsSource(parameters, self.INPUT_LINE, context)
        input_maes_source = self.parameterAsSource(parameters, self.INPUT_LINES_MAES, context)
        distance = self.parameterAsDouble(parameters, self.DISTANCE, context)
        trim_collision = self.parameterAsBool(parameters, self.TRIM_COLLISION, context)

        if input_line_source is None:
            raise QgsProcessingException(self.tr('Camada de linhas de entrada inválida.'))

        mother_line1_geom = None
        mother_line2_geom = None

        if input_maes_source:
            maes_features = list(input_maes_source.getFeatures())
            if len(maes_features) != 2:
                raise QgsProcessingException(self.tr('A camada de Linhas Mães deve conter exatamente 2 feições.'))
            
            # Garante que as linhas mães estejam no mesmo CRS da camada de entrada
            feat1_mae = maes_features[0]
            feat2_mae = maes_features[1]
            
            mother_line1_geom = feat1_mae.geometry()
            mother_line2_geom = feat2_mae.geometry()

            if input_maes_source.sourceCrs() != input_line_source.sourceCrs():
                feedback.pushInfo(self.tr('Reprojetando Linhas Mães para o CRS da camada de entrada...'))
                mother_line1_geom = VectorUtils.reproject_geometry(mother_line1_geom, input_maes_source.sourceCrs(), input_line_source.sourceCrs(), context)
                mother_line2_geom = VectorUtils.reproject_geometry(mother_line2_geom, input_maes_source.sourceCrs(), input_line_source.sourceCrs(), context)
            
            # Opcional: Orientar linhas mães para consistência, embora a intersecção seja agnóstica à direção
            mother_line1_geom = VectorUtils.orient_northwest(mother_line1_geom)
            mother_line2_geom = VectorUtils.orient_northwest(mother_line2_geom)


        fields_output = QgsFields()
        fields_output.append(QgsField('parent_id', QVariant.LongLong))
        fields_output.append(QgsField('vertex_id', QVariant.Int))
        fields_output.append(QgsField('azimuth', QVariant.Double))
        fields_output.append(QgsField('touch_id', QVariant.LongLong))
        fields_output.append(QgsField('side', QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters, 
            self.OUTPUT, 
            context, 
            fields_output, 
            QgsWkbTypes.LineString, 
            input_line_source.sourceCrs()
        )

        # Preparação para colisão
        spatial_index = QgsSpatialIndex(input_line_source.getFeatures())
        feat_dict = {f.id(): f for f in input_line_source.getFeatures()}
        
        total_features = input_line_source.featureCount()
        max_ray_len = (distance / 2.0) if not mother_line1_geom else 10000.0

        for current_feat_idx, feature in enumerate(input_line_source.getFeatures()):
            if feedback.isCanceled(): break

            geom = feature.geometry()
            polyline = list(geom.vertices())
            
            for v_idx, v in enumerate(polyline):
                p_start = QgsPointXY(v.x(), v.y())
                az_local = VectorUtils.get_vertex_azimuth(polyline, v_idx)
                
                # Duas direções (90 e -90 graus)
                dirs = [(az_local + 90) % 360, (az_local - 90) % 360]
                
                for az_ray in dirs:
                    rad = math.radians(az_ray)
                    p_target = QgsPointXY(p_start.x() + max_ray_len * math.sin(rad),
                                         p_start.y() + max_ray_len * math.cos(rad))
                    
                    ray_geom = QgsGeometry.fromPolylineXY([p_start, p_target])
                    final_p_end = p_target
                    touch_id = -1

                    # 1. Se houver linhas mães, o limite é o toque nelas
                    if mother_line1_geom:
                        closest_mother_dist = float('inf')
                        for m_geom in [mother_line1_geom, mother_line2_geom]:
                            inter = ray_geom.intersection(m_geom)
                            if not inter.isEmpty():
                                pt = VectorUtils._get_closest_point(inter, p_start)
                                if pt and p_start.distance(pt) < closest_mother_dist:
                                    closest_mother_dist = p_start.distance(pt)
                                    final_p_end = pt
                        # Atualiza a geometria do raio para o limite da mãe
                        ray_geom = QgsGeometry.fromPolylineXY([p_start, final_p_end])

                    # 2. Se trim ativado, corta na primeira linha da própria camada
                    if trim_collision:
                        candidates = spatial_index.intersects(ray_geom.boundingBox())
                        closest_touch_dist = float('inf')
                        
                        for c_id in candidates:
                            if c_id == feature.id(): continue
                            
                            inter = ray_geom.intersection(feat_dict[c_id].geometry())
                            if not inter.isEmpty():
                                pt = VectorUtils._get_closest_point(inter, p_start)
                                if pt:
                                    d = p_start.distance(pt)
                                    if 0.001 < d < closest_touch_dist:
                                        closest_touch_dist = d
                                        touch_id = c_id
                                        final_p_end = pt

                    # Criar feição do segmento quebrado
                    feat_out = QgsFeature(fields_output)
                    feat_out.setGeometry(QgsGeometry.fromPolylineXY([p_start, final_p_end]))
                    feat_out.setAttributes([
                        feature.id(),
                        v_idx + 1,
                        az_ray,
                        touch_id,
                        VectorUtils.get_cardinal_direction(az_ray)
                    ])
                    sink.addFeature(feat_out, QgsFeatureSink.FastInsert)
            
            feedback.setProgress(int(((current_feat_idx + 1) / total_features) * 100))

        return {self.OUTPUT: dest_id}

    def name(self):
        return 'linha_perpendicular_media'

    def displayName(self):
        return self.tr('Gerador de Perpendiculares Médias')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def tr(self, string):
        return QCoreApplication.translate('LinhaPerpendicularMediaAlgorithm', string)

    def createInstance(self):
        return LinhaPerpendicularMediaAlgorithm()