# -*- coding: utf-8 -*-

from qgis.core import QgsGeometry
from .vector_utils import VectorUtils


class SimpleConnectionJudge:
    """
    Classe responsavel por julgar conexoes entre um par de linhas.
    Trabalha com vertices reais das geometrias, sem amostragem equidistante.
    Pai e mae sao definidos por decide_base_by_endpoint (ponta valida na ponta).
    """

    @staticmethod
    def _get_real_vertices(geom):
        """Retorna a lista de QgsPointXY dos vertices reais da geometria."""
        from qgis.core import QgsPointXY
        return [QgsPointXY(v) for v in geom.vertices()]

    @staticmethod
    def _find_nearest_vertex_index(point, vertices):
        """Retorna o indice do vertice mais proximo de um ponto."""
        min_dist = float('inf')
        idx = 0
        for i, v in enumerate(vertices):
            d = point.distance(v)
            if d < min_dist:
                min_dist = d
                idx = i
        return idx

    @staticmethod
    def _build_connection(pt_a, pt_b, sort_key, keyFather, keyMother):
        return {
            'sort_key': sort_key,
            'geom': QgsGeometry.fromPolylineXY([pt_a, pt_b]),
            'keyFather': keyFather,
            'keyMother': keyMother,
        }

    @staticmethod
    def _strip_sort_key(connections):
        return [
            {
                'geom': c['geom'],
                'keyFather': c['keyFather'],
                'keyMother': c['keyMother'],
            }
            for c in connections
        ]

    @staticmethod
    def generate_connections(base_geom, target_geom, keyFather, keyMother):
        """
        Itera nos vertices reais do pai (base) e liga cada um ao vertice
        real mais proximo da mae (target).
        Vertices orfaos da mae:
          - Pontas (antes do primeiro / apos o ultimo acerto): ignorados
            (a layer ja vem padronizada, resolve_endpoints nao e necessario)
          - Meio: ligam ao midpoint entre os vertices do pai vizinhos ao orfao
        """
        base_verts = SimpleConnectionJudge._get_real_vertices(base_geom)
        target_verts = SimpleConnectionJudge._get_real_vertices(target_geom)

        if not base_verts or not target_verts:
            return []

        indexed_connections = []

        # target_idx -> lista de b_idx que apontaram para ele
        target_coverage = {i: [] for i in range(len(target_verts))}

        # Passo 1: cada vertice do pai liga ao vertice real mais proximo da mae
        for b_idx, b_pt in enumerate(base_verts):
            t_idx = SimpleConnectionJudge._find_nearest_vertex_index(
                b_pt, target_verts
            )
            target_coverage[t_idx].append(b_idx)
            indexed_connections.append(
                SimpleConnectionJudge._build_connection(
                    b_pt,
                    target_verts[t_idx],
                    float(b_idx),
                    keyFather,
                    keyMother,
                )
            )

        # Passo 2: identificar orfaos da mae
        orphans = [i for i, bs in target_coverage.items() if not bs]
        if not orphans:
            indexed_connections.sort(key=lambda x: x['sort_key'])
            return SimpleConnectionJudge._strip_sort_key(indexed_connections)

        # Passo 3: resolver orfaos do meio (pontas sao ignoradas)
        hit_indices = sorted(
            [i for i, bs in target_coverage.items() if bs]
        )

        for o_idx in orphans:
            # Pontas: ignora
            if not hit_indices:
                continue
            if o_idx < hit_indices[0] or o_idx > hit_indices[-1]:
                continue

            # Meio: midpoint entre os vertices do pai vizinhos
            prev_t_idx = max(i for i in hit_indices if i < o_idx)
            next_t_idx = min(i for i in hit_indices if i > o_idx)

            b_idx_left = target_coverage[prev_t_idx][-1]
            b_idx_right = target_coverage[next_t_idx][0]

            mid_pt = VectorUtils.get_midpoint(
                base_verts[b_idx_left],
                base_verts[b_idx_right],
            )
            sort_key = float(b_idx_left) + 0.5 + (
                o_idx / (len(target_verts) * 10)
            )
            indexed_connections.append(
                SimpleConnectionJudge._build_connection(
                    target_verts[o_idx],
                    mid_pt,
                    sort_key,
                    keyFather,
                    keyMother,
                )
            )

        indexed_connections.sort(key=lambda x: x['sort_key'])
        return SimpleConnectionJudge._strip_sort_key(indexed_connections)

    @staticmethod
    def solve_nearest_with_criteria(
        geom1,
        geom2,
        keyFather,
        keyMother,
    ):
        """
        Define pai e mae por decide_base_by_endpoint (ponta valida = ponto
        mais proximo da outra linha cai no meio dela, nao na ponta; das duas
        pontas validas a mais proxima vira pai).
        Alinha o par para que vertice 0 do pai fique proximo do vertice 0 da mae.
        Retorna lista de conexoes com keyFather sempre = Linha 1 e
        keyMother sempre = Linha 2.
        """
        g1, g2 = VectorUtils.align_line_pair(geom1, geom2)

        use_g1_as_base = VectorUtils.decide_base_by_endpoint(g1, g2)

        if use_g1_as_base:
            results = SimpleConnectionJudge.generate_connections(
                g1, g2, keyFather, keyMother
            )
            return [
                {
                    'geom': d['geom'],
                    'id': i + 1,
                    'keyFather': d['keyFather'],
                    'keyMother': d['keyMother'],
                }
                for i, d in enumerate(results)
            ]

        results = SimpleConnectionJudge.generate_connections(
            g2, g1, keyMother, keyFather
        )
        return [
            {
                'geom': VectorUtils.reverse_geometry(d['geom']),
                'id': i + 1,
                'keyFather': keyFather,
                'keyMother': keyMother,
            }
            for i, d in enumerate(results)
        ]