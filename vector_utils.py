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
            # reverse() inverte a ordem dos vértices e das partes (no caso de multi)
            new_geom = QgsGeometry(geom)
            new_geom.reverse()
            return new_geom
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
    def generate_linhamestra_elements(geom1, geom2, partitions, feedback=None):
        """
        Orquestra o fluxo completo de geração da linha mestra.
        Retorna (lista_segmentos_mestra, lista_conexoes_transversais).
        """
        g1 = VectorUtils.orient_northwest(geom1)
        g2 = VectorUtils.orient_northwest(geom2)
        
        dados = VectorUtils.calculate_interpolation_data(g1, g2, partitions, feedback)
        
        mestra_segments = []
        connections = []
        
        total = len(dados)
        for i in range(total):
            if feedback and feedback.isCanceled(): break
            
            item = dados[i]
            # Guardamos os dados brutos para o orquestrador montar as feições
            if i < total - 1:
                proximo = dados[i+1]
                geom_mestra = QgsGeometry.fromPolylineXY([item['centro'], proximo['centro']])
                mestra_segments.append({
                    'geom': geom_mestra, 
                    'dist': item['dist'],
                    'id': i + 1
                })
            
            geom_conn = QgsGeometry.fromPolylineXY([item['p1'], item['p2']])
            connections.append({
                'geom': geom_conn,
                'id': i + 1
            })
            
        return mestra_segments, connections

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