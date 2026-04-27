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
            type=QgsProcessingParameterNumber.Integer, defaultValue=1000))

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

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        # No QGIS 3.16, tratamos o campo de ordenação como string opcional
        order_field = self.parameterAsString(parameters, self.ORDER_FIELD, context)
        if not order_field or order_field.strip() == "": order_field = None
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        particoes = self.parameterAsInt(parameters, self.PARTICOES, context)
        criterio = self.parameterAsInt(parameters, self.CRITERIO_PROXIMIDADE, context)
        estilo_conn = self.parameterAsInt(parameters, self.ESTILO_CONEXAO, context)
        estilo_mestra = self.parameterAsInt(parameters, self.ESTILO_LINHA_MESTRA, context)
        resolve_pontas = self.parameterAsBool(parameters, self.RESOLVER_ORFAOS_PONTAS, context)
        reducao = self.parameterAsDouble(parameters, self.REDUCAO_FILTRO, context)
        alcance_sensor = self.parameterAsDouble(parameters, self.ALCANCE_SENSOR, context)
        espacamento = self.parameterAsDouble(parameters, self.ESPACAMENTO, context)

        # 1. Coletar e Organizar Grupos
        all_features = list(source.getFeatures())
        grouped_data = {}

        if group_field:
            feedback.pushInfo(self.tr(f'Agrupando feições pelo campo: {group_field}'))
            for f in all_features:
                group_val = f.attribute(group_field)
                if group_val not in grouped_data:
                    grouped_data[group_val] = []
                grouped_data[group_val].append(f)
        else:
            feedback.pushInfo(self.tr('Processando todas as feições como um único grupo.'))
            grouped_data['unico'] = all_features

        # 2. Configurar Sinks
        fields_mestra = QgsFields()
        if group_field:
            fields_mestra.append(QgsField('grupo', QVariant.String))
        fields_mestra.append(QgsField('original_id', QVariant.LongLong))
        fields_mestra.append(QgsField('par_id', QVariant.Int))
        fields_mestra.append(QgsField('dist_mae', QVariant.Double))
        
        (sink_mestra, dest_id_mestra) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields_mestra, QgsWkbTypes.LineString, source.sourceCrs())

        fields_conexao = QgsFields()
        if group_field:
            fields_conexao.append(QgsField('grupo', QVariant.String))
        fields_conexao.append(QgsField('original_id', QVariant.LongLong))
        fields_conexao.append(QgsField('id_conexao', QVariant.Int))
        fields_conexao.append(QgsField('id_pai', QVariant.Double))
        fields_conexao.append(QgsField('id_mae', QVariant.Double))
        fields_conexao.append(QgsField('id_origem', QVariant.Double))

        (sink_conexao, dest_id_conexao) = self.parameterAsSink(
            parameters, self.CONEXAO_OUTPUT, context, fields_conexao, QgsWkbTypes.LineString, source.sourceCrs())

        # 3. Processamento Iterativo por Grupo
        total_groups = len(grouped_data)
        for g_idx, (group_val, group_features) in enumerate(grouped_data.items()):
            if feedback.isCanceled():
                break

            if len(group_features) < 2:
                feedback.pushInfo(self.tr(f'Grupo "{group_val}" ignorado por possuir menos de 2 feições.'))
                continue

            pares_para_processar = []

            if order_field:
                # --- CENÁRIO A: COM ID (ORDENAÇÃO CLÁSSICA) ---
                group_features.sort(key=lambda f: f.attribute(order_field))
                for i in range(len(group_features) - 1):
                    pares_para_processar.append((group_features[i], group_features[i+1]))
            else:
                # --- CENÁRIO B: SEM ID (DESCOBERTA TOPOLÓGICA POR VIZINHANÇA) ---
                feedback.pushInfo(self.tr('Modo Automático: Gerando sensores de consulta para segmentação...'))
                
                # 1. Criar índice espacial para consulta rápida
                spatial_index = QgsSpatialIndex()
                feat_map = {}
                for f in group_features:
                    spatial_index.addFeature(f)
                    feat_map[f.id()] = f
                
                # 2. Segmentação Dinâmica
                segmentos_homogeneos = []
                max_sonda = alcance_sensor
                
                # Helper para compatibilidade QGIS 3.16 (Acessa curveSubstring via geometria abstrata)
                def get_safe_substring(geometry, start_dist, end_dist):
                    if geometry.isEmpty(): return QgsGeometry()
                    
                    # No QGIS 3.16, QgsMultiLineString não possui curveSubstring.
                    # Se for uma linha simples, tentamos o método nativo.
                    if not geometry.isMultipart():
                        abstract_geom = geometry.constGet()
                        if hasattr(abstract_geom, 'curveSubstring'):
                            return QgsGeometry(abstract_geom.curveSubstring(start_dist, end_dist))
                    
                    # Fallback para MultiLineString ou casos onde o método falha:
                    # Reconstruímos o segmento através de amostragem (interpolação).
                    segment_len = end_dist - start_dist
                    if segment_len <= 0: return QgsGeometry()
                    
                    # Criamos 50 pontos ao longo do trecho para garantir a forma da curva
                    num_samples = 50
                    pts = []
                    for i in range(num_samples + 1):
                        d = start_dist + (i * (segment_len / num_samples))
                        p_geom = geometry.interpolate(d)
                        if not p_geom.isEmpty():
                            pts.append(p_geom.asPoint())
                            
                    if len(pts) < 2: return QgsGeometry()
                    return QgsGeometry.fromPolylineXY(pts)

                for f_ori in group_features:
                    geom_ori = f_ori.geometry()
                    # Amostra pontos conforme a resolução de partições
                    pts_amostra = VectorUtils.get_equidistant_points(geom_ori, particoes + 1)
                    
                    vizinhos_por_ponto = []
                    for i, p in enumerate(pts_amostra):
                        az_local = VectorUtils.get_vertex_azimuth(pts_amostra, i)
                        viz_ponto = set()
                        
                        # Sonda para os dois lados (90 e -90)
                        for az_offset in [90, -90]:
                            az_ray = (az_local + az_offset) % 360
                            rad = math.radians(az_ray)
                            p_target = QgsPointXY(p.x() + max_sonda * math.sin(rad),
                                                 p.y() + max_sonda * math.cos(rad))
                            ray_geom = QgsGeometry.fromPolylineXY([p, p_target])
                            
                            # Busca interseção mais próxima que não seja ela mesma
                            candidates = spatial_index.intersects(ray_geom.boundingBox())
                            best_dist = float('inf')
                            best_viz = -1
                            for c_id in candidates:
                                if c_id == f_ori.id(): continue
                                c_geom = feat_map[c_id].geometry()
                                # Verifica interseção real
                                if not ray_geom.intersects(c_geom):
                                    continue
                                inter = ray_geom.intersection(c_geom)
                                if not inter.isEmpty():
                                    pt_int = VectorUtils._get_closest_point(inter, p)
                                    d = p.distance(pt_int)
                                    if d < best_dist:
                                        best_dist = d
                                        best_viz = c_id
                            if best_viz != -1:
                                viz_ponto.add(best_viz)
                        
                        vizinhos_por_ponto.append(tuple(sorted(list(viz_ponto))))

                    # Quebra a linha onde o conjunto de vizinhos muda
                    if not vizinhos_por_ponto: continue
                    
                    start_idx = 0
                    for i in range(1, len(vizinhos_por_ponto)):
                        if vizinhos_por_ponto[i] != vizinhos_por_ponto[start_idx]:
                            # Houve mudança de vizinho, cria segmento de start_idx até i
                            d_start = (geom_ori.length() / particoes) * start_idx
                            d_end = (geom_ori.length() / particoes) * i
                            seg_geom = get_safe_substring(geom_ori, d_start, d_end)
                            
                            # Registra o segmento e seus vizinhos
                            segmentos_homogeneos.append({
                                'geom': seg_geom,
                                'parent_id': f_ori.id(),
                                'vizinhos': vizinhos_por_ponto[start_idx]
                            })
                            start_idx = i
                    
                    # Adiciona o último pedaço
                    seg_geom_final = get_safe_substring(geom_ori, (geom_ori.length() / particoes) * start_idx, geom_ori.length())
                    segmentos_homogeneos.append({
                        'geom': seg_geom_final,
                        'parent_id': f_ori.id(),
                        'vizinhos': vizinhos_por_ponto[start_idx]
                    })

                # 3. Formação de Pares baseada em Vizinhança Única
                pares_detectados = set()
                for seg in segmentos_homogeneos:
                    fid_atual = seg['parent_id']
                    for v_id in seg['vizinhos']:
                        # Cria um par único (ordenado) para processar uma única vez
                        par_key = tuple(sorted([fid_atual, v_id]))
                        if par_key not in pares_detectados:
                            pares_detectados.add(par_key)
                            # Recupera as geometrias segmentadas específicas para este par
                            # Para simplificar, usamos as geometrias que detectaram o vizinho
                            f1_dummy = QgsFeature()
                            f1_dummy.setGeometry(seg['geom'])
                            f1_dummy.setAttributes([fid_atual])
                            
                            f2_dummy = feat_map[v_id]
                            pares_para_processar.append((f1_dummy, f2_dummy))
            
            num_pares = len(pares_para_processar)
            feedback.pushInfo(self.tr(f'Processando Grupo: {group_val} ({num_pares} pares identificados)'))

            for i, (f1, f2) in enumerate(pares_para_processar):
                if feedback.isCanceled(): break

                par_id = i + 1
                
                # A. Alinhamento e Casamento de Pontas
                g1, g2 = VectorUtils.align_line_pair(f1.geometry(), f2.geometry())

                # B. Cálculo dinâmico do alvo de partições
                v_count1 = sum(1 for _ in g1.vertices())
                v_count2 = sum(1 for _ in g2.vertices())
                target_n = max(particoes, v_count1 - 1, v_count2 - 1)

                # C. Pipeline Otimizada
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

                # D. Definir Mestra e Conexão de Saída para este par
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

                # E. Escrita dos Resultados no Sink
                if not order_field:
                    # No modo automático, o ID original está no primeiro atributo da feição dummy
                    orig_id = f1.attributes()[0]
                else:
                    orig_id = f1.id()
                
                for res in mestra_final_par:
                    attrs = [str(group_val), orig_id, par_id, res['dist']] if group_field else [orig_id, par_id, res['dist']]
                    feat = VectorUtils.create_feature(res['geom'], fields_mestra, attrs)
                    sink_mestra.addFeature(feat, QgsFeatureSink.FastInsert)

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

            # Progresso baseado nos grupos processados
            feedback.setProgress(int(((g_idx + 1) / total_groups) * 100))

        return {
            self.OUTPUT: dest_id_mestra, 
            self.CONEXAO_OUTPUT: dest_id_conexao
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