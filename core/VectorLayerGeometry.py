# -*- coding: utf-8 -*-

import math
from qgis.core import QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature
from .vector_utils import VectorUtils # Import VectorUtils for _get_closest_point

class VectorLayerGeometry: # Renomeado de VectorLayerGeometry para melhor clareza
    """Classe genérica para manipulação de geometrias de camadas vetoriais."""

    @staticmethod
    def get_trimmed_ray(p_start, azimuth, max_length, spatial_index=None, feat_dict=None, exclude_id=-1, mother_geoms=None):
        """
        Gera uma geometria de raio a partir de um ponto, cortando-a se houver colisão.
        Reutilizável por diversos algoritmos de sensores.
        
        Args:
            p_start (QgsPointXY): Ponto de origem do raio.
            azimuth (float): Azimute do raio em graus.
            max_length (float): Comprimento máximo do raio.
            spatial_index (QgsSpatialIndex, optional): Índice espacial para colisões com outras feições.
            feat_dict (dict, optional): Dicionário de feições para acesso rápido pelo ID.
            exclude_id (int, optional): ID de uma feição a ser ignorada na colisão (ex: a própria linha).
            mother_geoms (list, optional): Lista de geometrias "mães" para colisão prioritária.
            
        Returns:
            tuple: (QgsGeometry do raio cortado, ID da feição que causou a colisão ou -1)
        """
        rad = math.radians(azimuth)
        p_target = QgsPointXY(
            p_start.x() + max_length * math.sin(rad),
            p_start.y() + max_length * math.cos(rad)
        )
        
        ray_geom = QgsGeometry.fromPolylineXY([p_start, p_target])
        min_dist = float(max_length)
        final_p_end = p_target
        hit_id = -1

        # 1. Intersecção com Linhas Mães (se houver)
        if mother_geoms:
            for m_geom in mother_geoms:
                if m_geom and not m_geom.isEmpty():
                    inter = ray_geom.intersection(m_geom)
                    if not inter.isEmpty():
                        pt = VectorUtils._get_closest_point(inter, p_start)
                        if pt:
                            d = p_start.distance(pt)
                            if d < min_dist:
                                min_dist = d
                                final_p_end = pt

        # 2. Intersecção com outras curvas via Spatial Index
        if spatial_index and feat_dict:
            candidates = spatial_index.intersects(ray_geom.boundingBox())
            for c_id in candidates:
                if c_id == exclude_id: continue
                inter = ray_geom.intersection(feat_dict[c_id].geometry())
                if not inter.isEmpty():
                    pt = VectorUtils._get_closest_point(inter, p_start)
                    if pt:
                        d = p_start.distance(pt)
                        if 0.001 < d < min_dist: # Margem para evitar auto-colisão em junções
                            min_dist = d
                            final_p_end = pt
                            hit_id = c_id
        
        return QgsGeometry.fromPolylineXY([p_start, final_p_end]), hit_id

    @staticmethod
    def generate_perpendicular_sensors(points, key_prim, sensor_limit, spatial_index, feat_dict, feature_id, perp_fields, vert_fields, mother_geoms=None, fid_to_key_prim=None, start_sec_counter=0):
        """
        Gera feições de sensores perpendiculares para uma lista de pontos ao longo de uma linha.
        """
        sensor_features = []
        vertex_features = []
        
        sec_counter = start_sec_counter
        prev_neighbors = (None, None)

        for i, p in enumerate(points):
            key_vertex = f"{key_prim}_{i:04d}"
            p_start = QgsPointXY(p.x(), p.y())
            az_local = VectorUtils.get_vertex_azimuth(points, i)
            
            # Armazenamento temporário para os vizinhos detectados em cada lado
            vertex_neighbors = {'d': None, 'e': None}
            
            for angle_offset in [90, -90]:
                az_ray = (az_local + angle_offset) % 360
                side = 'd' if angle_offset == 90 else 'e'
                key_s1 = f"{key_vertex}{side}"
                
                # Reaproveita a lógica centralizada de corte por colisão
                final_geom, hit_id = VectorLayerGeometry.get_trimmed_ray(
                    p_start, az_ray, sensor_limit, spatial_index, feat_dict, feature_id, mother_geoms
                )

                neighbor_key = None
                if hit_id != -1 and fid_to_key_prim:
                    neighbor_key = fid_to_key_prim.get(hit_id)
                
                vertex_neighbors[side] = neighbor_key

                perp_feat = QgsFeature(perp_fields)
                perp_feat.setGeometry(final_geom)
                perp_feat.setAttributes([key_prim, key_vertex, key_s1, side, neighbor_key])
                sensor_features.append(perp_feat)

            # Lógica de agrupamento para keySec
            current_neighbors = (vertex_neighbors['e'], vertex_neighbors['d'])
            if i > 0:
                # Se qualquer um dos vizinhos mudar em relação ao vértice anterior, incrementa o grupo
                if current_neighbors != prev_neighbors:
                    sec_counter += 1
            
            key_sec = f"S{sec_counter:04d}"
            prev_neighbors = current_neighbors

            # Cria a feição de ponto (Vértice) para o output de pontos
            vert_feat = QgsFeature(vert_fields)
            vert_feat.setGeometry(QgsGeometry.fromPointXY(p_start))
            vert_feat.setAttributes([key_prim, key_vertex, key_sec, vertex_neighbors['e'], vertex_neighbors['d']])
            vertex_features.append(vert_feat)

        return sensor_features, vertex_features, sec_counter

    @staticmethod
    def adjust_line_length(geometry, delta):
        """
        Estende ou reduz uma linha em ambas as extremidades.
        delta > 0: Estende a linha para fora.
        delta < 0: Reduz a linha para dentro (trim).
        """
        if geometry.isEmpty():
            return geometry

        is_multi = geometry.isMultipart()
        parts = geometry.asMultiPolyline() if is_multi else [geometry.asPolyline()]
        new_parts = []

        for polyline in parts:
            if len(polyline) < 2:
                new_parts.append(polyline)
                continue
            
            new_poly = list(polyline)
            
            # Ajuste do Início (Vértice 0)
            # Vetor do segundo para o primeiro ponto para definir a direção de saída
            p0 = polyline[0]
            p1 = polyline[1]
            dx0 = p0.x() - p1.x()
            dy0 = p0.y() - p1.y()
            dist0 = math.sqrt(dx0**2 + dy0**2)
            
            if dist0 > 0:
                new_poly[0] = QgsPointXY(p0.x() + (dx0/dist0) * delta, 
                                         p0.y() + (dy0/dist0) * delta)
            
            # Ajuste do Fim (Vértice n)
            # Vetor do penúltimo para o último ponto para definir a direção de saída
            pn = polyline[-1]
            pn_1 = polyline[-2]
            dxn = pn.x() - pn_1.x()
            dyn = pn.y() - pn_1.y()
            distn = math.sqrt(dxn**2 + dyn**2)
            
            if distn > 0:
                new_poly[-1] = QgsPointXY(pn.x() + (dxn/distn) * delta, 
                                          pn.y() + (dyn/distn) * delta)
            
            new_parts.append(new_poly)

        if is_multi:
            return QgsGeometry.fromMultiPolylineXY(new_parts)
        else:
            return QgsGeometry.fromPolylineXY(new_parts[0])