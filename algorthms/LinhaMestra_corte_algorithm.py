# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsFeature,
                       QgsGeometry,
                       QgsWkbTypes)

class LinhaMestraCorteAlgorithm(QgsProcessingAlgorithm):
    """
    Algoritmo para cortar (dividir) polígonos ou linhas usando uma camada de linhas como lâmina.
    """
    INPUT = 'INPUT'
    CUTTER = 'CUTTER'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('LinhaMestraCorteAlgorithm', string)

    def createInstance(self):
        return LinhaMestraCorteAlgorithm()

    def name(self):
        return 'linhamestra_corte'

    def displayName(self):
        return self.tr('Cortar Feições com Linhas')

    def group(self):
        return self.tr('Linha Mestra')

    def groupId(self):
        return 'linhamestra'

    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Camada de Entrada (Polígonos ou Linhas)'),
                [QgsProcessing.TypeVectorAnyGeometry]
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUTTER,
                self.tr('Camada de Corte (Linhas)'),
                [QgsProcessing.TypeVectorLine]
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Feições Cortadas'),
                QgsProcessing.TypeVectorAnyGeometry
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        cutter_source = self.parameterAsSource(parameters, self.CUTTER, context)

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),
            source.wkbType(),
            source.sourceCrs()
        )

        # Coletar todas as linhas de corte em uma lista de sequências de pontos
        # splitGeometry exige QgsPointSequence (lista de QgsPointXY)
        cutters = []
        for f in cutter_source.getFeatures():
            if feedback.isCanceled(): break
            geom = f.geometry()
            if geom.isMultipart():
                for part in geom.asMultiPolyline():
                    cutters.append(part)
            else:
                cutters.append(geom.asPolyline())

        total = source.featureCount()
        features = source.getFeatures()

        for count, feat in enumerate(features):
            if feedback.isCanceled(): break

            geom = feat.geometry()
            
            # Lista de geometrias resultantes para esta feição
            # Começamos com a original
            results = [geom]

            for cut_line in cutters:
                new_results = []
                for g in results:
                    # O método splitGeometry divide a geometria g in-place e retorna as novas partes
                    # Retorno: (ErrorCode, NewGeometries, LeftPoint, RightPoint)
                    # ErrorCode 0 = Sucesso
                    res, new_parts, _, _ = g.splitGeometry(cut_line, False)
                    
                    if res == 0:
                        # Se cortou, g agora é uma das metades, new_parts contém as outras
                        new_results.append(QgsGeometry(g))
                        new_results.extend(new_parts)
                    else:
                        # Se não houve corte, mantém a geometria como estava
                        new_results.append(g)
                results = new_results

            # Salvar todas as partes no sink
            for fragment_geom in results:
                # Para linhas que foram cortadas mas resultaram em MultiLineStrings, 
                # podemos querer explodir para feições simples
                if fragment_geom.isMultipart():
                    for part in fragment_geom.asGeometryCollection():
                        new_feat = QgsFeature(feat)
                        new_feat.setGeometry(part)
                        sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
                else:
                    new_feat = QgsFeature(feat)
                    new_feat.setGeometry(fragment_geom)
                    sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

            feedback.setProgress(int((count / total) * 100))

        return {self.OUTPUT: dest_id}