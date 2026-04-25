# -*- coding: utf-8 -*-

from qgis.core import QgsGeometry, QgsPointXY
from .vector_utils import VectorUtils

class ConnectionJudge:
    """
    Classe responsável por tomar decisões complexas de conectividade entre camadas.
    Implementa a lógica de preenchimento de vértices órfãos.
    """

    @staticmethod
    def generate_nearest_with_orphans(base_geom, target_geom, target_n):
        """
        Gera conexões de menor distância garantindo que nenhum vértice da linha alvo fique órfão.
        Usa amostragem uniforme baseada em target_n para garantir densidade.
        """
        # Amostragem uniforme para garantir a quantidade de divisões solicitada
        # target_n é o número de segmentos, logo precisamos de n + 1 pontos
        base_verts = VectorUtils.get_equidistant_points(base_geom, target_n + 1)
        target_verts = VectorUtils.get_equidistant_points(target_geom, target_n + 1)
        
        if not base_verts or not target_verts:
            return []

        indexed_connections = [] 
        
        # Dicionário para rastrear quais vértices do alvo foram "atingidos"
        # target_idx -> list of base_indices
        target_coverage = {i: [] for i in range(len(target_verts))}

        # Passo 1: Base -> Target (Nearest Point)
        for b_idx, b_pt in enumerate(base_verts):
            # Encontra o ponto mais próximo na geometria (não apenas vértices)
            nearest_g = target_geom.nearestPoint(QgsGeometry.fromPointXY(b_pt))
            if not nearest_g.isEmpty():
                target_pt = nearest_g.asPoint()
                # Identifica qual vértice do alvo está mais próximo deste ponto de impacto
                t_idx = ConnectionJudge._find_nearest_vertex_index(target_pt, target_verts)
                target_coverage[t_idx].append(b_idx)

                indexed_connections.append({
                    'sort_key': float(b_idx),
                    'geom': QgsGeometry.fromPolylineXY([b_pt, target_pt]),
                    'id_pai': float(b_idx),
                    'id_mae': float(t_idx)
                })

        # Passo 2: Identificar Órfãos no Target
        orphans = [i for i, base_indices in target_coverage.items() if not base_indices]
        if not orphans:
            return sorted(indexed_connections, key=lambda x: x['sort_key'])

        # Passo 3: Lógica do Juiz para Órfãos
        hit_indices = sorted([i for i, base_indices in target_coverage.items() if base_indices])
        
        for o_idx in orphans:
            # Caso A: Órfãos antes do primeiro acerto (Início)
            if not hit_indices or o_idx < hit_indices[0]:
                # Liga ao primeiro ponto da base que teve um acerto
                target_pt = target_verts[o_idx]
                base_ref_idx = target_coverage[hit_indices[0]][0] if hit_indices else 0 
                # Peso negativo para órfãos do início (mantendo ordem entre eles)
                sort_key = -1.0 + (o_idx / len(target_verts))
                indexed_connections.append({
                    'sort_key': sort_key,
                    'geom': QgsGeometry.fromPolylineXY([target_verts[o_idx], base_verts[base_ref_idx]]),
                    'id_pai': float(base_ref_idx),
                    'id_mae': float(o_idx)
                })
            
            # Caso B: Órfãos após o último acerto (Fim)
            elif o_idx > hit_indices[-1]:
                target_pt = target_verts[o_idx]
                base_ref_idx = target_coverage[hit_indices[-1]][-1]
                # Peso maior que o último índice para órfãos do fim
                sort_key = float(len(base_verts)) + (o_idx / len(target_verts))
                indexed_connections.append({
                    'sort_key': sort_key,
                    'geom': QgsGeometry.fromPolylineXY([target_verts[o_idx], base_verts[base_ref_idx]]),
                    'id_pai': float(base_ref_idx),
                    'id_mae': float(o_idx)
                })
            
            # Caso C: Órfãos no meio (Centroide dos vizinhos)
            else:
                # Encontra quem são os vizinhos adotivos
                prev_t_idx = max([i for i in hit_indices if i < o_idx])
                next_t_idx = min([i for i in hit_indices if i > o_idx])
                
                # Pega o último da esquerda e o primeiro da direita na base
                b_idx_left = target_coverage[prev_t_idx][-1]
                b_idx_right = target_coverage[next_t_idx][0]
                
                mid_pt = VectorUtils.get_midpoint(base_verts[b_idx_left], base_verts[b_idx_right])
                # Peso fracionado entre os dois índices da base
                sort_key = float(b_idx_left) + 0.5 + (o_idx / (len(target_verts) * 10))
                indexed_connections.append({
                    'sort_key': sort_key,
                    'geom': QgsGeometry.fromPolylineXY([target_verts[o_idx], mid_pt]),
                    'id_pai': (float(b_idx_left) + float(b_idx_right)) / 2.0,
                    'id_mae': float(o_idx)
                })

        # Ordenação Final: O "Juiz" decide a posição baseada na ordem espacial da base
        indexed_connections.sort(key=lambda x: x['sort_key'])
        return indexed_connections

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
    def solve_nearest_with_criteria(geom1, geom2, criteria_idx, target_n):
        """
        Executa o julgamento para decidir qual linha será a base conforme o critério.
        """
        # 1. Alinhamento prévio para garantir que os vértices 0 coincidam espacialmente
        g1, g2 = VectorUtils.align_line_pair(geom1, geom2)

        use_g1_as_base = True
        if criteria_idx == 0: # Menor Tamanho
            use_g1_as_base = g1.length() <= g2.length()
        elif criteria_idx == 1: # Maior Tamanho
            use_g1_as_base = g1.length() >= g2.length()
        elif criteria_idx == 2: # Menor Ângulo (Mais fechada/curva)
            use_g1_as_base = VectorUtils.get_line_straightness_score(g1) <= VectorUtils.get_line_straightness_score(g2)
        elif criteria_idx == 3: # Maior Ângulo (Mais aberta/reta)
            use_g1_as_base = VectorUtils.get_line_straightness_score(g1) >= VectorUtils.get_line_straightness_score(g2)

        if use_g1_as_base:
            results = ConnectionJudge.generate_nearest_with_orphans(g1, g2, target_n)
            # id_pai mapeia para g1, id_mae mapeia para g2
            return [{
                'geom': d['geom'], 
                'id': i + 1,
                'id_pai': d.get('id_pai', 0),
                'id_mae': d.get('id_mae', 0),
                'id_origem': d.get('sort_key', 0)
            } for i, d in enumerate(results)]
        else:
            results = ConnectionJudge.generate_nearest_with_orphans(g2, g1, target_n)
            # Invertemos os IDs no retorno para que 'Pai' sempre seja a Linha 1
            # e 'Mae' sempre seja a Linha 2, independente de quem foi a base.
            # Também invertemos a geometria da conexão para começar no Pai (g1).
            return [{
                'geom': VectorUtils.reverse_geometry(d['geom']), 
                'id': i + 1,
                'id_pai': d.get('id_mae', 0),
                'id_mae': d.get('id_pai', 0),
                'id_origem': d.get('sort_key', 0)
            } for i, d in enumerate(results)]
            