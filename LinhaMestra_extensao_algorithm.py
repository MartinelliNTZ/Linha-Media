# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsFeature)
from .geometry_utils import VectorLayerGeometry

class LinhaMestraExtensaoAlgorithm(QgsProcessingAlgorithm):
    """
    Algoritmo para estender ou reduzir geometrias de linha por um valor fixo em suas extremidades.
    """
    INPUT = 'INPUT'
    DELTA = 'DELTA'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('LinhaMestraExtensaoAlgorithm', string)

    def createInstance(self):
        return LinhaMestraExtensaoAlgorithm()

    def name(self):
        return 'linhamestra_extensao'

    def displayName(self):
        return self.tr('Extensão/Redução de Linhas')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Camada de Linhas'),
                [QgsProcessing.TypeVectorLine]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DELTA,
                self.tr('Valor de Ajuste (metros)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=-0.01
                #elpText=self.tr('Use valores positivos para estender e negativos para reduzir (trim) a linha.')
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Linhas Ajustadas'),
                QgsProcessing.TypeVectorLine
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        delta = self.parameterAsDouble(parameters, self.DELTA, context)

        (sink, dest_id) = self.parameterAsSink(
            parameters, 
            self.OUTPUT, 
            context, 
            source.fields(), 
            source.wkbType(), 
            source.sourceCrs()
        )

        features = source.getFeatures()
        total = source.featureCount()

        for count, feature in enumerate(features):
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            new_geom = VectorLayerGeometry.adjust_line_length(geom, delta)
            
            new_feat = QgsFeature(feature)
            new_feat.setGeometry(new_geom)
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

            feedback.setProgress(int((count / total) * 100))

        return {self.OUTPUT: dest_id}