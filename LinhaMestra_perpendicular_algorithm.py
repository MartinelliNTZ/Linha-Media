# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingException,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFields,
                       QgsField)
from .vector_utils import VectorUtils

class LinhaPerpendicularMediaAlgorithm(QgsProcessingAlgorithm):
    INPUT_LINE = 'INPUT_LINE'
    INPUT_LINES_MAES = 'INPUT_LINES_MAES'
    DISTANCE = 'DISTANCE'
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
        fields_output.append(QgsField('original_id', QVariant.Int))
        fields_output.append(QgsField('vertex_id', QVariant.Int))

        (sink, dest_id) = self.parameterAsSink(
            parameters, 
            self.OUTPUT, 
            context, 
            fields_output, 
            QgsWkbTypes.LineString, 
            input_line_source.sourceCrs()
        )

        total_features = input_line_source.featureCount()
        for current_feat_idx, feature in enumerate(input_line_source.getFeatures()):
            if feedback.isCanceled():
                break

            feedback.pushInfo(self.tr(f'Processando feição {current_feat_idx + 1}/{total_features} (ID: {feature.id()})...'))
            
            perpendicular_geoms = VectorUtils.generate_perpendiculars_from_line_vertices(
                feature.geometry(), 
                mother_line1_geom, 
                mother_line2_geom, 
                distance, 
                feedback
            )

            for vertex_idx, geom_perp in enumerate(perpendicular_geoms):
                if feedback.isCanceled(): break
                feat_out = VectorUtils.create_feature(geom_perp, fields_output, [feature.id(), vertex_idx + 1])
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