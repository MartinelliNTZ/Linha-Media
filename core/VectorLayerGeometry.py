# -*- coding: utf-8 -*-

import math
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsSpatialIndex
from .vector_utils import VectorUtils


class VectorLayerGeometry:
    """Classe genérica para manipulação de geometrias de camadas vetoriais."""

    @staticmethod
    def create_spatial_context(features, key_attr_name):
        """
        Cria índice espacial e dicionários auxiliares para operações de vizinhança.

        Args:
            features (iterable[QgsFeature]): Feições que participarão das consultas.
            key_attr_name (str): Nome do atributo que identifica a feição vizinha.

        Returns:
            tuple: (spatial_index, feat_dict, fid_to_key)
        """
        feature_list = list(features)
        if not feature_list:
            return QgsSpatialIndex(), {}, {}

        if not key_attr_name:
            raise ValueError("O parâmetro key_attr_name é obrigatório.")

        field_names = feature_list[0].fields().names()
        if key_attr_name not in field_names:
            raise ValueError(
                "O atributo '{0}' não existe nas feições informadas.".format(
                    key_attr_name
                )
            )

        spatial_index = QgsSpatialIndex()
        for feature in feature_list:
            spatial_index.addFeature(feature)
        feat_dict = {feature.id(): feature for feature in feature_list}
        fid_to_key = {feature.id(): feature[key_attr_name] for feature in feature_list}
        return spatial_index, feat_dict, fid_to_key

    @staticmethod
    def standardize_line_feature(feature, spacing, temp_fields, *, key):
        """
        Padroniza o espaçamento de uma linha e prepara sua representação intermediária.

        Returns:
            dict: geometria padronizada, pontos padronizados, atributos e feição temporária.
        """
        geometry = feature.geometry()
        points = VectorLayerGeometry._sample_points_by_spacing(geometry, spacing)
        standardized_geometry = (
            QgsGeometry.fromPolylineXY(points) if len(points) >= 2 else geometry
        )

        temp_feature = QgsFeature(temp_fields)
        temp_feature.setId(feature.id())
        temp_feature.setGeometry(standardized_geometry)
        temp_feature.setAttributes(feature.attributes() + [key])

        return {
            "feature_id": feature.id(),
            "key": key,
            "original_attrs": feature.attributes(),
            "geometry": standardized_geometry,
            "points": points,
            "feature": temp_feature,
        }

    @staticmethod
    def generate_perpendicular_records(points, sensor_limit, *, key):
        """
        Gera registros de sensores perpendiculares sem cortar por vizinhança.
        """
        sensor_records = []

        for index, point in enumerate(points):
            p_start = QgsPointXY(point.x(), point.y())
            key_vertex = f"{key}_{index:04d}"
            az_local = VectorUtils.get_vertex_azimuth(points, index)

            for angle_offset in [90, -90]:
                azimuth = (az_local + angle_offset) % 360
                side = "d" if angle_offset == 90 else "e"
                key_s1 = f"{key_vertex}{side}"
                sensor_records.append(
                    {
                        "key": key,
                        "keyVertex": key_vertex,
                        "keyS1": key_s1,
                        "vertex_index": index,
                        "side": side,
                        "azimuth": azimuth,
                        "start_point": p_start,
                        "geometry": VectorLayerGeometry._build_ray_geometry(
                            p_start, azimuth, sensor_limit
                        ),
                        "neighbor": None,
                    }
                )

        return sensor_records

    @staticmethod
    def trim_perpendicular_records(
        sensor_records,
        sensor_limit,
        spatial_index,
        feat_dict,
        origin_feature_id,
        fid_to_key,
        *,
        neighbor_key_attr_name,
        mother_geoms=None,
    ):
        """
        Corta os sensores pela feição vizinha mais próxima e identifica sua chave.
        """
        if not neighbor_key_attr_name:
            raise ValueError("O nome do atributo de chave do vizinho é obrigatório.")

        for record in sensor_records:
            trimmed_geometry, hit_id = VectorLayerGeometry.get_trimmed_ray(
                record["start_point"],
                record["azimuth"],
                sensor_limit,
                spatial_index,
                feat_dict,
                origin_feature_id,
                mother_geoms,
            )
            record["geometry"] = trimmed_geometry
            record["neighbor"] = fid_to_key.get(hit_id) if hit_id != -1 else None

        return sensor_records

    @staticmethod
    def populate_vertex_neighbors(points, sensor_records, *, key):
        """
        Consolida os vizinhos detectados pelos sensores em registros de vértices.
        """
        sensor_map = {}
        for record in sensor_records:
            sensor_map[(record["vertex_index"], record["side"])] = record.get("neighbor")

        vertex_records = []
        for index, point in enumerate(points):
            vertex_records.append(
                {
                    "key": key,
                    "keyVertex": f"{key}_{index:04d}",
                    "point": QgsPointXY(point.x(), point.y()),
                    "vertex_index": index,
                    "neighborE": sensor_map.get((index, "e")),
                    "neighborD": sensor_map.get((index, "d")),
                    "keySec": None,
                }
            )

        return vertex_records

    @staticmethod
    def clear_attributes(attributes, fields, attribute_names):
        """
        Limpa atributos de uma lista genérica a partir de seus nomes.
        """
        if not attributes or not fields or not attribute_names:
            return attributes

        cleaned_attributes = list(attributes)
        field_names = fields.names() if hasattr(fields, "names") else list(fields)

        for attribute_name in attribute_names:
            if attribute_name in field_names:
                cleaned_attributes[field_names.index(attribute_name)] = None

        return cleaned_attributes

    @staticmethod
    def calculate_geometry_length(geometry):
        """
        Calcula o comprimento de uma geometria com protecao para nulos.
        """
        if geometry is None or geometry.isEmpty():
            return 0.0
        return geometry.length()

    @staticmethod
    def get_most_common_target_by_key(layer_or_features, key_attr_name, target_attr_name):
        """
        Agrupa feicoes por um atributo-chave e retorna o valor mais frequente
        do atributo-alvo em cada grupo.

        Args:
            layer_or_features (QgsFeatureSource | iterable[QgsFeature]):
                Camada ou lista de feicoes a consultar.
            key_attr_name (str): Nome do atributo usado no agrupamento.
            target_attr_name (str): Nome do atributo cujo valor dominante sera retornado.

        Returns:
            dict: {valor_da_key: valor_mais_frequente_do_target}
        """
        if layer_or_features is None:
            return {}

        if not key_attr_name or not target_attr_name:
            raise ValueError("Os atributos de chave e alvo devem ser informados.")

        if hasattr(layer_or_features, "getFeatures"):
            feature_list = list(layer_or_features.getFeatures())
            fields = (
                layer_or_features.fields()
                if hasattr(layer_or_features, "fields")
                else None
            )
        else:
            feature_list = list(layer_or_features)
            fields = feature_list[0].fields() if feature_list else None

        if not feature_list:
            return {}

        field_names = fields.names() if fields else feature_list[0].fields().names()
        for attr_name in [key_attr_name, target_attr_name]:
            if attr_name not in field_names:
                raise ValueError(
                    "O atributo '{0}' nao existe nas feicoes informadas.".format(
                        attr_name
                    )
                )

        grouped_counts = {}
        grouped_order = {}

        for feature in feature_list:
            key_value = feature[key_attr_name]
            target_value = feature[target_attr_name]

            if key_value in (None, "") or target_value in (None, ""):
                continue

            key_counts = grouped_counts.setdefault(key_value, {})
            key_order = grouped_order.setdefault(key_value, {})

            if target_value not in key_order:
                key_order[target_value] = len(key_order)

            key_counts[target_value] = key_counts.get(target_value, 0) + 1

        most_common_by_key = {}
        for key_value, target_counts in grouped_counts.items():
            most_common_by_key[key_value] = max(
                target_counts.items(),
                key=lambda item: (
                    item[1],
                    -grouped_order[key_value][item[0]],
                ),
            )[0]

        return most_common_by_key

    @staticmethod
    def assign_keysec(vertex_records, start_sec_counter=0):
        """
        Atribui keySec agrupando vértices com a mesma assinatura de vizinhança.

        Returns:
            int: próximo contador disponível após o último keySec utilizado.
        """
        if not vertex_records:
            return start_sec_counter

        current_counter = start_sec_counter
        previous_signature = VectorLayerGeometry._vertex_signature(vertex_records[0])
        vertex_records[0]["keySec"] = f"S{current_counter:04d}"

        for vertex_record in vertex_records[1:]:
            current_signature = VectorLayerGeometry._vertex_signature(vertex_record)
            if current_signature != previous_signature:
                current_counter += 1
                previous_signature = current_signature
            vertex_record["keySec"] = f"S{current_counter:04d}"

        return current_counter + 1

    @staticmethod
    def enforce_minimum_group_size(vertex_records, minimum_size):
        """
        Reatribui keySec de grupos pequenos para o grupo anterior válido.
        Se o primeiro grupo for pequeno e não houver anterior, usa o próximo grupo.
        """
        if minimum_size <= 1 or not vertex_records:
            return vertex_records

        groups = VectorLayerGeometry._group_vertex_records_by_keysec(vertex_records)
        if len(groups) <= 1:
            return vertex_records

        for index, group in enumerate(groups):
            if len(group["records"]) >= minimum_size:
                continue

            target_key_sec = None

            for previous_index in range(index - 1, -1, -1):
                if len(groups[previous_index]["records"]) >= minimum_size:
                    target_key_sec = groups[previous_index]["keySec"]
                    break

            if target_key_sec is None:
                for next_index in range(index + 1, len(groups)):
                    if len(groups[next_index]["records"]) >= minimum_size:
                        target_key_sec = groups[next_index]["keySec"]
                        break

            if target_key_sec is None:
                if index > 0:
                    target_key_sec = groups[index - 1]["keySec"]
                elif index + 1 < len(groups):
                    target_key_sec = groups[index + 1]["keySec"]

            if target_key_sec is None:
                continue

            for record in group["records"]:
                record["keySec"] = target_key_sec

        return vertex_records

    @staticmethod
    def partition_standardized_line(points, original_attrs, vertex_records, *, key):
        """
        Particiona a linha padronizada por keySec e transfere neighborE/neighborD.
        """
        if len(points) < 2 or not vertex_records:
            return []

        segment_records = []
        current_key_sec = vertex_records[0]["keySec"]
        current_neighbor_e = vertex_records[0]["neighborE"]
        current_neighbor_d = vertex_records[0]["neighborD"]
        current_points = [QgsPointXY(points[0].x(), points[0].y())]
        current_vertex_keys = [vertex_records[0]["keyVertex"]]

        for index in range(1, len(points)):
            point = QgsPointXY(points[index].x(), points[index].y())
            vertex_record = vertex_records[index]

            if vertex_record["keySec"] != current_key_sec:
                if len(current_points) >= 2:
                    segment_geometry = QgsGeometry.fromPolylineXY(current_points)
                    segment_records.append(
                        {
                            "geometry": segment_geometry,
                            "keySec": current_key_sec,
                            "vertex_keys": list(current_vertex_keys),
                            "attributes": original_attrs
                            + [
                                key,
                                current_key_sec,
                                current_neighbor_e,
                                current_neighbor_d,
                                VectorLayerGeometry.calculate_geometry_length(
                                    segment_geometry
                                ),
                            ],
                        }
                    )

                previous_point = QgsPointXY(points[index - 1].x(), points[index - 1].y())
                previous_vertex_key = vertex_records[index - 1]["keyVertex"]
                current_points = [previous_point, point]
                current_vertex_keys = [previous_vertex_key, vertex_record["keyVertex"]]
                current_key_sec = vertex_record["keySec"]
                current_neighbor_e = vertex_record["neighborE"]
                current_neighbor_d = vertex_record["neighborD"]
                continue

            current_points.append(point)
            current_vertex_keys.append(vertex_record["keyVertex"])

        if len(current_points) >= 2:
            segment_geometry = QgsGeometry.fromPolylineXY(current_points)
            segment_records.append(
                {
                    "geometry": segment_geometry,
                    "keySec": current_key_sec,
                    "vertex_keys": list(current_vertex_keys),
                    "attributes": original_attrs
                    + [
                        key,
                        current_key_sec,
                        current_neighbor_e,
                        current_neighbor_d,
                        VectorLayerGeometry.calculate_geometry_length(
                            segment_geometry
                        ),
                    ],
                }
            )

        return segment_records

    @staticmethod
    def get_trimmed_ray(
        p_start,
        azimuth,
        max_length,
        spatial_index=None,
        feat_dict=None,
        exclude_id=-1,
        mother_geoms=None,
    ):
        """
        Gera uma geometria de raio a partir de um ponto, cortando-a se houver colisão.

        Returns:
            tuple: (QgsGeometry do raio cortado, ID da feição que causou a colisão ou -1)
        """
        p_target = VectorLayerGeometry._project_point(p_start, azimuth, max_length)
        ray_geom = QgsGeometry.fromPolylineXY([p_start, p_target])
        min_dist = float(max_length)
        final_p_end = p_target
        hit_id = -1

        if mother_geoms:
            for mother_geometry in mother_geoms:
                if mother_geometry and not mother_geometry.isEmpty():
                    intersection = ray_geom.intersection(mother_geometry)
                    if not intersection.isEmpty():
                        point = VectorUtils._get_closest_point(intersection, p_start)
                        if point:
                            distance = p_start.distance(point)
                            if distance < min_dist:
                                min_dist = distance
                                final_p_end = point

        if spatial_index and feat_dict:
            candidates = spatial_index.intersects(ray_geom.boundingBox())
            for candidate_id in candidates:
                if candidate_id == exclude_id:
                    continue

                intersection = ray_geom.intersection(feat_dict[candidate_id].geometry())
                if not intersection.isEmpty():
                    point = VectorUtils._get_closest_point(intersection, p_start)
                    if point:
                        distance = p_start.distance(point)
                        if 0.001 < distance < min_dist:
                            min_dist = distance
                            final_p_end = point
                            hit_id = candidate_id

        return QgsGeometry.fromPolylineXY([p_start, final_p_end]), hit_id

    @staticmethod
    def generate_perpendicular_sensors(
        points,
        sensor_limit,
        spatial_index,
        feat_dict,
        feature_id,
        perp_fields,
        vert_fields,
        output_fields,
        original_attrs,
        *,
        key,
        neighbor_key_attr_name,
        mother_geoms=None,
        fid_to_key=None,
        start_sec_counter=0,
    ):
        """
        Wrapper de compatibilidade baseado no fluxo particionado.
        """
        sensor_records = VectorLayerGeometry.generate_perpendicular_records(
            points, sensor_limit, key=key
        )
        sensor_records = VectorLayerGeometry.trim_perpendicular_records(
            sensor_records,
            sensor_limit,
            spatial_index,
            feat_dict,
            feature_id,
            fid_to_key or {},
            neighbor_key_attr_name=neighbor_key_attr_name,
            mother_geoms=mother_geoms,
        )
        vertex_records = VectorLayerGeometry.populate_vertex_neighbors(
            points, sensor_records, key=key
        )
        next_sec_counter = VectorLayerGeometry.assign_keysec(
            vertex_records, start_sec_counter
        )
        segment_records = VectorLayerGeometry.partition_standardized_line(
            points, original_attrs, vertex_records, key=key
        )

        sensor_features = []
        for record in sensor_records:
            feature = QgsFeature(perp_fields)
            feature.setGeometry(record["geometry"])
            feature.setAttributes(
                [
                    record["key"],
                    record["keyVertex"],
                    record["keyS1"],
                    record["side"],
                    record["neighbor"],
                ]
            )
            sensor_features.append(feature)

        vertex_features = []
        for record in vertex_records:
            feature = QgsFeature(vert_fields)
            feature.setGeometry(QgsGeometry.fromPointXY(record["point"]))
            feature.setAttributes(
                [
                    record["key"],
                    record["keyVertex"],
                    record["keySec"],
                    record["neighborE"],
                    record["neighborD"],
                ]
            )
            vertex_features.append(feature)

        partitioned_line_features = []
        for record in segment_records:
            feature = QgsFeature(output_fields)
            feature.setGeometry(record["geometry"])
            feature.setAttributes(record["attributes"])
            partitioned_line_features.append(feature)

        return sensor_features, vertex_features, partitioned_line_features, next_sec_counter - 1

    @staticmethod
    def adjust_line_length(geometry, delta):
        """
        Estende ou reduz uma linha em ambas as extremidades.
        delta > 0: estende a linha para fora.
        delta < 0: reduz a linha para dentro.
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

            p0 = polyline[0]
            p1 = polyline[1]
            dx0 = p0.x() - p1.x()
            dy0 = p0.y() - p1.y()
            dist0 = math.sqrt(dx0 ** 2 + dy0 ** 2)

            if dist0 > 0:
                new_poly[0] = QgsPointXY(
                    p0.x() + (dx0 / dist0) * delta,
                    p0.y() + (dy0 / dist0) * delta,
                )

            pn = polyline[-1]
            pn_1 = polyline[-2]
            dxn = pn.x() - pn_1.x()
            dyn = pn.y() - pn_1.y()
            distn = math.sqrt(dxn ** 2 + dyn ** 2)

            if distn > 0:
                new_poly[-1] = QgsPointXY(
                    pn.x() + (dxn / distn) * delta,
                    pn.y() + (dyn / distn) * delta,
                )

            new_parts.append(new_poly)

        if is_multi:
            return QgsGeometry.fromMultiPolylineXY(new_parts)
        return QgsGeometry.fromPolylineXY(new_parts[0])

    @staticmethod
    def _sample_points_by_spacing(geometry, spacing):
        if geometry.isEmpty():
            return []

        if spacing <= 0:
            return [QgsPointXY(vertex.x(), vertex.y()) for vertex in geometry.vertices()]

        length = geometry.length()
        if length == 0:
            return [QgsPointXY(vertex.x(), vertex.y()) for vertex in geometry.vertices()]

        distances = []
        current_distance = 0.0
        while current_distance < length:
            distances.append(current_distance)
            current_distance += spacing

        if not distances or abs(distances[-1] - length) > 1e-9:
            distances.append(length)

        points = []
        for distance in distances:
            interpolated_geometry = geometry.interpolate(distance)
            if interpolated_geometry and not interpolated_geometry.isEmpty():
                point = interpolated_geometry.asPoint()
                points.append(QgsPointXY(point.x(), point.y()))

        if len(points) == 1:
            end_point = geometry.interpolate(length).asPoint()
            points.append(QgsPointXY(end_point.x(), end_point.y()))

        return points

    @staticmethod
    def _project_point(start_point, azimuth, distance):
        radians = math.radians(azimuth)
        return QgsPointXY(
            start_point.x() + distance * math.sin(radians),
            start_point.y() + distance * math.cos(radians),
        )

    @staticmethod
    def _build_ray_geometry(start_point, azimuth, distance):
        end_point = VectorLayerGeometry._project_point(start_point, azimuth, distance)
        return QgsGeometry.fromPolylineXY([start_point, end_point])

    @staticmethod
    def _vertex_signature(vertex_record):
        return vertex_record.get("neighborE"), vertex_record.get("neighborD")

    @staticmethod
    def _group_vertex_records_by_keysec(vertex_records):
        groups = []
        current_group = None

        for record in vertex_records:
            key_sec = record.get("keySec")
            if current_group is None or current_group["keySec"] != key_sec:
                current_group = {"keySec": key_sec, "records": [record]}
                groups.append(current_group)
                continue
            current_group["records"].append(record)

        return groups
