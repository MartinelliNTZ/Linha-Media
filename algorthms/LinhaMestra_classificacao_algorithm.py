# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsProcessingParameterNumber,
                       QgsGeometry,
                       QgsFeature,
                       QgsField)
from ..core.vector_utils import VectorUtils

class LinhaMestraClassificacaoAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
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
        return self.tr('Linha Mestra')

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
                self.OUTPUT,
                self.tr('Curvas Classificadas'),
                QgsProcessing.TypeVectorLine
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)

        fields = source.fields()
        fields.append(QgsField('tipo_line', QVariant.String))
        fields.append(QgsField('ordem_id', QVariant.Int))
        fields.append(QgsField('az_medio', QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, source.wkbType(), source.sourceCrs()
        )

        features = list(source.getFeatures())
        processed_data = []
        
        # 1. Classificação e Coleta de dados
        all_azimuths = []
        for feat in features:
            if feedback.isCanceled(): break
            
            geom = feat.geometry()
            tipo, az_med, dev = VectorUtils.classify_line_morphology(geom, threshold)
            
            centroid = geom.centroid().asPoint()
            if geom.centroid().isEmpty():
                nodes = list(geom.vertices())
                centroid = nodes[0] if nodes else None

            processed_data.append({
                'feat': feat,
                'tipo': tipo,
                'az': az_med,
                'centroid': centroid
            })
            all_azimuths.append(az_med)

        if not processed_data:
            return {self.OUTPUT: dest_id}

        # 2. Numeração para Curvas de Nível (Abordagem de Fluxo de Terreno)
        # Em vez de paralelismo local, usamos o azimute predominante do conjunto
        # para projetar e ordenar (isso funciona bem para camadas de curvas de nível)
        avg_global_az = sum(all_azimuths) / len(all_azimuths)
        
        # Ordenação por projeção espacial
        processed_data.sort(key=lambda x: VectorUtils.get_projection_value(x['centroid'], avg_global_az))

        # 3. Salvar resultados
        for i, data in enumerate(processed_data, 1):
            if feedback.isCanceled(): break
            
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(data['feat'].geometry())
            
            attrs = data['feat'].attributes()
            attrs.append(data['tipo'])
            attrs.append(i) # Numeração sequencial baseada na posição do terreno
            attrs.append(data['az'])
            
            out_feat.setAttributes(attrs)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)
            
            feedback.setProgress(int((i / len(processed_data)) * 100))

        return {self.OUTPUT: dest_id}