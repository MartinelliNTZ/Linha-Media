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
    def _get_closest_point(geom, ref_point):
        """Extrai o ponto mais próximo de um ponto de referência a partir de uma geometria."""
        if not geom or geom.isEmpty():
            return None
            
        # O método nearestPoint é o mais robusto para encontrar a projeção em qualquer geometria.
        # No QGIS 3.16, asPoint() garante o retorno de um QgsPointXY.
        nearest_geom = geom.nearestPoint(QgsGeometry.fromPointXY(ref_point))
        if not nearest_geom.isEmpty():
            return nearest_geom.asPoint()
            
        # Fallback para vértices se nearestPoint falhar (converte explicitamente para PointXY)
        verts = [QgsPointXY(v.x(), v.y()) for v in geom.vertices()]
        return min(verts, key=lambda p: p.distance(ref_point)) if verts else None

    @staticmethod
    def generate_linhamestra_elements(geom1, geom2, partitions, feedback=None):
        """
        Orquestra o fluxo completo de geração da linha mestra.
        Retorna (lista_segmentos_mestra, lista_conexoes_transversais, lista_perpendiculares).
        """
        # 1. Normaliza a primeira linha para uma direção padrão (Noroeste)
        g1 = VectorUtils.orient_northwest(geom1)
        
        # 2. Garante que a segunda linha siga o mesmo sentido da primeira por proximidade
        g2 = geom2
        nodes1 = list(g1.vertices())
        nodes2 = list(g2.vertices())
        
        if nodes1 and nodes2:
            p1_start = QgsPointXY(nodes1[0].x(), nodes1[0].y())
            p2_start = QgsPointXY(nodes2[0].x(), nodes2[0].y())
            p2_end = QgsPointXY(nodes2[-1].x(), nodes2[-1].y())
            
            # Camada extra de validação:
            # Se o início de g1 estiver mais perto do FIM de g2 do que do INÍCIO de g2,
            # significa que g2 está invertida em relação ao par. Nós a corrigimos.
            if p1_start.distance(p2_start) > p1_start.distance(p2_end):
                g2 = VectorUtils.reverse_geometry(g2)
        
        # 3. Agora a interpolação ocorrerá entre pontos homólogos (início com início)
        dados = VectorUtils.calculate_interpolation_data(g1, g2, partitions, feedback)
        
        if not dados:
            if feedback: feedback.reportError("Falha ao gerar dados de interpolação.")
            return [], [], []

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
                # Exagero maior para garantir que cruze as linhas mãe mesmo em curvas
                ext = (item['dist'] + 1.0) * 10.0 
                
                rad1 = math.radians(perp_az)
                p_ext1 = QgsPointXY(p_curr.x() + ext * math.sin(rad1), p_curr.y() + ext * math.cos(rad1))
                rad2 = math.radians((perp_az + 180) % 360)
                p_ext2 = QgsPointXY(p_curr.x() + ext * math.sin(rad2), p_curr.y() + ext * math.cos(rad2))
                
                full_perp = QgsGeometry.fromPolylineXY([p_ext1, p_ext2])
                
                # Tenta intersecção exata
                inter1 = g1.intersection(full_perp)
                inter2 = g2.intersection(full_perp)
                
                pt1 = VectorUtils._get_closest_point(inter1, p_curr)
                pt2 = VectorUtils._get_closest_point(inter2, p_curr)
                
                # Fallback: Se a intersecção falhar, usamos o ponto interpolado original para não ficar vazio
                if pt1 is None: pt1 = item['p1']
                if pt2 is None: pt2 = item['p2']
                
                geom_perp = QgsGeometry.fromPolylineXY([pt1, pt2])
                perpendiculars.append({
                    'geom': geom_perp,
                    'id': i + 1
                })
            
            if feedback and i % 100 == 0:
                feedback.pushInfo(f"Processando ponto {i}/{total}...")
            
        return mestra_segments, connections, perpendiculars

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