# -*- coding: utf-8 -*-

from qgis.core import QgsGeometry
from .vector_utils import VectorUtils


class SimpleConnectionJudge:
    """
    Classe responsavel por julgar conexoes entre um par de linhas.
    Implementa a logica de preenchimento de vertices orfaos.
    """

    @staticmethod
    def _build_connection(points, sort_key, keyFather, keyMother):
        return {
            'sort_key': sort_key,
            'geom': QgsGeometry.fromPolylineXY(points),
            'keyFather': keyFather,
            'keyMother': keyMother,
        }

    @staticmethod
    def _strip_sort_key(connections):
        return [
            {
                'geom': connection['geom'],
                'keyFather': connection['keyFather'],
                'keyMother': connection['keyMother'],
            }
            for connection in connections
        ]

    @staticmethod
    def generate_nearest_with_orphans(
        base_geom,
        target_geom,
        target_n,
        keyFather,
        keyMother,
        resolve_endpoints=True,
    ):
        """
        Gera conexoes de menor distancia garantindo que nenhum vertice da linha
        alvo fique orfao. Usa amostragem uniforme baseada em target_n para
        garantir densidade.
        """
        # target_n e o numero de segmentos, logo precisamos de n + 1 pontos.
        base_verts = VectorUtils.get_equidistant_points(base_geom, target_n + 1)
        target_verts = VectorUtils.get_equidistant_points(target_geom, target_n + 1)

        if not base_verts or not target_verts:
            return []

        indexed_connections = []

        # target_idx -> list of base_indices
        target_coverage = {i: [] for i in range(len(target_verts))}

        # Passo 1: Base -> Target (Nearest Point)
        for b_idx, b_pt in enumerate(base_verts):
            nearest_g = target_geom.nearestPoint(QgsGeometry.fromPointXY(b_pt))
            if not nearest_g.isEmpty():
                target_pt = nearest_g.asPoint()
                t_idx = SimpleConnectionJudge._find_nearest_vertex_index(
                    target_pt,
                    target_verts,
                )
                target_coverage[t_idx].append(b_idx)

                indexed_connections.append(
                    SimpleConnectionJudge._build_connection(
                        [b_pt, target_pt],
                        float(b_idx),
                        keyFather,
                        keyMother,
                    )
                )

        # Passo 2: Identificar orfaos no Target
        orphans = [i for i, base_indices in target_coverage.items() if not base_indices]
        if not orphans:
            indexed_connections.sort(key=lambda x: x['sort_key'])
            return SimpleConnectionJudge._strip_sort_key(indexed_connections)

        # Passo 3: Logica do juiz para orfaos
        hit_indices = sorted(
            [i for i, base_indices in target_coverage.items() if base_indices]
        )

        for o_idx in orphans:
            # Caso A: Orfaos antes do primeiro acerto (inicio)
            if not hit_indices or o_idx < hit_indices[0]:
                if not resolve_endpoints:
                    continue

                base_ref_idx = target_coverage[hit_indices[0]][0] if hit_indices else 0
                sort_key = -1.0 + (o_idx / len(target_verts))
                indexed_connections.append(
                    SimpleConnectionJudge._build_connection(
                        [target_verts[o_idx], base_verts[base_ref_idx]],
                        sort_key,
                        keyFather,
                        keyMother,
                    )
                )

            # Caso B: Orfaos apos o ultimo acerto (fim)
            elif o_idx > hit_indices[-1]:
                if not resolve_endpoints:
                    continue

                base_ref_idx = target_coverage[hit_indices[-1]][-1]
                sort_key = float(len(base_verts)) + (o_idx / len(target_verts))
                indexed_connections.append(
                    SimpleConnectionJudge._build_connection(
                        [target_verts[o_idx], base_verts[base_ref_idx]],
                        sort_key,
                        keyFather,
                        keyMother,
                    )
                )

            # Caso C: Orfaos no meio (centroide dos vizinhos)
            else:
                prev_t_idx = max([i for i in hit_indices if i < o_idx])
                next_t_idx = min([i for i in hit_indices if i > o_idx])

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
                        [target_verts[o_idx], mid_pt],
                        sort_key,
                        keyFather,
                        keyMother,
                    )
                )

        indexed_connections.sort(key=lambda x: x['sort_key'])
        return SimpleConnectionJudge._strip_sort_key(indexed_connections)

    @staticmethod
    def _find_nearest_vertex_index(point, vertices):
        """Auxiliar para encontrar o indice do vertice mais proximo."""
        min_dist = float('inf')
        idx = 0
        for i, v in enumerate(vertices):
            d = point.distance(v)
            if d < min_dist:
                min_dist = d
                idx = i
        return idx

    @staticmethod
    def solve_nearest_with_criteria(
        geom1,
        geom2,
        criteria_idx,
        target_n,
        keyFather,
        keyMother,
        resolve_endpoints=True,
    ):
        """
        Executa o julgamento para decidir qual linha sera a base conforme o
        criterio. O retorno sempre representa um par: keyFather = Linha 1 e
        keyMother = Linha 2.
        """
        g1, g2 = VectorUtils.align_line_pair(geom1, geom2)

        use_g1_as_base = True
        if criteria_idx == 0:
            use_g1_as_base = VectorUtils.decide_base_by_endpoint(g1, g2)
        elif criteria_idx == 1:
            use_g1_as_base = g1.length() <= g2.length()
        elif criteria_idx == 2:
            use_g1_as_base = g1.length() >= g2.length()
        elif criteria_idx == 3:
            use_g1_as_base = (
                VectorUtils.get_line_straightness_score(g1)
                <= VectorUtils.get_line_straightness_score(g2)
            )
        elif criteria_idx == 4:
            use_g1_as_base = (
                VectorUtils.get_line_straightness_score(g1)
                >= VectorUtils.get_line_straightness_score(g2)
            )

        if use_g1_as_base:
            results = SimpleConnectionJudge.generate_nearest_with_orphans(
                g1,
                g2,
                target_n,
                keyFather,
                keyMother,
                resolve_endpoints,
            )
            return [
                {
                    'geom': d['geom'],
                    'id': i + 1,
                    'keyFather': d.get('keyFather'),
                    'keyMother': d.get('keyMother'),
                }
                for i, d in enumerate(results)
            ]

        results = SimpleConnectionJudge.generate_nearest_with_orphans(
            g2,
            g1,
            target_n,
            keyMother,
            keyFather,
            resolve_endpoints,
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
