# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingException,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFields,
                       QgsField)
from .vector_utils import VectorUtils

class LinhaMestraMassaAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    ORDER_FIELD = 'ORDER_FIELD'
    PARTICOES = 'PARTICOES'
    OUTPUT = 'OUTPUT'
    INTERMEDIATE_LINES_OUTPUT = 'INTERMEDIATE_LINES_OUTPUT'

    def initAlgorithm(self, config):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('Camada de Linhas'), [QgsProcessing.TypeVectorLine]))
        
        self.addParameter(QgsProcessingParameterField(
            self.ORDER_FIELD, self.tr('Campo de Ordenação (Sequência)'), 
            parentLayerParameterName=self.INPUT))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARTICOES, self.tr('Número de Partiçôes'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=1000))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Linhas Mestras Geradas'), QgsProcessing.TypeVectorLine))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.INTERMEDIATE_LINES_OUTPUT, self.tr('Conexões Geradas'), QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        # Em QGIS 3.16 usamos parameterAsString para obter o nome do campo
        order_field = self.parameterAsString(parameters, self.ORDER_FIELD, context)
        particoes = self.parameterAsInt(parameters, self.PARTICOES, context)

        # 1. Coletar e Ordenar Feições
        features = list(source.getFeatures())
        if len(features) < 2:
            raise QgsProcessingException(self.tr('A camada deve conter pelo menos 2 feições para processamento em massa.'))

        # Ordenação baseada no atributo escolhido
        features.sort(key=lambda f: f.attribute(order_field))
        
        feedback.pushInfo(self.tr(f'Iniciando processamento de {len(features)} feições ordenadas por "{order_field}"...'))

        # 2. Configurar Sinks
        fields_mestra = QgsFields()
        fields_mestra.append(QgsField('par_id', QVariant.Int))
        fields_mestra.append(QgsField('dist_mae', QVariant.Double))
        
        (sink_mestra, dest_id_mestra) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields_mestra, QgsWkbTypes.LineString, source.sourceCrs())

        fields_conn = QgsFields()
        fields_conn.append(QgsField('par_id', QVariant.Int))
        
        (sink_conn, dest_id_conn) = self.parameterAsSink(
            parameters, self.INTERMEDIATE_LINES_OUTPUT, context, fields_conn, QgsWkbTypes.LineString, source.sourceCrs())

        # 3. Processamento em Pares (Loop de Massa)
        num_pares = len(features) - 1
        for i in range(num_pares):
            if feedback.isCanceled():
                break
            
            f1 = features[i]
            f2 = features[i+1]
            par_id = i + 1

            feedback.pushInfo(self.tr(f'Processando par {par_id}: {f1.attribute(order_field)} -> {f2.attribute(order_field)}'))

            # Processamento Geométrico
            mestra_res, conn_res = VectorUtils.generate_linhamestra_elements(
                f1.geometry(), f2.geometry(), particoes, feedback
            )

            # Escrita dos Resultados via Utils
            for res in mestra_res:
                feat = VectorUtils.create_feature(res['geom'], fields_mestra, [par_id, res['dist']])
                sink_mestra.addFeature(feat, QgsFeatureSink.FastInsert)

            for res_c in conn_res:
                feat = VectorUtils.create_feature(res_c['geom'], fields_conn, [par_id])
                sink_conn.addFeature(feat, QgsFeatureSink.FastInsert)

            # Atualiza progresso global baseado no número de pares
            feedback.setProgress(int(((i + 1) / num_pares) * 100))

        return {self.OUTPUT: dest_id_mestra, self.INTERMEDIATE_LINES_OUTPUT: dest_id_conn}

    def name(self):
        return 'linhamestra_gerador_massa'

    def displayName(self):
        return self.tr('Gerador de Linha Mestra (Em Massa)')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def tr(self, string):
        return QCoreApplication.translate('LinhaMestraMassaAlgorithm', string)

    def createInstance(self):
        return LinhaMestraMassaAlgorithm()