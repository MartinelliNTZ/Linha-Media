# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterDefinition,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum,
                       QgsProcessingException,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFields,
                       QgsField,
                       QgsSpatialIndex,
                       QgsGeometry,
                       QgsPointXY)
import math
from ..core.vector_utils import VectorUtils
from ..core.connection_judge import ConnectionJudge


class LinhaMestraMassaAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    ORDER_FIELD = 'ORDER_FIELD'
    GROUP_FIELD = 'GROUP_FIELD'
    PARTICOES = 'PARTICOES'
    ESTILO_CONEXAO = 'ESTILO_CONEXAO'
    ESTILO_LINHA_MESTRA = 'ESTILO_LINHA_MESTRA'
    CRITERIO_PROXIMIDADE = 'CRITERIO_PROXIMIDADE'
    OUTPUT = 'OUTPUT'
    CONEXAO_OUTPUT = 'CONEXAO_OUTPUT'
    OUTPUT_CONSULTA_1 = 'OUTPUT_CONSULTA_1'
    OUTPUT_CONSULTA_2 = 'OUTPUT_CONSULTA_2'
    OUTPUT_SEGMENTOS = 'OUTPUT_SEGMENTOS'
    OUTPUT_VERTICES = 'OUTPUT_VERTICES'
    OUTPUT_PERP_PROC = 'OUTPUT_PERP_PROC'
    ALCANCE_SENSOR = 'ALCANCE_SENSOR'
    REDUCAO_FILTRO = 'REDUCAO_FILTRO'
    RESOLVER_ORFAOS_PONTAS = 'RESOLVER_ORFAOS_PONTAS'
    ESPACAMENTO = 'ESPACAMENTO'

    def initAlgorithm(self, config):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('Camada de Linhas'), [QgsProcessing.TypeVectorLine]))

        self.addParameter(QgsProcessingParameterField(
            self.ORDER_FIELD, self.tr('Campo de Ordenação (Opcional - Sequência)'),
            parentLayerParameterName=self.INPUT,
            optional=True))

        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD, self.tr('Campo de Agrupamento (Opcional)'),
            parentLayerParameterName=self.INPUT,
            optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARTICOES, self.tr('Número de Partiçôes'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=50))

        self.addParameter(
            QgsProcessingParameterEnum(
                self.ESTILO_CONEXAO,
                self.tr('Estilo de Conexão'),
                options=['Proximidade', 'Perpendicular', 'Conexão Direta (Ponto a Ponto)', 'Espaçamento Fixo (1:1)'],
                defaultValue=0))

        self.addParameter(
            QgsProcessingParameterEnum(
                self.ESTILO_LINHA_MESTRA,
                self.tr('Estilo da Linha Mestra'),
                options=['Interpolação (Ponto a Ponto)', 'Proximidade (Média Espacial)', 'Espaçamento Fixo (1:1)'],
                defaultValue=1))

        self.addParameter(
            QgsProcessingParameterEnum(
                self.CRITERIO_PROXIMIDADE,
                self.tr('Critério de Proximidade (Escolha da Base)'),
                options=['Ponto na Ponta -> Meio (Sincronismo)', 'Menor Tamanho', 'Maior Tamanho', 'Menor Ângulo', 'Maior Ângulo'],
                defaultValue=0))

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RESOLVER_ORFAOS_PONTAS,
                self.tr('Resolver órfãos das pontas no método de Proximidade'),
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ESPACAMENTO,
                self.tr('Espaçamento Fixo (Metros)'),
                type=QgsProcessingParameterNumber.Double,
                minValue=0.1,
                defaultValue=1.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALCANCE_SENSOR,
                self.tr('Alcance do Sensor de Vizinhança (Metros)'),
                type=QgsProcessingParameterNumber.Double,
                minValue=0.1,
                defaultValue=400.0))

        param_reducao = QgsProcessingParameterNumber(
            self.REDUCAO_FILTRO,
            self.tr('Redução para Filtro de Cruzamento (metros)'),
            type=QgsProcessingParameterNumber.Double,
            minValue=0.0,
            maxValue=1.0,
            defaultValue=1
        )
        param_reducao.setFlags(QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param_reducao)

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr('Linhas Mestras'), QgsProcessing.TypeVectorLine))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.CONEXAO_OUTPUT, self.tr('Conexões'), QgsProcessing.TypeVectorLine))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_CONSULTA_1,
                self.tr('Consulta: Sensores 1ª Varredura'),
                QgsProcessing.TypeVectorLine,
                optional=True,
                createByDefault=True))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_CONSULTA_2,
                self.tr('Consulta: Sensores 2ª Varredura'),
                QgsProcessing.TypeVectorLine,
                optional=True,
                createByDefault=True))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_SEGMENTOS,
                self.tr('Segmentos Fragmentados'),
                QgsProcessing.TypeVectorLine,
                optional=True,
                createByDefault=True))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_VERTICES,
                self.tr('Vértices'),
                QgsProcessing.TypeVectorPoint,
                optional=True,
                createByDefault=True))

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_PERP_PROC,
                self.tr('Consulta: Perpendiculares do Processamento'),
                QgsProcessing.TypeVectorLine,
                optional=True,
                createByDefault=True))

    # ------------------------------------------------------------------
    # Helper: atribui ID_Mae string sequencial às features
    # ------------------------------------------------------------------
    @staticmethod
    def _atribuir_ids_mae(features):
        """Zera campos e atribui ID_Mae = 'L0', 'L1', ..."""
        for idx, f in enumerate(features):
            f.setFields(QgsFields())
            f.setAttributes(['L{}'.format(idx)])
        return features

    # ------------------------------------------------------------------
    # Helper: subdivide geometria (compatível QGIS 3.16)
    # ------------------------------------------------------------------
    @staticmethod
    def _get_safe_substring(geometry, start_dist, end_dist):
        if geometry.isEmpty():
            return QgsGeometry()
        if not geometry.isMultipart():
            abstract_geom = geometry.constGet()
            if hasattr(abstract_geom, 'curveSubstring'):
                return QgsGeometry(abstract_geom.curveSubstring(start_dist, end_dist))
        segment_len = end_dist - start_dist
        if segment_len <= 0:
            return QgsGeometry()
        num_samples = 50
        pts = []
        for i in range(num_samples + 1):
            d = start_dist + (i * (segment_len / num_samples))
            p_geom = geometry.interpolate(d)
            if not p_geom.isEmpty():
                pts.append(p_geom.asPoint())
        if len(pts) < 2:
            return QgsGeometry()
        return QgsGeometry.fromPolylineXY(pts)

    # ------------------------------------------------------------------
    # Helper: executa varredura de sensores (1ª ou 2ª)
    # ------------------------------------------------------------------
    def _executar_varredura(self, features, feat_map, max_sonda, particoes,
                             sink_consulta, fields_consulta, id_mapper):
        """
        Varre cada feature, gera raios ±90° em cada vértice.
        Escreve DIRETO no sink_consulta (sem buffer).
        Retorna: vizinhos_por_feature = { id_mae: [ set(vizinhos_por_vertice), ... ] }
        id_mapper(feat) -> id_mae string
        """
        vizinhos_por_feature = {}

        for f_ori in features:
            id_mae = id_mapper(f_ori)
            geom_ori = f_ori.geometry()
            pts_amostra = VectorUtils.get_equidistant_points(geom_ori, particoes + 1)

            vizinhos_por_vertice = []
            for i, p in enumerate(pts_amostra):
                az_local = VectorUtils.get_vertex_azimuth(pts_amostra, i)
                id_vertice = '{}_{}'.format(id_mae, i)
                viz_por_lado = {'esquerdo': None, 'direito': None}

                for az_offset, lado in [(90, 'esquerdo'), (-90, 'direito')]:
                    az_ray = (az_local + az_offset) % 360
                    rad = math.radians(az_ray)
                    p_target = QgsPointXY(
                        p.x() + max_sonda * math.sin(rad),
                        p.y() + max_sonda * math.cos(rad))
                    ray_geom = QgsGeometry.fromPolylineXY([p, p_target])

                    best_dist = float('inf')
                    best_viz_id = None  # id_mae do vizinho (string)

                    candidates = feat_map['spatial_index'].intersects(ray_geom.boundingBox())
                    for c in candidates:
                        if c == f_ori.id():
                            continue
                        c_feat = feat_map['by_feature_id'].get(c)
                        if c_feat is None:
                            continue
                        c_geom = c_feat.geometry()
                        if not ray_geom.intersects(c_geom):
                            continue
                        inter = ray_geom.intersection(c_geom)
                        if inter.isEmpty():
                            continue
                        pt_int = VectorUtils._get_closest_point(inter, p)
                        if pt_int is None:
                            continue
                        d = p.distance(pt_int)
                        if d < best_dist:
                            best_dist = d
                            best_viz_id = feat_map['id_mae_by_feature_id'].get(c, None)

                    vizinho_str = best_viz_id if best_viz_id else ''
                    if best_viz_id:
                        viz_por_lado[lado] = best_viz_id

                    # Escrever sensor no sink
                    sensor_attrs = [
                        id_mae,
                        id_vertice,
                        round(az_local, 4),
                        round(az_ray, 4),
                        lado,
                        vizinho_str,
                        round(best_dist if best_dist != float('inf') else -1, 4),
                        round(p.x(), 4),
                        round(p.y(), 4)
                    ]
                    feat_s = VectorUtils.create_feature(ray_geom, fields_consulta, sensor_attrs)
                    sink_consulta.addFeature(feat_s, QgsFeatureSink.FastInsert)

                vizinhos_por_vertice.append(viz_por_lado)

            vizinhos_por_feature[id_mae] = (f_ori, vizinhos_por_vertice)

        return vizinhos_por_feature

    # ------------------------------------------------------------------
    # Helper: fragmenta uma feature baseado em mudança de vizinhança
    # ------------------------------------------------------------------
    @staticmethod
    def _fragmentar_feature(feat, vizinhos_por_vertice, particoes,
                            segmentos_out, vertices_out,
                            fields_segmentos, fields_vertices,
                            sink_segmentos, sink_vertices,
                            contador_segmentos, id_mae):
        """
        Quebra a geometria onde os vizinhos mudam.
        Retorna: lista de segmentos [{ 'geom', 'id_seg', 'parent_id', 'vizinhos_set' }]
        """
        geom = feat.geometry()
        if not vizinhos_por_vertice:
            return []

        # Converte vizinhos_por_vertice (dicts) para tuplas hashable por lado
        viz_tuplas = []
        for v in vizinhos_por_vertice:
            viz_tuplas.append((v['esquerdo'], v['direito']))

        start_idx = 0
        segmentos = []
        for i in range(1, len(viz_tuplas)):
            if viz_tuplas[i] != viz_tuplas[start_idx]:
                d_start = (geom.length() / particoes) * start_idx
                d_end = (geom.length() / particoes) * i
                seg_geom = LinhaMestraMassaAlgorithm._get_safe_substring(geom, d_start, d_end)

                seg_id = 'S{}'.format(contador_segmentos[0])
                contador_segmentos[0] += 1

                viz_set = set()
                if viz_tuplas[start_idx][0]:
                    viz_set.add(viz_tuplas[start_idx][0])
                if viz_tuplas[start_idx][1]:
                    viz_set.add(viz_tuplas[start_idx][1])

                # Escrever segmento
                viz_str = ','.join(sorted(viz_set))
                seg_attrs = [
                    seg_id,
                    id_mae,
                    viz_str,
                    len(viz_set),
                    round(seg_geom.length(), 4)
                ]
                feat_seg = VectorUtils.create_feature(seg_geom, fields_segmentos, seg_attrs)
                sink_segmentos.addFeature(feat_seg, QgsFeatureSink.FastInsert)

                # Escrever vértices do segmento
                pts_seg = VectorUtils.get_equidistant_points(seg_geom, particoes + 1)
                for vi, pt in enumerate(pts_seg):
                    vert_attrs = [
                        '{}_{}'.format(seg_id, vi),
                        seg_id,
                        vi,
                        round(pt.x(), 4),
                        round(pt.y(), 4)
                    ]
                    feat_v = VectorUtils.create_feature(
                        QgsGeometry.fromPointXY(pt), fields_vertices, vert_attrs)
                    sink_vertices.addFeature(feat_v, QgsFeatureSink.FastInsert)

                segmentos.append({
                    'geom': seg_geom,
                    'id_seg': seg_id,
                    'parent_id': id_mae,
                    'vizinhos_set': viz_set
                })
                start_idx = i

        # Último pedaço
        d_start = (geom.length() / particoes) * start_idx
        seg_geom_final = LinhaMestraMassaAlgorithm._get_safe_substring(
            geom, d_start, geom.length())

        seg_id = 'S{}'.format(contador_segmentos[0])
        contador_segmentos[0] += 1

        viz_set = set()
        if viz_tuplas[start_idx][0]:
            viz_set.add(viz_tuplas[start_idx][0])
        if viz_tuplas[start_idx][1]:
            viz_set.add(viz_tuplas[start_idx][1])

        viz_str = ','.join(sorted(viz_set))
        seg_attrs = [
            seg_id,
            id_mae,
            viz_str,
            len(viz_set),
            round(seg_geom_final.length(), 4)
        ]
        feat_seg = VectorUtils.create_feature(seg_geom_final, fields_segmentos, seg_attrs)
        sink_segmentos.addFeature(feat_seg, QgsFeatureSink.FastInsert)

        pts_seg = VectorUtils.get_equidistant_points(seg_geom_final, particoes + 1)
        for vi, pt in enumerate(pts_seg):
            vert_attrs = [
                '{}_{}'.format(seg_id, vi),
                seg_id,
                vi,
                round(pt.x(), 4),
                round(pt.y(), 4)
            ]
            feat_v = VectorUtils.create_feature(
                QgsGeometry.fromPointXY(pt), fields_vertices, vert_attrs)
            sink_vertices.addFeature(feat_v, QgsFeatureSink.FastInsert)

        segmentos.append({
            'geom': seg_geom_final,
            'id_seg': seg_id,
            'parent_id': id_mae,
            'vizinhos_set': viz_set
        })
        return segmentos

    # ------------------------------------------------------------------
    # Helper: monta feat_map para varredura (1ª ou 2ª)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_feat_map(features, id_mae_by_feature_id):
        spatial_index = QgsSpatialIndex()
        by_feature_id = {}
        for f in features:
            spatial_index.addFeature(f)
            by_feature_id[f.id()] = f
        return {
            'spatial_index': spatial_index,
            'by_feature_id': by_feature_id,
            'id_mae_by_feature_id': id_mae_by_feature_id
        }

    # ==================================================================
    # processAlgorithm
    # ==================================================================
    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        order_field = self.parameterAsString(parameters, self.ORDER_FIELD, context)
        if not order_field or order_field.strip() == "":
            order_field = None
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        particoes = self.parameterAsInt(parameters, self.PARTICOES, context)
        criterio = self.parameterAsInt(parameters, self.CRITERIO_PROXIMIDADE, context)
        estilo_conn = self.parameterAsInt(parameters, self.ESTILO_CONEXAO, context)
        estilo_mestra = self.parameterAsInt(parameters, self.ESTILO_LINHA_MESTRA, context)
        resolve_pontas = self.parameterAsBool(parameters, self.RESOLVER_ORFAOS_PONTAS, context)
        reducao = self.parameterAsDouble(parameters, self.REDUCAO_FILTRO, context)
        alcance_sensor = self.parameterAsDouble(parameters, self.ALCANCE_SENSOR, context)
        espacamento = self.parameterAsDouble(parameters, self.ESPACAMENTO, context)

        # ---- ETAPA 0: Zerar atributos e gerar ID_Mae ----
        feedback.pushInfo(self.tr('ETAPA 0: Zerando atributos e gerando IDs...'))
        all_features = list(source.getFeatures())
        all_features = self._atribuir_ids_mae(all_features)

        # Mapa rápido: feature_id -> id_mae
        id_mae_map = {}
        for f in all_features:
            id_mae_map[f.id()] = f.attributes()[0]

        # ---- Agrupar ----
        grouped_data = {}
        if group_field:
            for f in all_features:
                gv = f.attribute(group_field)
                if gv not in grouped_data:
                    grouped_data[gv] = []
                grouped_data[gv].append(f)
        else:
            grouped_data['unico'] = all_features

        # ---- Configurar Sinks principais ----
        fields_mestra = QgsFields()
        if group_field:
            fields_mestra.append(QgsField('grupo', QVariant.String))
        fields_mestra.append(QgsField('original_id', QVariant.String))
        fields_mestra.append(QgsField('par_id', QVariant.Int))
        fields_mestra.append(QgsField('dist_mae', QVariant.Double))

        (sink_mestra, dest_id_mestra) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields_mestra, QgsWkbTypes.LineString, source.sourceCrs())

        fields_conexao = QgsFields()
        if group_field:
            fields_conexao.append(QgsField('grupo', QVariant.String))
        fields_conexao.append(QgsField('original_id', QVariant.String))
        fields_conexao.append(QgsField('id_conexao', QVariant.Int))
        fields_conexao.append(QgsField('id_pai', QVariant.Double))
        fields_conexao.append(QgsField('id_mae', QVariant.Double))
        fields_conexao.append(QgsField('id_origem', QVariant.Double))

        (sink_conexao, dest_id_conexao) = self.parameterAsSink(
            parameters, self.CONEXAO_OUTPUT, context, fields_conexao, QgsWkbTypes.LineString, source.sourceCrs())

        # ---- Sinks de Consulta ----
        fields_consulta = QgsFields()
        fields_consulta.append(QgsField('id_mae', QVariant.String))
        fields_consulta.append(QgsField('id_vertice', QVariant.String))
        fields_consulta.append(QgsField('azimute_local', QVariant.Double))
        fields_consulta.append(QgsField('azimute_raio', QVariant.Double))
        fields_consulta.append(QgsField('lado', QVariant.String))
        fields_consulta.append(QgsField('id_vizinho', QVariant.String))
        fields_consulta.append(QgsField('distancia_vizinho', QVariant.Double))
        fields_consulta.append(QgsField('coord_x', QVariant.Double))
        fields_consulta.append(QgsField('coord_y', QVariant.Double))

        (sink_consulta_1, dest_id_consulta_1) = self.parameterAsSink(
            parameters, self.OUTPUT_CONSULTA_1, context,
            fields_consulta, QgsWkbTypes.LineString, source.sourceCrs())

        (sink_consulta_2, dest_id_consulta_2) = self.parameterAsSink(
            parameters, self.OUTPUT_CONSULTA_2, context,
            fields_consulta, QgsWkbTypes.LineString, source.sourceCrs())

        fields_segmentos = QgsFields()
        fields_segmentos.append(QgsField('segmento_id', QVariant.String))
        fields_segmentos.append(QgsField('parent_id', QVariant.String))
        fields_segmentos.append(QgsField('vizinhos', QVariant.String))
        fields_segmentos.append(QgsField('num_vizinhos', QVariant.Int))
        fields_segmentos.append(QgsField('comprimento', QVariant.Double))

        (sink_segmentos, dest_id_segmentos) = self.parameterAsSink(
            parameters, self.OUTPUT_SEGMENTOS, context,
            fields_segmentos, QgsWkbTypes.LineString, source.sourceCrs())

        fields_vertices = QgsFields()
        fields_vertices.append(QgsField('id_vertice', QVariant.String))
        fields_vertices.append(QgsField('id_linha', QVariant.String))
        fields_vertices.append(QgsField('indice', QVariant.Int))
        fields_vertices.append(QgsField('coord_x', QVariant.Double))
        fields_vertices.append(QgsField('coord_y', QVariant.Double))

        (sink_vertices, dest_id_vertices) = self.parameterAsSink(
            parameters, self.OUTPUT_VERTICES, context,
            fields_vertices, QgsWkbTypes.Point, source.sourceCrs())

        fields_perp_proc = QgsFields()
        fields_perp_proc.append(QgsField('par_id', QVariant.Int))
        fields_perp_proc.append(QgsField('original_id', QVariant.String))
        fields_perp_proc.append(QgsField('ponto_indice', QVariant.Int))
        fields_perp_proc.append(QgsField('azimute_mestra', QVariant.Double))
        fields_perp_proc.append(QgsField('distancia_mae', QVariant.Double))

        (sink_perp_proc, dest_id_perp_proc) = self.parameterAsSink(
            parameters, self.OUTPUT_PERP_PROC, context,
            fields_perp_proc, QgsWkbTypes.LineString, source.sourceCrs())

        # ==============================================================
        # PROCESSAMENTO POR GRUPO
        # ==============================================================
        total_groups = len(grouped_data)
        for g_idx, (group_val, group_features) in enumerate(grouped_data.items()):
            if feedback.isCanceled():
                break

            if len(group_features) < 2:
                feedback.pushInfo(self.tr('Grupo "{}" ignorado (menos de 2 feições).'.format(group_val)))
                continue

            # Reconstruir id_mae_map para o grupo
            local_id_mae_map = {}
            for f in group_features:
                local_id_mae_map[f.id()] = f.attributes()[0]

            # ----------------------------------------------------------
            # ETAPA 1: 1ª CONSULTA (sensores sobre linhas originais)
            # ----------------------------------------------------------
            feedback.pushInfo(self.tr('ETAPA 1: 1ª Consulta de sensores...'))
            feat_map_1 = self._build_feat_map(group_features, local_id_mae_map)

            def id_mapper_original(f):
                return local_id_mae_map.get(f.id(), '?')

            # Escrever vértices das linhas originais no OUTPUT_VERTICES
            for f in group_features:
                id_mae = id_mapper_original(f)
                pts = VectorUtils.get_equidistant_points(f.geometry(), particoes + 1)
                for vi, pt in enumerate(pts):
                    vert_attrs = [
                        '{}_{}'.format(id_mae, vi),
                        id_mae,
                        vi,
                        round(pt.x(), 4),
                        round(pt.y(), 4)
                    ]
                    feat_v = VectorUtils.create_feature(
                        QgsGeometry.fromPointXY(pt), fields_vertices, vert_attrs)
                    sink_vertices.addFeature(feat_v, QgsFeatureSink.FastInsert)

            vizinhos_por_feat = self._executar_varredura(
                group_features, feat_map_1, alcance_sensor, particoes,
                sink_consulta_1, fields_consulta, id_mapper_original)

            # ----------------------------------------------------------
            # ETAPA 2: FRAGMENTAÇÃO
            # ----------------------------------------------------------
            feedback.pushInfo(self.tr('ETAPA 2: Fragmentando linhas...'))
            todos_segmentos = []
            contador_segmentos = [0]  # mutable counter

            for feat in group_features:
                id_mae = id_mapper_original(feat)
                entry = vizinhos_por_feat.get(id_mae)
                if entry is None:
                    continue
                _, viz_por_vertice = entry

                segs = self._fragmentar_feature(
                    feat, viz_por_vertice, particoes,
                    todos_segmentos, todos_segmentos,  # segmentos_out, vertices_out (list accumulator)
                    fields_segmentos, fields_vertices,
                    sink_segmentos, sink_vertices,
                    contador_segmentos, id_mae)
                # _fragmentar_feature já escreve segmentos e vértices nos sinks
                todos_segmentos.extend(segs)

            if not todos_segmentos:
                feedback.pushInfo(self.tr('Nenhum segmento gerado para o grupo "{}".'.format(group_val)))
                continue

            # ----------------------------------------------------------
            # ETAPA 3: 2ª CONSULTA (sensores sobre segmentos fragmentados)
            # ----------------------------------------------------------
            feedback.pushInfo(self.tr('ETAPA 3: 2ª Consulta sobre segmentos fragmentados...'))

            # Construir features com IDs explícitos para QgsSpatialIndex
            seg_features = []
            seg_id_mae_map = {}   # feature_id (explícito) -> id_seg string
            seg_by_fid = {}       # feature_id -> QgsFeature
            for idx, seg in enumerate(todos_segmentos):
                fid = idx + 1  # ID explícito (1-based)
                f_seg = QgsFeature(fid)
                f_seg.setGeometry(seg['geom'])
                seg_features.append(f_seg)
                seg_id_mae_map[fid] = seg['id_seg']
                seg_by_fid[fid] = f_seg

            # Construir spatial_index (QGIS 3.16: precisa de IDs explícitos)
            seg_spatial_index = QgsSpatialIndex()
            for f in seg_features:
                seg_spatial_index.addFeature(f)

            # 2ª Varredura — mesmo padrão da ETAPA 1
            for f_ori in seg_features:
                id_mae_seg = seg_id_mae_map.get(f_ori.id(), '?')
                geom_ori = f_ori.geometry()
                pts_amostra = VectorUtils.get_equidistant_points(geom_ori, particoes + 1)

                for i, p in enumerate(pts_amostra):
                    az_local = VectorUtils.get_vertex_azimuth(pts_amostra, i)
                    id_vertice = '{}_{}'.format(id_mae_seg, i)

                    for az_offset, lado in [(90, 'esquerdo'), (-90, 'direito')]:
                        az_ray = (az_local + az_offset) % 360
                        rad = math.radians(az_ray)
                        p_target = QgsPointXY(
                            p.x() + alcance_sensor * math.sin(rad),
                            p.y() + alcance_sensor * math.cos(rad))
                        ray_geom = QgsGeometry.fromPolylineXY([p, p_target])

                        best_dist = float('inf')
                        best_viz_id = ''

                        candidates = seg_spatial_index.intersects(ray_geom.boundingBox())
                        for c in candidates:
                            if c == f_ori.id():
                                continue
                            c_feat = seg_by_fid.get(c)
                            if c_feat is None:
                                continue
                            c_geom = c_feat.geometry()
                            if not ray_geom.intersects(c_geom):
                                continue
                            inter = ray_geom.intersection(c_geom)
                            if inter.isEmpty():
                                continue
                            pt_int = VectorUtils._get_closest_point(inter, p)
                            if pt_int is None:
                                continue
                            d = p.distance(pt_int)
                            if d < best_dist:
                                best_dist = d
                                best_viz_id = seg_id_mae_map.get(c, '')

                        sensor_attrs = [
                            id_mae_seg,
                            id_vertice,
                            round(az_local, 4),
                            round(az_ray, 4),
                            lado,
                            best_viz_id,
                            round(best_dist if best_dist != float('inf') else -1, 4),
                            round(p.x(), 4),
                            round(p.y(), 4)
                        ]
                        feat_s = VectorUtils.create_feature(ray_geom, fields_consulta, sensor_attrs)
                        sink_consulta_2.addFeature(feat_s, QgsFeatureSink.FastInsert)

            # ----------------------------------------------------------
            # ETAPA 4: PROCESSAMENTO DE PARES (Proximidade × Proximidade)
            # ----------------------------------------------------------
            feedback.pushInfo(self.tr('ETAPA 4: Processando pares...'))

            if order_field:
                # Cenário A: com ID
                group_features.sort(key=lambda f: f.attribute(order_field))
                pares_para_processar = []
                for i in range(len(group_features) - 1):
                    pares_para_processar.append((group_features[i], group_features[i + 1]))
            else:
                # Cenário B: sem ID — formar pares a partir dos segmentos
                pares_detectados = set()
                pares_para_processar = []
                for seg in todos_segmentos:
                    for viz_id in seg['vizinhos_set']:
                        par_key = tuple(sorted([seg['parent_id'], viz_id]))
                        if par_key not in pares_detectados:
                            pares_detectados.add(par_key)
                            # Encontrar feature original do vizinho
                            f_viz = None
                            for f in group_features:
                                if local_id_mae_map.get(f.id()) == viz_id:
                                    f_viz = f
                                    break
                            if f_viz is None:
                                continue
                            f1_dummy = QgsFeature()
                            f1_dummy.setGeometry(seg['geom'])
                            f1_dummy.setAttributes([seg['parent_id']])
                            pares_para_processar.append((f1_dummy, f_viz))

            num_pares = len(pares_para_processar)
            feedback.pushInfo(self.tr('Processando Grupo: {} ({} pares)'.format(group_val, num_pares)))

            for i, (f1, f2) in enumerate(pares_para_processar):
                if feedback.isCanceled():
                    break

                par_id = i + 1
                g1, g2 = VectorUtils.align_line_pair(f1.geometry(), f2.geometry())

                v_count1 = sum(1 for _ in g1.vertices())
                v_count2 = sum(1 for _ in g2.vertices())
                target_n = max(v_count1 - 1, v_count2 - 1)

                needs_near = (estilo_mestra == 1 or estilo_conn == 0)
                needs_interp = (estilo_mestra == 0 or estilo_conn == 2 or estilo_conn == 1)
                needs_1to1 = (estilo_mestra == 2 or estilo_conn == 3)

                near_conns = []
                fixed_conns = []
                interp_conns = []
                perp_results = []

                if needs_near:
                    near_conns = ConnectionJudge.solve_nearest_with_criteria(g1, g2, criterio, target_n, resolve_pontas)
                    near_conns = VectorUtils.filter_connections(near_conns, g1, g2, source.sourceCrs(), reducao)

                if needs_interp:
                    m_res, c_res, p_res = VectorUtils.generate_linhamestra_elements(g1, g2, target_n, feedback)
                    interp_conns = VectorUtils.filter_connections(c_res, g1, g2, source.sourceCrs(), reducao)
                    perp_results = p_res

                if needs_1to1:
                    g_pai, g_mae = VectorUtils.align_by_endpoint_logic(f1.geometry(), f2.geometry())
                    fixed_conns = VectorUtils.generate_1to1_connections(g_pai, g_mae, espacamento)
                    fixed_conns = VectorUtils.filter_connections(fixed_conns, g_pai, g_mae, source.sourceCrs(), reducao)

                if estilo_mestra == 1:
                    mestra_final_par = VectorUtils.generate_mestra_from_connections(near_conns)
                elif estilo_mestra == 2:
                    mestra_final_par = VectorUtils.generate_mestra_from_connections(fixed_conns)
                else:
                    mestra_final_par = VectorUtils.generate_mestra_from_connections(interp_conns)

                if estilo_conn == 0:
                    conexao_par = near_conns
                elif estilo_conn == 1:
                    conexao_par = perp_results
                elif estilo_conn == 3:
                    conexao_par = fixed_conns
                else:
                    conexao_par = interp_conns

                # Origem ID
                if not order_field:
                    orig_id = f1.attributes()[0] if f1.attributes() else '?'
                else:
                    orig_id = local_id_mae_map.get(f1.id(), str(f1.id()))

                # OUTPUT: Linhas Mestras
                for res in mestra_final_par:
                    attrs = [str(group_val), orig_id, par_id, res['dist']] if group_field else [orig_id, par_id, res['dist']]
                    feat = VectorUtils.create_feature(res['geom'], fields_mestra, attrs)
                    sink_mestra.addFeature(feat, QgsFeatureSink.FastInsert)

                # OUTPUT: Perpendiculares do Processamento
                for j, mestra_seg in enumerate(mestra_final_par):
                    line_points = mestra_seg['geom'].asPolyline()
                    if len(line_points) >= 2:
                        mp = VectorUtils.get_midpoint(line_points[0], line_points[1])
                        az_mestra = line_points[0].azimuth(line_points[1])
                        perp_az = (az_mestra + 90) % 360
                        half_dist = mestra_seg['dist'] / 2.0
                        rad = math.radians(perp_az)
                        p_start = QgsPointXY(mp.x() - half_dist * math.sin(rad),
                                             mp.y() - half_dist * math.cos(rad))
                        p_end = QgsPointXY(mp.x() + half_dist * math.sin(rad),
                                           mp.y() + half_dist * math.cos(rad))
                        perp_geom = QgsGeometry.fromPolylineXY([p_start, p_end])
                        perp_attrs = [
                            par_id,
                            orig_id,
                            j + 1,
                            round(az_mestra, 4),
                            round(mestra_seg['dist'], 4)
                        ]
                        feat_perp = VectorUtils.create_feature(perp_geom, fields_perp_proc, perp_attrs)
                        sink_perp_proc.addFeature(feat_perp, QgsFeatureSink.FastInsert)

                # OUTPUT: Conexões
                for res_c in conexao_par:
                    attrs_c = [
                        str(group_val),
                        orig_id,
                        res_c.get('id', 0),
                        res_c.get('id_pai', 0),
                        res_c.get('id_mae', 0),
                        res_c.get('id_origem', 0)
                    ] if group_field else [
                        orig_id,
                        res_c.get('id', 0),
                        res_c.get('id_pai', 0),
                        res_c.get('id_mae', 0),
                        res_c.get('id_origem', 0)
                    ]
                    feat_c = VectorUtils.create_feature(res_c['geom'], fields_conexao, attrs_c)
                    sink_conexao.addFeature(feat_c, QgsFeatureSink.FastInsert)

            feedback.setProgress(int(((g_idx + 1) / total_groups) * 100))

        return {
            self.OUTPUT: dest_id_mestra,
            self.CONEXAO_OUTPUT: dest_id_conexao,
            self.OUTPUT_CONSULTA_1: dest_id_consulta_1,
            self.OUTPUT_CONSULTA_2: dest_id_consulta_2,
            self.OUTPUT_SEGMENTOS: dest_id_segmentos,
            self.OUTPUT_VERTICES: dest_id_vertices,
            self.OUTPUT_PERP_PROC: dest_id_perp_proc
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