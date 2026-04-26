# -*- coding: utf-8 -*-

import math
from qgis.core import (QgsGeometry, 
                       QgsPointXY, 
                       QgsFeature,
                       QgsCoordinateTransform,
                       QgsWkbTypes)

class VectorUtils:
    """Classe utilitária para operações vetoriais genéricas."""

    @staticmethod
    def reproject_geometry(geom, source_crs, target_crs, context):
        """Reprojeta uma geometria para um CRS de destino."""
        if source_crs == target_crs:
            return geom
        transform = QgsCoordinateTransform(source_crs, target_crs, context.transformContext())
        new_geom = QgsGeometry(geom)
        new_geom.transform(transform)
        return new_geom

    @staticmethod
    def reverse_geometry(geom):
        """Inverte a direção de uma geometria linear (compatível com QGIS < 3.18)."""
        if geom.isMultipart():
            multi_poly = geom.asMultiPolyline()
            # Inverte a ordem das partes e os vértices dentro de cada parte
            reversed_multi = [part[::-1] for part in reversed(multi_poly)]
            return QgsGeometry.fromMultiPolylineXY(reversed_multi)
        else:
            poly = geom.asPolyline()
            return QgsGeometry.fromPolylineXY(poly[::-1])

    @staticmethod
    def get_midpoint(p1, p2):
        """Calcula o ponto médio entre dois objetos QgsPointXY."""
        return QgsPointXY((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)

    @staticmethod
    def extract_two_features(source1, source2, context):
        """
        Extrai exatamente duas feições de uma ou duas fontes.
        Retorna (feat1, feat2, crs) ou (None, None, None) se a seleção for inválida.
        """
        features1 = list(source1.getFeatures())
        
        if source2 is None:
            if len(features1) != 2:
                return None, None, None
            return features1[0], features1[1], source1.sourceCrs()
        
        features2 = list(source2.getFeatures())
        if len(features1) != 1 or len(features2) != 1:
            return None, None, None
            
        feat1, feat2 = features1[0], features2[0]
        if source1.sourceCrs() != source2.sourceCrs():
            geom2 = VectorUtils.reproject_geometry(feat2.geometry(), source2.sourceCrs(), source1.sourceCrs(), context)
            feat2.setGeometry(geom2)
            
        return feat1, feat2, source1.sourceCrs()

    @staticmethod
    def orient_northwest(geom):
        """Inverte a linha se o final for mais ao Norte/Oeste que o início."""
        if geom.isEmpty():
            return geom
            
        # vertices() funciona para LineString e MultiLineString de forma transparente
        nodes = list(geom.vertices())
        if len(nodes) < 2:
            return geom
        
        inicio = nodes[0]
        fim = nodes[-1]

        # Critério NO: Menor X (Oeste), se empate, maior Y (Norte)
        def score_no(pt):
            return (pt.x(), -pt.y())

        if score_no(fim) < score_no(inicio):
            return VectorUtils.reverse_geometry(geom)
        return geom

    @staticmethod
    def get_line_azimuths(geom):
        """Retorna uma lista de azimutes para cada segmento da geometria."""
        azimuths = []
        # asMultiPolyline lida com MultiLineString; asPolyline com LineString
        parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
        
        for part in parts:
            if not part: continue
            for i in range(len(part) - 1):
                # QgsPointXY.azimuth() retorna graus
                azimuths.append(part[i].azimuth(part[i+1]))
        return azimuths

    @staticmethod
    def analyze_straightness(geom, threshold):
        """Analisa se a linha é reta e retorna (is_straight, avg_az, max_dev)."""
        azs = VectorUtils.get_line_azimuths(geom)
        if not azs:
            return False, 0, 0
            
        if len(azs) == 1:
            return True, azs[0], 0
            
        avg_az = sum(azs) / len(azs)
        max_dev = 0
        is_straight = True
        
        for az in azs:
            diff = abs(az - avg_az)
            if diff > 180: diff = 360 - diff
            max_dev = max(max_dev, diff)
            if diff > threshold:
                is_straight = False
        return is_straight, avg_az, max_dev

    @staticmethod
    def get_projection_value(point, azimuth_deg):
        """Calcula o valor de projeção espacial perpendicular ao azimute para ordenação."""
        rad = math.radians(azimuth_deg)
        return -point.x() * math.sin(rad) + point.y() * math.cos(rad)

    @staticmethod
    def calculate_internal_angle(p1, p2, p3):
        """Calcula o ângulo interno em p2 formado pelos segmentos p1-p2 e p2-p3."""
        v1 = (p1.x() - p2.x(), p1.y() - p2.y())
        v2 = (p3.x() - p2.x(), p3.y() - p2.y())
        dot = v1[0]*v2[0] + v1[1]*v2[1]
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
        if mag1 == 0 or mag2 == 0: return 180.0
        cos_theta = max(-1.0, min(1.0, dot / (mag1 * mag2)))
        return math.degrees(math.acos(cos_theta))

    @staticmethod
    def get_line_straightness_score(geom):
        """Mede quão 'aberta' é a linha baseada na média de ângulos de 5 pontos amostrados."""
        length = geom.length()
        if length == 0: return 180.0
        # Amostra 5 pontos uniformemente (0%, 25%, 50%, 75%, 100%)
        pts = [QgsPointXY(geom.interpolate(length * (i/4.0)).asPoint().x(), 
                         geom.interpolate(length * (i/4.0)).asPoint().y()) for i in range(5)]
        # Ângulos nos pontos internos
        a1 = VectorUtils.calculate_internal_angle(pts[0], pts[1], pts[2])
        a2 = VectorUtils.calculate_internal_angle(pts[1], pts[2], pts[3])
        a3 = VectorUtils.calculate_internal_angle(pts[2], pts[3], pts[4])
        return (a1 + a2 + a3) / 3.0

    @staticmethod
    def _get_closest_point(geom, ref_point):
        """Extrai o ponto mais próximo de um ponto de referência a partir de uma geometria."""
        if geom is None or geom.isEmpty():
            return None
        
        # No QGIS 3.16, asPoint() pode retornar QgsPoint. 
        # Forçamos QgsPointXY para compatibilidade com construtores de geometria.
        nearest_geom = geom.nearestPoint(QgsGeometry.fromPointXY(ref_point))
        if not nearest_geom.isEmpty():
            pt = nearest_geom.asPoint()
            return QgsPointXY(pt.x(), pt.y())
            
        return None

    @staticmethod
    def align_line_pair(geom1, geom2):
        """
        Prepara o 'casamento' das linhas:
        1. Orienta a primeira para Noroeste.
        2. Orienta a segunda para que seu início seja o mais próximo possível do início da primeira.
        """
        g1 = VectorUtils.orient_northwest(geom1)
        
        nodes1 = list(g1.vertices())
        nodes2 = list(geom2.vertices())
        
        if not nodes1 or not nodes2:
            return g1, geom2
            
        p1_start = QgsPointXY(nodes1[0].x(), nodes1[0].y())
        p2_start = QgsPointXY(nodes2[0].x(), nodes2[0].y())
        p2_end = QgsPointXY(nodes2[-1].x(), nodes2[-1].y())
        
        # Se o início da g1 está mais perto do fim da g2, inverte g2 para alinhar o par
        if p1_start.distance(p2_start) > p1_start.distance(p2_end):
            return g1, VectorUtils.reverse_geometry(geom2)
            
        return g1, geom2

    @staticmethod
    def decide_base_by_endpoint(geom1, geom2):
        """
        Decide qual linha deve ser a 'Base' (Pai) usando a lógica de sincronismo:
        Retorna True se geom1 for a base, False se for geom2.
        """
        def check_endpoint(pt, target_geom):
            nearest_pt = target_geom.nearestPoint(QgsGeometry.fromPointXY(pt)).asPoint()
            nodes = list(target_geom.vertices())
            d_start = nearest_pt.distance(QgsPointXY(nodes[0].x(), nodes[0].y()))
            d_end = nearest_pt.distance(QgsPointXY(nodes[-1].x(), nodes[-1].y()))
            # Consideramos 'meio' se estiver a mais de 1cm das pontas
            is_mid = d_start > 0.01 and d_end > 0.01
            return is_mid, pt.distance(nearest_pt)

        v1 = list(geom1.vertices())
        v2 = list(geom2.vertices())
        if not v1 or not v2: return True

        tests = [
            ('L1', check_endpoint(QgsPointXY(v1[0].x(), v1[0].y()), geom2)),
            ('L1', check_endpoint(QgsPointXY(v1[-1].x(), v1[-1].y()), geom2)),
            ('L2', check_endpoint(QgsPointXY(v2[0].x(), v2[0].y()), geom1)),
            ('L2', check_endpoint(QgsPointXY(v2[-1].x(), v2[-1].y()), geom1))
        ]

        # Prioridade 1: Quem liga no meio ganha (is_mid == True)
        mids = [t for t in tests if t[1][0]]
        if mids:
            winner = min(mids, key=lambda x: x[1][1])
            return winner[0] == 'L1'

        # Prioridade 2: Menor distância absoluta entre pontas
        winner = min(tests, key=lambda x: x[1][1])
        return winner[0] == 'L1'

    @staticmethod
    def align_by_endpoint_logic(geom1, geom2):
        """
        Determina Pai/Mãe e alinhamento baseado na regra:
        1. Verifica qual ponta de uma linha se liga ao meio da outra.
        2. Desempate por menor distância entre ponta e ponto mais próximo.
        Retorna (geom_pai, geom_mae, invert_pai, invert_mae)
        """
        def check_endpoint(pt, target_geom):
            nearest_pt = target_geom.nearestPoint(QgsGeometry.fromPointXY(pt)).asPoint()
            # Verifica se está no 'meio' (longe das pontas da target)
            nodes = list(target_geom.vertices())
            d_start = nearest_pt.distance(QgsPointXY(nodes[0].x(), nodes[0].y()))
            d_end = nearest_pt.distance(QgsPointXY(nodes[-1].x(), nodes[-1].y()))
            is_mid = d_start > 0.01 and d_end > 0.01
            return is_mid, pt.distance(nearest_pt), nearest_pt

        v1 = list(geom1.vertices())
        v2 = list(geom2.vertices())
        
        # Testes: (LinhaOrigem, PontaIdx, Target)
        tests = [
            ('L1', 0, geom2, QgsPointXY(v1[0].x(), v1[0].y())),
            ('L1', -1, geom2, QgsPointXY(v1[-1].x(), v1[-1].y())),
            ('L2', 0, geom1, QgsPointXY(v2[0].x(), v2[0].y())),
            ('L2', -1, geom1, QgsPointXY(v2[-1].x(), v2[-1].y()))
        ]

        results = []
        for label, idx, target, pt in tests:
            is_mid, dist, target_pt = check_endpoint(pt, target)
            results.append({'label': label, 'idx': idx, 'is_mid': is_mid, 'dist': dist, 'pt': pt, 'target_pt': target_pt})

        # Critério 1: Quem liga no meio ganha
        mids = [r for r in results if r['is_mid']]
        if mids:
            winner = min(mids, key=lambda x: x['dist'])
        else:
            # Critério 2: Menor distância absoluta
            winner = min(results, key=lambda x: x['dist'])

        if winner['label'] == 'L1':
            pai = VectorUtils.reverse_geometry(geom1) if winner['idx'] == -1 else geom1
            # Alinha mãe com o ponto de impacto
            nodes_pai = list(pai.vertices())
            p_start_pai = QgsPointXY(nodes_pai[0].x(), nodes_pai[0].y())
            mae = geom2
            # Verifica se a mãe precisa inverter para o início estar perto do pai
            if p_start_pai.distance(QgsPointXY(v2[0].x(), v2[0].y())) > p_start_pai.distance(QgsPointXY(v2[-1].x(), v2[-1].y())):
                mae = VectorUtils.reverse_geometry(geom2)
            return pai, mae
        else:
            pai = VectorUtils.reverse_geometry(geom2) if winner['idx'] == -1 else geom2
            nodes_pai = list(pai.vertices())
            p_start_pai = QgsPointXY(nodes_pai[0].x(), nodes_pai[0].y())
            mae = geom1
            if p_start_pai.distance(QgsPointXY(v1[0].x(), v1[0].y())) > p_start_pai.distance(QgsPointXY(v1[-1].x(), v1[-1].y())):
                mae = VectorUtils.reverse_geometry(geom1)
            return pai, mae

    @staticmethod
    def get_points_at_interval(geom, interval):
        """Gera pontos ao longo da linha a cada intervalo fixo de metros."""
        length = geom.length()
        num_points = int(length / interval) + 1
        points = []
        for i in range(num_points):
            points.append(geom.interpolate(i * interval).asPoint())
        return points

    @staticmethod
    def generate_1to1_connections(geom_pai, geom_mae, interval):
        """Gera conexões 1:1 baseadas em distância fixa."""
        pts_pai = VectorUtils.get_points_at_interval(geom_pai, interval)
        pts_mae = VectorUtils.get_points_at_interval(geom_mae, interval)
        
        connections = []
        limit = min(len(pts_pai), len(pts_mae))
        
        for i in range(limit):
            p1 = pts_pai[i]
            p2 = pts_mae[i]
            connections.append({
                'geom': QgsGeometry.fromPolylineXY([p1, p2]),
                'id': i + 1,
                'id_pai': float(i),
                'id_mae': float(i),
                'id_origem': float(i + 1)
            })
        return connections

    @staticmethod
    def generate_linhamestra_elements(geom1, geom2, partitions, feedback=None):
        """
        Orquestra o fluxo completo de geração da linha mestra.
        Retorna (mestra, conexoes, perpendiculares, mais_proximo_1, mais_proximo_2).
        """
        # 1. Prepara o casamento (Alinhamento)
        g1, g2 = VectorUtils.align_line_pair(geom1, geom2)
        
        # 3. Agora a interpolação ocorrerá entre pontos homólogos (início com início)
        dados = VectorUtils.calculate_interpolation_data(g1, g2, partitions, feedback)
        
        if not dados:
            if feedback: feedback.reportError("Falha ao gerar dados de interpolação.")
            return [], [], [], [], []

        mestra_segments = []
        connections = []
        perpendiculars = []
        
        total = len(dados)
        for i in range(total):
            if feedback and feedback.isCanceled(): break
            
            item = dados[i]
            p_curr = item['centro']

            # 1. Gerar Segmento da Linha Mestra
            if i < total - 1:
                proximo = dados[i+1]
                geom_mestra = QgsGeometry.fromPolylineXY([p_curr, proximo['centro']])
                mestra_segments.append({
                    'geom': geom_mestra, 
                    'dist': item['dist'],
                    'id': i + 1
                })
            
            # 2. Gerar Conexão Direta (Interpolação simples)
            connections.append({
                'geom': QgsGeometry.fromPolylineXY([item['p1'], item['p2']]),
                'id': i + 1
            })
            
            # 3. Gerar Linha Perpendicular (Bissetriz nos vértices da mestra)
            if total >= 2:
                # Cálculo do azimute local (direção da mestra)
                if i == 0:
                    # No início, usa a direção do primeiro segmento
                    az_mestra = p_curr.azimuth(dados[i+1]['centro'])
                elif i == total - 1:
                    # No final, usa a direção do último segmento
                    az_mestra = dados[i-1]['centro'].azimuth(p_curr)
                else:
                    az1 = dados[i-1]['centro'].azimuth(p_curr)
                    az2 = p_curr.azimuth(dados[i+1]['centro'])
                    diff = az2 - az1
                    if diff > 180: diff -= 360 
                    if diff < -180: diff += 360
                    az_mestra = (az1 + diff / 2.0) % 360

                perp_az = (az_mestra + 90) % 360
                ext = 10000.0 
                half_dist = item['dist'] / 2.0

                # --- Lógica de Corte Estrito ---
                # Raio 1: Direção A
                p_ext1 = QgsPointXY(p_curr.x() + ext * math.sin(math.radians(perp_az)),
                                   p_curr.y() + ext * math.cos(math.radians(perp_az)))
                ray1 = QgsGeometry.fromPolylineXY([p_curr, p_ext1])
                
                pts1 = []
                for m_geom in [g1, g2]:
                    p_int = VectorUtils._get_closest_point(m_geom.intersection(ray1), p_curr)
                    if p_int: pts1.append(p_int)
                
                # Se não intersectar a mãe, usamos a distância média para manter a linha RETA
                pt1 = min(pts1, key=lambda p: p.distance(p_curr)) if pts1 else \
                      QgsPointXY(p_curr.x() + half_dist * math.sin(math.radians(perp_az)),
                                 p_curr.y() + half_dist * math.cos(math.radians(perp_az)))

                # Raio 2: Direção B (oposta)
                p_ext2 = QgsPointXY(p_curr.x() + ext * math.sin(math.radians((perp_az + 180) % 360)),
                                   p_curr.y() + ext * math.cos(math.radians((perp_az + 180) % 360)))
                ray2 = QgsGeometry.fromPolylineXY([p_curr, p_ext2])
                
                pts2 = []
                for m_geom in [g1, g2]:
                    p_int = VectorUtils._get_closest_point(m_geom.intersection(ray2), p_curr)
                    if p_int: pts2.append(p_int)
                
                pt2 = min(pts2, key=lambda p: p.distance(p_curr)) if pts2 else \
                      QgsPointXY(p_curr.x() + half_dist * math.sin(math.radians((perp_az + 180) % 360)),
                                 p_curr.y() + half_dist * math.cos(math.radians((perp_az + 180) % 360)))
                
                perpendiculars.append({
                    'geom': QgsGeometry.fromPolylineXY([pt1, pt2]),
                    'id': i + 1
                })
            
            if feedback and i % 100 == 0:
                feedback.pushInfo(f"Processando ponto {i}/{total}...")
            
        return mestra_segments, connections, perpendiculars

    @staticmethod
    def generate_perpendiculars_from_line_vertices(input_line_geom, mother_line1_geom=None, mother_line2_geom=None, fixed_distance=None, feedback=None):
        """
        Gera linhas perpendiculares em cada vértice de uma geometria de linha.
        A direção da perpendicular é a bissetriz do ângulo formado pelos segmentos adjacentes.
        
        Args:
            input_line_geom (QgsGeometry): A geometria da linha de entrada.
            mother_line1_geom (QgsGeometry, optional): A primeira linha mãe para intersecção.
            mother_line2_geom (QgsGeometry, optional): A segunda linha mãe para intersecção.
            fixed_distance (float, optional): Distância fixa para as perpendiculares se não houver linhas mães.
            feedback (QgsProcessingFeedback, optional): Objeto de feedback para progresso.
            
        Returns:
            list: Uma lista de geometrias QgsGeometry das linhas perpendiculares.
        """
        perpendicular_geoms = []
        
        if input_line_geom.isEmpty():
            if feedback: feedback.pushInfo("Geometria de entrada vazia, pulando.")
            return []
            
        # Processa cada parte da geometria (se for MultiLineString)
        parts = input_line_geom.asMultiPolyline() if input_line_geom.isMultipart() else [input_line_geom.asPolyline()]
        
        for part_idx, polyline in enumerate(parts):
            if not polyline or len(polyline) < 2:
                if feedback: feedback.pushInfo(f"Parte {part_idx} da geometria de entrada tem menos de 2 vértices, pulando.")
                continue
            
            total_vertices = len(polyline)
            for i in range(total_vertices):
                if feedback and feedback.isCanceled(): return []
                
                p_curr = QgsPointXY(polyline[i].x(), polyline[i].y())
                
                # Calcula o azimute local (bissetriz para vértices internos, segmento único para extremidades)
                az_mestra = 0.0
                if i == 0: # Primeiro vértice
                    az_mestra = p_curr.azimuth(polyline[i+1])
                elif i == total_vertices - 1: # Último vértice
                    az_mestra = polyline[i-1].azimuth(p_curr)
                else: # Vértice interno
                    az1 = polyline[i-1].azimuth(p_curr)
                    az2 = p_curr.azimuth(polyline[i+1])
                    
                    # Calcula o ângulo bissetor, tratando a quebra 0/360
                    diff = az2 - az1
                    if diff > 180: diff -= 360 
                    if diff < -180: diff += 360
                    az_mestra = (az1 + diff / 2.0) % 360

                perp_az = (az_mestra + 90) % 360
                
                if mother_line1_geom and mother_line2_geom:
                    # Cenário 1: Intersectar com as linhas mães
                    ext_max = 10000.0
                    # Raio 1
                    p_ext1 = QgsPointXY(p_curr.x() + ext_max * math.sin(math.radians(perp_az)), 
                                        p_curr.y() + ext_max * math.cos(math.radians(perp_az)))
                    ray1 = QgsGeometry.fromPolylineXY([p_curr, p_ext1])
                    pts1 = []
                    for m_geom in [mother_line1_geom, mother_line2_geom]:
                        p_int = VectorUtils._get_closest_point(m_geom.intersection(ray1), p_curr)
                        if p_int: pts1.append(p_int)
                    pt1 = min(pts1, key=lambda p: p.distance(p_curr)) if pts1 else None

                    # Raio 2
                    p_ext2 = QgsPointXY(p_curr.x() + ext_max * math.sin(math.radians((perp_az + 180) % 360)),
                                        p_curr.y() + ext_max * math.cos(math.radians((perp_az + 180) % 360)))
                    ray2 = QgsGeometry.fromPolylineXY([p_curr, p_ext2])
                    pts2 = []
                    for m_geom in [mother_line1_geom, mother_line2_geom]:
                        p_int = VectorUtils._get_closest_point(m_geom.intersection(ray2), p_curr)
                        if p_int: pts2.append(p_int)
                    pt2 = min(pts2, key=lambda p: p.distance(p_curr)) if pts2 else None
                    
                    if pt1 and pt2:
                        perpendicular_geoms.append(QgsGeometry.fromPolylineXY([pt1, pt2]))
                    elif pt1 or pt2:
                        # Se apenas um lado intersectar, usamos a distância fixa para o outro lado para não entortar
                        half = fixed_distance / 2.0 if fixed_distance else 10.0
                        p_other = pt2 if pt1 else pt1 # Lógica de fallback para manter reta
                    elif feedback:
                        feedback.pushInfo(f"Falha na intersecção para vértice {i} da parte {part_idx}. Linha perpendicular não gerada.")
                else:
                    # Cenário 2: Distância fixa
                    half_dist = fixed_distance / 2.0
                    rad = math.radians(perp_az)
                    p_start = QgsPointXY(p_curr.x() - half_dist * math.sin(rad), p_curr.y() - half_dist * math.cos(rad))
                    p_end = QgsPointXY(p_curr.x() + half_dist * math.sin(rad), p_curr.y() + half_dist * math.cos(rad))
                    perpendicular_geoms.append(QgsGeometry.fromPolylineXY([p_start, p_end]))
                    
        return perpendicular_geoms

    @staticmethod
    def create_feature(geometry, fields, attributes):
        """Cria uma QgsFeature genérica com geometria e atributos."""
        feat = QgsFeature(fields)
        feat.setGeometry(geometry)
        feat.setAttributes(attributes)
        return feat

    @staticmethod
    def calculate_interpolation_data(geom1, geom2, particoes, feedback=None):
        """
        Gera uma lista de dados de interpolação (pontos originais, centroide e distância) 
        entre duas geometrias lineares.
        """
        len1 = geom1.length()
        len2 = geom2.length()
        dados_particao = []

        for i in range(particoes + 1):
            if feedback and feedback.isCanceled():
                break
            
            d1 = (len1 / particoes) * i
            d2 = (len2 / particoes) * i

            g1 = geom1.interpolate(d1)
            g2 = geom2.interpolate(d2)

            if g1.isNull() or g2.isNull():
                continue

            p1 = g1.asPoint()
            p2 = g2.asPoint()
            dist_mae = p1.distance(p2)
            centro = VectorUtils.get_midpoint(p1, p2)
            
            dados_particao.append({
                'p1': p1,
                'p2': p2,
                'centro': centro,
                'dist': dist_mae
            })
        
        return dados_particao

    @staticmethod
    def get_equidistant_points(geom, num_points):
        """Retorna uma lista de num_points pontos QgsPointXY uniformemente espaçados ao longo da geometria."""
        if geom.isEmpty():
            return []
        if num_points < 2:
            return [QgsPointXY(v.x(), v.y()) for v in geom.vertices()]
        
        length = geom.length()
        points = []
        for i in range(num_points):
            interpolated_geom = geom.interpolate((length / (num_points - 1)) * i)
            if not interpolated_geom.isEmpty():
                pt = interpolated_geom.asPoint()
                points.append(QgsPointXY(pt.x(), pt.y()))
        return points

    @staticmethod
    def generate_mestra_from_connections(connection_results):
        """
        Gera segmentos de linha mestra a partir de uma lista ordenada de conexões.
        """
        mestra_segments = []
        midpoints = []
        
        for res in connection_results:
            line = res['geom'].asPolyline()
            if len(line) >= 2:
                midpoints.append({'pt': VectorUtils.get_midpoint(line[0], line[1]), 'dist': res['geom'].length()})
        
        for i in range(len(midpoints) - 1):
            p_curr = midpoints[i]['pt']
            p_next = midpoints[i+1]['pt']
            geom_mestra = QgsGeometry.fromPolylineXY([p_curr, p_next])
            mestra_segments.append({
                'geom': geom_mestra,
                'dist': midpoints[i]['dist'],
                'id': i + 1
            })
        return mestra_segments

    @staticmethod
    def filter_connections(connections, g1, g2, crs, delta_m):
        """
        Filtra conexões que cruzam as linhas mãe.
        Reduz delta_m em cada ponta para evitar falsos positivos nos vértices de contato.
        """
        from .geometry_utils import VectorLayerGeometry
        
        # Converte metros para graus se o CRS for geográfico
        if crs.isGeographic():
            delta = 0.01 / 111120.0
            delta = delta_m / 111120.0
        else:
            delta = delta_m
            
        filtered = []
        for conn in connections:
            # Reduzimos a linha para teste de cruzamento
            test_geom = VectorLayerGeometry.adjust_line_length(conn['geom'], -delta)
            
            # Se a linha reduzida não cruza nenhuma das mães, ela é válida
            if not (test_geom.intersects(g1) or test_geom.intersects(g2)):
                filtered.append(conn)
                
        return filtered