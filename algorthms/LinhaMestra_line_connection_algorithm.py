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
    SPACING = 'SPACING'
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
                self.SPACING,
                self.tr('Espaçamento entre Partições'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0
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
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)

        # Configuração básica do Sink (destino) para que o algoritmo seja executável
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),
            source.wkbType(),
            source.sourceCrs()
        )

        features = source.getFeatures()
        feature_count = source.featureCount()
        total = 100.0 / feature_count if feature_count > 0 else 0

        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break
            
            # Por enquanto apenas repassa a feição original
            sink.addFeature(feature, QgsFeatureSink.FastInsert)
            
            # Atualiza o feedback de progresso
            feedback.setProgress(int(current * total))

        return {self.OUTPUT: dest_id}