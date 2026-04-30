# -*- coding: utf-8 -*-

from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink,
                       QgsFeatureSink,
                       QgsFields,
                       QgsField,
                       QgsFeature,
                       QgsGeometry,
                       QgsPointXY,
                       QgsWkbTypes,
                       QgsSpatialIndex)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from ..core.vector_utils import VectorUtils
from ..core.VectorLayerGeometry import VectorLayerGeometry # Importa a nova classe GeometryUtils

class LinhaMestraLineConnectionAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    SENSOR_LIMIT = 'SENSOR_LIMIT'
    SPACING = 'SPACING'
    OUTPUT = 'OUTPUT'
    PERP_OUTPUT = 'PERP_OUTPUT'
    VERT_OUTPUT = 'VERT_OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LinhaMestraLineConnectionAlgorithm()

    def name(self):
        return 'lineconnection'

    def displayName(self):
        return self.tr('Conexão de Linhas')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def shortHelpString(self):
        return self.tr("Este algoritmo conecta extremidades de linhas que estão dentro de uma distância de tolerância específica.")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Camada de Linhas de Entrada'),
                [QgsProcessing.TypeVectorLine]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SENSOR_LIMIT,
                self.tr('Limite do Sensor'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=400
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPACING,
                self.tr('Espaçamento entre Partições'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Camada Padronizada (Spacing)')
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PERP_OUTPUT,
                self.tr('Sensores Perpendiculares')
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.VERT_OUTPUT,
                self.tr('Vértices com Keys')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        sensor_limit = self.parameterAsInt(parameters, self.SENSOR_LIMIT, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)

        # 1. Preparação dos campos
        output_fields = source.fields()
        output_fields.append(QgsField('key_prim', QVariant.String))

        perp_fields = QgsFields()
        perp_fields.append(QgsField('key_prim', QVariant.String))
        perp_fields.append(QgsField('keyVertex', QVariant.String))
        perp_fields.append(QgsField('keyS1', QVariant.String))

        # 2. Configuração dos Sinks
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            output_fields,
            source.wkbType(),
            source.sourceCrs()
        )

        (perp_sink, perp_dest_id) = self.parameterAsSink(
            parameters,
            self.PERP_OUTPUT,
            context,
            perp_fields,
            QgsWkbTypes.LineString,
            source.sourceCrs()
        )

        (vert_sink, vert_dest_id) = self.parameterAsSink(
            parameters,
            self.VERT_OUTPUT,
            context,
            perp_fields,
            QgsWkbTypes.Point,
            source.sourceCrs()
        )

        # 3. Preparação para colisões
        spatial_index = QgsSpatialIndex(source.getFeatures())
        feat_dict = {f.id(): f for f in source.getFeatures()}

        features = source.getFeatures()
        feature_count = source.featureCount()
        total = 100.0 / feature_count if feature_count > 0 else 0

        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break
            
            points = VectorUtils.get_points_at_interval(feature.geometry(), spacing)
            new_geom = QgsGeometry.fromPolylineXY(points) if len(points) >= 2 else feature.geometry()
            key_prim = f"O{current:04d}"

            new_feat = QgsFeature(output_fields)
            new_feat.setGeometry(new_geom)
            
            attrs = feature.attributes()
            attrs.append(key_prim)
            new_feat.setAttributes(attrs)
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

            # 4. Geração de Sensores Perpendiculares usando Utils
            sensors, vertices = VectorLayerGeometry.generate_perpendicular_sensors(
                points, key_prim, sensor_limit, spatial_index, feat_dict, feature.id(), perp_fields
            )
            
            for s in sensors:
                perp_sink.addFeature(s, QgsFeatureSink.FastInsert)
            
            for v in vertices:
                vert_sink.addFeature(v, QgsFeatureSink.FastInsert)

            # Atualiza o feedback de progresso
            feedback.setProgress(int(current * total))

        return {
            self.OUTPUT: dest_id,
            self.PERP_OUTPUT: perp_dest_id,
            self.VERT_OUTPUT: vert_dest_id
        }