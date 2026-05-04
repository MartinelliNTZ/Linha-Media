# -*- coding: utf-8 -*-

from qgis.core import QgsGeometry

from .vector_utils import VectorUtils


class SimpleConnectionJudge:
    """
    Classe responsavel por julgar conexoes entre um par de linhas.
    Trabalha com vertices reais das geometrias, sem amostragem equidistante.
    Pai e mae sao definidos por decide_base_by_endpoint (ponta valida na ponta).
    """

    ORPHAN_VERTEX_KEY = "orpan"

    @staticmethod
    def _get_real_vertices(geom):
        """Retorna a lista de QgsPointXY dos vertices reais da geometria."""
        from qgis.core import QgsPointXY

        return [QgsPointXY(v) for v in geom.vertices()]

    @staticmethod
    def _find_nearest_vertex_index(point, vertices):
        """Retorna o indice do vertice mais proximo de um ponto."""
        min_dist = float("inf")
        idx = 0
        for i, vertex in enumerate(vertices):
            distance = point.distance(vertex)
            if distance < min_dist:
                min_dist = distance
                idx = i
        return idx

    @staticmethod
    def _normalize_vertex_keys(vertex_keys, expected_size):
        if not vertex_keys or len(vertex_keys) != expected_size:
            return [None] * expected_size
        return [None if key in (None, "") else str(key) for key in vertex_keys]

    @staticmethod
    def _reverse_vertex_keys(vertex_keys):
        if vertex_keys is None:
            return None
        return list(reversed(vertex_keys))

    @staticmethod
    def _orient_northwest_with_vertex_keys(geom, vertex_keys):
        if geom.isEmpty():
            return geom, vertex_keys

        nodes = list(geom.vertices())
        if len(nodes) < 2:
            return geom, vertex_keys

        start = nodes[0]
        end = nodes[-1]

        def score_no(point):
            return (point.x(), -point.y())

        if score_no(end) < score_no(start):
            return (
                VectorUtils.reverse_geometry(geom),
                SimpleConnectionJudge._reverse_vertex_keys(vertex_keys),
            )

        return geom, vertex_keys

    @staticmethod
    def _align_line_pair_with_vertex_keys(
        geom1,
        geom2,
        vertex_keys1=None,
        vertex_keys2=None,
    ):
        g1, keys1 = SimpleConnectionJudge._orient_northwest_with_vertex_keys(
            geom1, vertex_keys1
        )
        g2 = geom2
        keys2 = vertex_keys2

        nodes1 = list(g1.vertices())
        nodes2 = list(g2.vertices())

        if not nodes1 or not nodes2:
            return g1, g2, keys1, keys2

        from qgis.core import QgsPointXY

        p1_start = QgsPointXY(nodes1[0].x(), nodes1[0].y())
        p2_start = QgsPointXY(nodes2[0].x(), nodes2[0].y())
        p2_end = QgsPointXY(nodes2[-1].x(), nodes2[-1].y())

        if p1_start.distance(p2_start) > p1_start.distance(p2_end):
            return (
                g1,
                VectorUtils.reverse_geometry(g2),
                keys1,
                SimpleConnectionJudge._reverse_vertex_keys(keys2),
            )

        return g1, g2, keys1, keys2

    @staticmethod
    def _build_connection(
        pt_a,
        pt_b,
        sort_key,
        key_father,
        key_mother,
        vtx_key_base,
        vtx_key_target,
    ):
        return {
            "sort_key": sort_key,
            "geom": QgsGeometry.fromPolylineXY([pt_a, pt_b]),
            "keyFather": key_father,
            "keyMother": key_mother,
            "vtxKeyBase": vtx_key_base,
            "vtxKeyTarget": vtx_key_target,
        }

    @staticmethod
    def _strip_sort_key(connections):
        return [
            {
                "geom": connection["geom"],
                "keyFather": connection["keyFather"],
                "keyMother": connection["keyMother"],
                "vtxKeyBase": connection["vtxKeyBase"],
                "vtxKeyTarget": connection["vtxKeyTarget"],
            }
            for connection in connections
        ]

    @staticmethod
    def generate_connections(
        base_geom,
        target_geom,
        key_father,
        key_mother,
        base_vertex_keys=None,
        target_vertex_keys=None,
        orphan_vertex_key=None,
    ):
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

        base_vertex_keys = SimpleConnectionJudge._normalize_vertex_keys(
            base_vertex_keys, len(base_verts)
        )
        target_vertex_keys = SimpleConnectionJudge._normalize_vertex_keys(
            target_vertex_keys, len(target_verts)
        )
        orphan_vertex_key = (
            orphan_vertex_key or SimpleConnectionJudge.ORPHAN_VERTEX_KEY
        )

        indexed_connections = []

        # target_idx -> lista de b_idx que apontaram para ele
        target_coverage = {i: [] for i in range(len(target_verts))}

        # Passo 1: cada vertice do pai liga ao vertice real mais proximo da mae
        for b_idx, base_point in enumerate(base_verts):
            target_idx = SimpleConnectionJudge._find_nearest_vertex_index(
                base_point, target_verts
            )
            target_coverage[target_idx].append(b_idx)
            indexed_connections.append(
                SimpleConnectionJudge._build_connection(
                    base_point,
                    target_verts[target_idx],
                    float(b_idx),
                    key_father,
                    key_mother,
                    base_vertex_keys[b_idx],
                    target_vertex_keys[target_idx],
                )
            )

        # Passo 2: identificar orfaos da mae
        orphans = [index for index, hits in target_coverage.items() if not hits]
        if not orphans:
            indexed_connections.sort(key=lambda connection: connection["sort_key"])
            return SimpleConnectionJudge._strip_sort_key(indexed_connections)

        # Passo 3: resolver orfaos do meio (pontas sao ignoradas)
        hit_indices = sorted(
            [index for index, hits in target_coverage.items() if hits]
        )

        for orphan_idx in orphans:
            if not hit_indices:
                continue
            if orphan_idx < hit_indices[0] or orphan_idx > hit_indices[-1]:
                continue

            prev_target_idx = max(index for index in hit_indices if index < orphan_idx)
            next_target_idx = min(index for index in hit_indices if index > orphan_idx)

            base_idx_left = target_coverage[prev_target_idx][-1]
            base_idx_right = target_coverage[next_target_idx][0]

            midpoint = VectorUtils.get_midpoint(
                base_verts[base_idx_left],
                base_verts[base_idx_right],
            )
            sort_key = float(base_idx_left) + 0.5 + (
                orphan_idx / (len(target_verts) * 10)
            )
            indexed_connections.append(
                SimpleConnectionJudge._build_connection(
                    target_verts[orphan_idx],
                    midpoint,
                    sort_key,
                    key_father,
                    key_mother,
                    orphan_vertex_key,
                    target_vertex_keys[orphan_idx],
                )
            )

        indexed_connections.sort(key=lambda connection: connection["sort_key"])
        return SimpleConnectionJudge._strip_sort_key(indexed_connections)

    @staticmethod
    def solve_nearest_with_criteria(
        geom1,
        geom2,
        keyFather,
        keyMother,
        vertex_keys1=None,
        vertex_keys2=None,
        orphan_vertex_key=None,
    ):
        """
        Define pai e mae por decide_base_by_endpoint (ponta valida = ponto
        mais proximo da outra linha cai no meio dela, nao na ponta; das duas
        pontas validas a mais proxima vira pai).
        Alinha o par para que vertice 0 do pai fique proximo do vertice 0 da mae.
        Retorna lista de conexoes com keyFather sempre = Linha 1 e
        keyMother sempre = Linha 2.
        """
        geom1_vertex_count = sum(1 for _ in geom1.vertices())
        geom2_vertex_count = sum(1 for _ in geom2.vertices())
        vertex_keys1 = SimpleConnectionJudge._normalize_vertex_keys(
            vertex_keys1, geom1_vertex_count
        )
        vertex_keys2 = SimpleConnectionJudge._normalize_vertex_keys(
            vertex_keys2, geom2_vertex_count
        )

        (
            g1,
            g2,
            aligned_vertex_keys1,
            aligned_vertex_keys2,
        ) = SimpleConnectionJudge._align_line_pair_with_vertex_keys(
            geom1,
            geom2,
            vertex_keys1,
            vertex_keys2,
        )

        use_g1_as_base = VectorUtils.decide_base_by_endpoint(g1, g2)

        if use_g1_as_base:
            results = SimpleConnectionJudge.generate_connections(
                g1,
                g2,
                keyFather,
                keyMother,
                aligned_vertex_keys1,
                aligned_vertex_keys2,
                orphan_vertex_key=orphan_vertex_key,
            )
            return [
                {
                    "geom": result["geom"],
                    "id": index + 1,
                    "keyFather": result["keyFather"],
                    "keyMother": result["keyMother"],
                    "vtxKeyFather": result["vtxKeyBase"],
                    "vtxKeyMother": result["vtxKeyTarget"],
                }
                for index, result in enumerate(results)
            ]

        results = SimpleConnectionJudge.generate_connections(
            g2,
            g1,
            keyMother,
            keyFather,
            aligned_vertex_keys2,
            aligned_vertex_keys1,
            orphan_vertex_key=orphan_vertex_key,
        )
        return [
            {
                "geom": VectorUtils.reverse_geometry(result["geom"]),
                "id": index + 1,
                "keyFather": keyFather,
                "keyMother": keyMother,
                "vtxKeyFather": result["vtxKeyTarget"],
                "vtxKeyMother": result["vtxKeyBase"],
            }
            for index, result in enumerate(results)
        ]
