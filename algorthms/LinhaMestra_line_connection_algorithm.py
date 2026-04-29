# -*- coding: utf-8 -*-

from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink,
                       QgsFeatureSink)
from qgis.PyQt.QtCore import QCoreApplication

class LinhaMestraLineConnectionAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    SENSOR_LIMIT = 'SENSOR_LIMIT'
    PARTITIONS = 'PARTITIONS'
    OUTPUT = 'OUTPUT'

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
                self.PARTITIONS,
                self.tr('Número de Partições'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=50
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Camada Conectada')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        sensor_limit = self.parameterAsInt(parameters, self.SENSOR_LIMIT, context)
        partitions = self.parameterAsInt(parameters, self.PARTITIONS, context)
   
        return {None}