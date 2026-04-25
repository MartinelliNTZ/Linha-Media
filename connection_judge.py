# -*- coding: utf-8 -*-

from qgis.core import QgsGeometry, QgsPointXY
from .vector_utils import VectorUtils

class ConnectionJudge:
    """
    Classe responsável por tomar decisões complexas de conectividade entre camadas.
    Implementa a lógica de preenchimento de vértices órfãos.
    """

    @staticmethod
    def generate_nearest_with_orphans(base_geom, target_geom):
        """
        Gera conexões de menor distância garantindo que nenhum vértice da linha alvo fique órfão.
        
        Lógica:
        1. Cada vértice da base se liga ao ponto mais próximo da linha alvo.
        2. Vértices da alvo que não receberam conexões (órfãos) são identificados.
        3. Órfãos de início/fim ligam-se às extremidades da base.
        4. Órfãos do meio ligam-se ao centroide dos limites de 'adoção' na base.
        """
        base_verts = [QgsPointXY(v.x(), v.y()) for v in base_geom.vertices()]
        target_verts = [QgsPointXY(v.x(), v.y()) for v in target_geom.vertices()]
        
        if not base_verts or not target_verts:
            return []

        final_connections = []
        
        # Dicionário para rastrear quais vértices do alvo foram "atingidos"
        # target_idx -> list of base_indices
        target_coverage = {i: [] for i in range(len(target_verts))}

        # Passo 1: Base -> Target (Nearest Point)
        for b_idx, b_pt in enumerate(base_verts):
            # Encontra o ponto mais próximo na geometria (não apenas vértices)
            nearest_g = target_geom.nearestPoint(QgsGeometry.fromPointXY(b_pt))
            if not nearest_g.isEmpty():
                target_pt = nearest_g.asPoint()
                final_connections.append(QgsGeometry.fromPolylineXY([b_pt, target_pt]))
                
                # Identifica qual vértice do alvo está mais próximo deste ponto de impacto
                # Isso define quem "adotou" este ponto na linha alvo
                t_idx = ConnectionJudge._find_nearest_vertex_index(target_pt, target_verts)
                target_coverage[t_idx].append(b_idx)

        # Passo 2: Identificar Órfãos no Target
        orphans = [i for i, base_indices in target_coverage.items() if not base_indices]
        if not orphans:
            return final_connections

        # Passo 3: Lógica do Juiz para Órfãos
        hit_indices = sorted([i for i, base_indices in target_coverage.items() if base_indices])
        
        for o_idx in orphans:
            # Caso A: Órfãos antes do primeiro acerto (Início)
            if not hit_indices or o_idx < hit_indices[0]:
                # Liga ao primeiro ponto da base que teve um acerto
                target_pt = target_verts[o_idx]
                base_ref_idx = target_coverage[hit_indices[0]][0] if hit_indices else 0
                final_connections.append(QgsGeometry.fromPolylineXY([target_verts[o_idx], base_verts[base_ref_idx]]))
            
            # Caso B: Órfãos após o último acerto (Fim)
            elif o_idx > hit_indices[-1]:
                target_pt = target_verts[o_idx]
                base_ref_idx = target_coverage[hit_indices[-1]][-1]
                final_connections.append(QgsGeometry.fromPolylineXY([target_verts[o_idx], base_verts[base_ref_idx]]))
            
            # Caso C: Órfãos no meio (Centroide dos vizinhos)
            else:
                # Encontra quem são os vizinhos adotivos
                prev_t_idx = max([i for i in hit_indices if i < o_idx])
                next_t_idx = min([i for i in hit_indices if i > o_idx])
                
                # Pega o último da esquerda e o primeiro da direita na base
                b_idx_left = target_coverage[prev_t_idx][-1]
                b_idx_right = target_coverage[next_t_idx][0]
                
                mid_pt = VectorUtils.get_midpoint(base_verts[b_idx_left], base_verts[b_idx_right])
                final_connections.append(QgsGeometry.fromPolylineXY([target_verts[o_idx], mid_pt]))

        return final_connections

    @staticmethod
    def _find_nearest_vertex_index(point, vertices):
        """Auxiliar para encontrar o índice do vértice mais próximo."""
        min_dist = float('inf')
        idx = 0
        for i, v in enumerate(vertices):
            d = point.distance(v)
            if d < min_dist:
                min_dist = d
                idx = i
        return idx

    @staticmethod
    def solve_nearest_with_criteria(geom1, geom2, criteria_idx):
        """
        Executa o julgamento para decidir qual linha será a base conforme o critério.
        0: menor tamanho, 1: maior tamanho, 2: menor angulo, 3: maior angulo, 4: qualquer
        """
        use_g1_as_base = True
        
        if criteria_idx == 0: # Menor Tamanho
            use_g1_as_base = geom1.length() <= geom2.length()
        elif criteria_idx == 1: # Maior Tamanho
            use_g1_as_base = geom1.length() >= geom2.length()
        elif criteria_idx == 2: # Menor Ângulo (Mais fechada/curva)
            use_g1_as_base = VectorUtils.get_line_straightness_score(geom1) <= VectorUtils.get_line_straightness_score(geom2)
        elif criteria_idx == 3: # Maior Ângulo (Mais aberta/reta)
            use_g1_as_base = VectorUtils.get_line_straightness_score(geom1) >= VectorUtils.get_line_straightness_score(geom2)
        # else: criteria_idx == 4 ou empate -> use_g1_as_base = True

        if use_g1_as_base:
            results = ConnectionJudge.generate_nearest_with_orphans(geom1, geom2)
        else:
            results = ConnectionJudge.generate_nearest_with_orphans(geom2, geom1)
            
        return [{'geom': g, 'id': i+1} for i, g in enumerate(results)]