# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsProcessingException,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFields,
                       QgsField)
from .vector_utils import VectorUtils

class LinhaMestraMassaAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    ORDER_FIELD = 'ORDER_FIELD'
    GROUP_FIELD = 'GROUP_FIELD'
    PARTICOES = 'PARTICOES'
    OUTPUT = 'OUTPUT'
    INTERMEDIATE_LINES_OUTPUT = 'INTERMEDIATE_LINES_OUTPUT'
    PERPENDICULAR_OUTPUT = 'PERPENDICULAR_OUTPUT'
    NEAREST_OUTPUT = 'NEAREST_OUTPUT'
    CRITERIO_PROXIMIDADE = 'CRITERIO_PROXIMIDADE'

    def initAlgorithm(self, config):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('Camada de Linhas'), [QgsProcessing.TypeVectorLine]))
        
        self.addParameter(QgsProcessingParameterField(
            self.ORDER_FIELD, self.tr('Campo de Ordenação (Sequência)'), 
            parentLayerParameterName=self.INPUT))

        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD, self.tr('Campo de Agrupamento (Opcional)'), 
            parentLayerParameterName=self.INPUT,
            optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARTICOES, self.tr('Número de Partiçôes'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=1000))

        self.addParameter(
            QgsProcessingParameterEnum(
                self.CRITERIO_PROXIMIDADE,
                self.tr('Critério de Proximidade (Escolha da Base)'),
                options=['Menor Tamanho', 'Maior Tamanho', 'Menor Ângulo', 'Maior Ângulo', 'Qualquer uma'],
                defaultValue=4))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Linhas Mestras Geradas'), QgsProcessing.TypeVectorLine))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.INTERMEDIATE_LINES_OUTPUT, self.tr('Conexões Geradas'), QgsProcessing.TypeVectorLine))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.PERPENDICULAR_OUTPUT, self.tr('Linhas Perpendiculares Geradas'), QgsProcessing.TypeVectorLine))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.NEAREST_OUTPUT, self.tr('Menor Distância (Proximidade)'), QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        # Em QGIS 3.16 usamos parameterAsString para obter o nome do campo
        order_field = self.parameterAsString(parameters, self.ORDER_FIELD, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        particoes = self.parameterAsInt(parameters, self.PARTICOES, context)
        criterio = self.parameterAsInt(parameters, self.CRITERIO_PROXIMIDADE, context)

        # 1. Coletar e Organizar Grupos
        features = list(source.getFeatures())
        grouped_data = {}

        if group_field:
            feedback.pushInfo(self.tr(f'Agrupando feições pelo campo: {group_field}'))
            for f in features:
                group_val = f.attribute(group_field)
                if group_val not in grouped_data:
                    grouped_data[group_val] = []
                grouped_data[group_val].append(f)
        else:
            feedback.pushInfo(self.tr('Processando todas as feições como um único grupo.'))
            grouped_data['unico'] = features

        # 2. Configurar Sinks
        fields_mestra = QgsFields()
        if group_field:
            fields_mestra.append(QgsField('grupo', QVariant.String))
        fields_mestra.append(QgsField('par_id', QVariant.Int))
        fields_mestra.append(QgsField('dist_mae', QVariant.Double))
        
        (sink_mestra, dest_id_mestra) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields_mestra, QgsWkbTypes.LineString, source.sourceCrs())

        fields_conn = QgsFields()
        if group_field:
            fields_conn.append(QgsField('grupo', QVariant.String))
        fields_conn.append(QgsField('par_id', QVariant.Int))
        
        (sink_conn, dest_id_conn) = self.parameterAsSink(
            parameters, self.INTERMEDIATE_LINES_OUTPUT, context, fields_conn, QgsWkbTypes.LineString, source.sourceCrs())

        fields_perp = QgsFields()
        if group_field: fields_perp.append(QgsField('grupo', QVariant.String))
        fields_perp.append(QgsField('par_id', QVariant.Int))
        (sink_perp, dest_id_perp) = self.parameterAsSink(
            parameters, self.PERPENDICULAR_OUTPUT, context, fields_perp, QgsWkbTypes.LineString, source.sourceCrs())

        fields_near = QgsFields()
        if group_field: fields_near.append(QgsField('grupo', QVariant.String))
        fields_near.append(QgsField('par_id', QVariant.Int))
        
        (sink_near, dest_id_near) = self.parameterAsSink(
            parameters, self.NEAREST_OUTPUT, context, fields_near, QgsWkbTypes.LineString, source.sourceCrs())

        # 3. Processamento Iterativo por Grupo
        total_groups = len(grouped_data)
        for g_idx, (group_val, group_features) in enumerate(grouped_data.items()):
            if feedback.isCanceled():
                break

            if len(group_features) < 2:
                feedback.pushInfo(self.tr(f'Grupo "{group_val}" ignorado por possuir menos de 2 feições.'))
                continue

            # Ordenação dentro do grupo
            group_features.sort(key=lambda f: f.attribute(order_field))
            num_pares = len(group_features) - 1
            
            feedback.pushInfo(self.tr(f'Processando Grupo: {group_val} ({num_pares} pares)'))

            for i in range(num_pares):
                if feedback.isCanceled(): break
                
                f1 = group_features[i]
                f2 = group_features[i+1]
                par_id = i + 1

                # Processamento Geométrico delegado à Utils
                mestra_res, conn_res, perp_res, n1_res, n2_res = VectorUtils.generate_linhamestra_elements(
                    f1.geometry(), f2.geometry(), particoes, feedback
                )

                # Escrita dos Resultados
                for res in mestra_res:
                    attrs = [str(group_val), par_id, res['dist']] if group_field else [par_id, res['dist']]
                    feat = VectorUtils.create_feature(res['geom'], fields_mestra, attrs)
                    sink_mestra.addFeature(feat, QgsFeatureSink.FastInsert)

                for res_c in conn_res:
                    attrs = [str(group_val), par_id] if group_field else [par_id]
                    feat = VectorUtils.create_feature(res_c['geom'], fields_conn, attrs)
                    sink_conn.addFeature(feat, QgsFeatureSink.FastInsert)

                for res_p in perp_res:
                    attrs = [str(group_val), par_id] if group_field else [par_id]
                    feat = VectorUtils.create_feature(res_p['geom'], fields_perp, attrs)
                    sink_perp.addFeature(feat, QgsFeatureSink.FastInsert)

                for res_n in n1_res:
                    attrs = [str(group_val), par_id] if group_field else [par_id]
                    feat = VectorUtils.create_feature(res_n['geom'], fields_near, attrs)
                    sink_n1.addFeature(feat, QgsFeatureSink.FastInsert)

                for res_n2 in n2_res:
                    attrs = [str(group_val), par_id] if group_field else [par_id]
                    feat = VectorUtils.create_feature(res_n2['geom'], fields_near, attrs)
                    sink_n2.addFeature(feat, QgsFeatureSink.FastInsert)

            # Progresso baseado nos grupos processados
            feedback.setProgress(int(((g_idx + 1) / total_groups) * 100))

        return {
            self.OUTPUT: dest_id_mestra, 
            self.INTERMEDIATE_LINES_OUTPUT: dest_id_conn,
            self.PERPENDICULAR_OUTPUT: dest_id_perp,
            self.NEAREST_1_TO_2: dest_id_n1,
            self.NEAREST_2_TO_1: dest_id_n2
        }

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