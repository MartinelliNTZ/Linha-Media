# -*- coding: utf-8 -*-

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from ..core.MatchJudge import MatchJudge
from ..core.SimpleConnectionJudge import SimpleConnectionJudge
from ..core.VectorLayerGeometry import VectorLayerGeometry


class LinhaMestraLineConnectionAlgorithm(QgsProcessingAlgorithm):
    TRANSPOSE_TRIM_DISTANCE = 0.5
    INPUT = "INPUT"
    SENSOR_LIMIT = "SENSOR_LIMIT"
    SPACING = "SPACING"
    MIN_SEGMENT = "MIN_SEGMENT"
    PTS_PER_VTX = "PTS_PER_VTX"
    OUTPUT = "OUTPUT"
    PERP_OUTPUT = "PERP_OUTPUT"
    SEC_PERP_OUTPUT = "SEC_PERP_OUTPUT"
    VERT_OUTPUT = "VERT_OUTPUT"
    PAIR_CONN_OUTPUT = "PAIR_CONN_OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return LinhaMestraLineConnectionAlgorithm()

    def name(self):
        return "lineconnection"

    def displayName(self):
        return self.tr("Conexão de Linhas")

    def group(self):
        return self.tr("Linha Mestra")

    def groupId(self):
        return "linhamestra"

    def shortHelpString(self):
        return self.tr(
            "Padroniza a linha, gera perpendiculares, identifica vizinhos e particiona os segmentos."
        )

    @staticmethod
    def _classify_pair_connection_statuses(connection_records, orphan_vertex_key):
        father_counts = {}
        mother_counts = {}

        for record in connection_records:
            father_key = record.get("vtxKeyFather")
            mother_key = record.get("vtxKeyMother")

            if father_key not in (None, "", orphan_vertex_key):
                father_counts[str(father_key)] = (
                    father_counts.get(str(father_key), 0) + 1
                )

            if mother_key not in (None, "", orphan_vertex_key):
                mother_counts[str(mother_key)] = (
                    mother_counts.get(str(mother_key), 0) + 1
                )

        summary = {
            "normal": 0,
            "duplicated F": 0,
            "duplicated M": 0,
            "duplicated A": 0,
        }

        for record in connection_records:
            father_key = record.get("vtxKeyFather")
            mother_key = record.get("vtxKeyMother")

            father_duplicated = (
                father_key not in (None, "", orphan_vertex_key)
                and father_counts.get(str(father_key), 0) > 1
            )
            mother_duplicated = (
                mother_key not in (None, "", orphan_vertex_key)
                and mother_counts.get(str(mother_key), 0) > 1
            )

            if father_duplicated and mother_duplicated:
                record["Cstatus"] = "duplicated A"
            elif father_duplicated:
                record["Cstatus"] = "duplicated F"
            elif mother_duplicated:
                record["Cstatus"] = "duplicated M"
            else:
                record["Cstatus"] = "normal"

            summary[record["Cstatus"]] = summary.get(record["Cstatus"], 0) + 1

        return summary

    @staticmethod
    def _connection_crosses_standardized_layer(
        connection_geometry,
        standardized_spatial_index,
        standardized_feat_dict,
    ):
        if (
            connection_geometry is None
            or connection_geometry.isEmpty()
            or standardized_spatial_index is None
            or standardized_feat_dict is None
        ):
            return False

        if (
            VectorLayerGeometry.calculate_geometry_length(connection_geometry)
            <= LinhaMestraLineConnectionAlgorithm.TRANSPOSE_TRIM_DISTANCE * 2
        ):
            return False

        trimmed_connection_geometry = VectorLayerGeometry.adjust_line_length(
            connection_geometry,
            -LinhaMestraLineConnectionAlgorithm.TRANSPOSE_TRIM_DISTANCE,
        )
        if (
            trimmed_connection_geometry is None
            or trimmed_connection_geometry.isEmpty()
            or VectorLayerGeometry.calculate_geometry_length(trimmed_connection_geometry)
            <= 0
        ):
            return False

        for candidate_id in standardized_spatial_index.intersects(
            trimmed_connection_geometry.boundingBox()
        ):
            candidate_feature = standardized_feat_dict.get(candidate_id)
            if candidate_feature is None:
                continue

            candidate_geometry = candidate_feature.geometry()
            if candidate_geometry is None or candidate_geometry.isEmpty():
                continue

            if trimmed_connection_geometry.crosses(candidate_geometry):
                return True

        return False

    @staticmethod
    def _classify_pair_connection_final(
        connection_records,
        orphan_vertex_key,
        pts_per_vtx,
        standardized_spatial_index,
        standardized_feat_dict,
    ):
        max_valid_per_vertex = max(int(pts_per_vtx or 1), 1)
        grouped_by_father_vertex = {}
        grouped_by_mother_vertex = {}
        summary = {
            "valid": 0,
            "maxVertex": 0,
            "transpose": 0,
        }
        record_positions = {
            id(record): index for index, record in enumerate(connection_records)
        }

        def normalized_vertex_key(record, attribute_name):
            vertex_key = record.get(attribute_name)
            if vertex_key in (None, "", orphan_vertex_key):
                return None
            return str(vertex_key)

        def sort_key(record):
            return (
                record.get("lenght", 0.0),
                record.get("pair_id", 0),
                record.get("id_conexao", 0),
                record_positions[id(record)],
            )

        valid_by_father = set()
        valid_by_mother = set()
        transposed_connections = set()

        for record in connection_records:
            father_key = normalized_vertex_key(record, "vtxKeyFather")
            mother_key = normalized_vertex_key(record, "vtxKeyMother")

            if LinhaMestraLineConnectionAlgorithm._connection_crosses_standardized_layer(
                record.get("geom"),
                standardized_spatial_index,
                standardized_feat_dict,
            ):
                transposed_connections.add(id(record))

            if father_key is None:
                valid_by_father.add(id(record))
            else:
                grouped_by_father_vertex.setdefault(father_key, []).append(record)

            if mother_key is None:
                valid_by_mother.add(id(record))
            else:
                grouped_by_mother_vertex.setdefault(mother_key, []).append(record)

        for grouped_records in grouped_by_father_vertex.values():
            grouped_records.sort(key=sort_key)

            for index, record in enumerate(grouped_records):
                if index < max_valid_per_vertex:
                    valid_by_father.add(id(record))

        for grouped_records in grouped_by_mother_vertex.values():
            grouped_records.sort(key=sort_key)

            for index, record in enumerate(grouped_records):
                if index < max_valid_per_vertex:
                    valid_by_mother.add(id(record))

        for record in connection_records:
            record_id = id(record)

            if record_id in transposed_connections:
                record["Final"] = "transpose"
                summary["transpose"] += 1
            elif record_id in valid_by_father and record_id in valid_by_mother:
                record["Final"] = "valid"
                summary["valid"] += 1
            else:
                record["Final"] = "maxVertex"
                summary["maxVertex"] += 1

        return summary

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Camada de Linhas de Entrada"),
                [QgsProcessing.TypeVectorLine],
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SENSOR_LIMIT,
                self.tr("Limite do Sensor"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=150,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPACING,
                self.tr("Espaçamento entre Partições"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=50,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_SEGMENT,
                self.tr("Mínimo de vértices por grupo"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=3,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PTS_PER_VTX,
                self.tr("Pts por Vtx"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=2,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr("Camada Padronizada (Spacing)")
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PERP_OUTPUT, self.tr("Sensores Primarios")
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(self.VERT_OUTPUT, self.tr("Vértices"))
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.SEC_PERP_OUTPUT, self.tr("Sensores Secundarios")
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PAIR_CONN_OUTPUT,
                self.tr("Conexoes por Par (SimpleConnectionJudge)"),
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        sensor_limit = self.parameterAsInt(parameters, self.SENSOR_LIMIT, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)
        min_segment = self.parameterAsInt(parameters, self.MIN_SEGMENT, context)
        pts_per_vtx = self.parameterAsInt(parameters, self.PTS_PER_VTX, context)
        primary_key_attr = "key_prim"
        secondary_key_attr = "keySec"

        if source is None:
            raise QgsProcessingException(self.tr("Camada de entrada inválida."))

        temp_fields = source.fields()
        temp_fields.append(QgsField(primary_key_attr, QVariant.String))

        output_fields = source.fields()
        output_fields.append(QgsField(primary_key_attr, QVariant.String))
        output_fields.append(QgsField(secondary_key_attr, QVariant.String))
        output_fields.append(QgsField("neighborE", QVariant.String))
        output_fields.append(QgsField("neighborD", QVariant.String))
        output_fields.append(QgsField("lenght", QVariant.Double))

        perp_fields = QgsFields()
        perp_fields.append(QgsField(primary_key_attr, QVariant.String))
        perp_fields.append(QgsField("keyVertex", QVariant.String))
        perp_fields.append(QgsField("keyS1", QVariant.String))
        perp_fields.append(QgsField("side", QVariant.String))
        perp_fields.append(QgsField("neighbor", QVariant.String))

        sec_perp_fields = QgsFields()
        sec_perp_fields.append(QgsField(secondary_key_attr, QVariant.String))
        sec_perp_fields.append(QgsField("keyVertex", QVariant.String))
        sec_perp_fields.append(QgsField("keyS1", QVariant.String))
        sec_perp_fields.append(QgsField("side", QVariant.String))
        sec_perp_fields.append(QgsField("neighbor", QVariant.String))

        vert_fields = QgsFields()
        vert_fields.append(QgsField(primary_key_attr, QVariant.String))
        vert_fields.append(QgsField("keyVertex", QVariant.String))
        vert_fields.append(QgsField(secondary_key_attr, QVariant.String))
        vert_fields.append(QgsField("neighborE", QVariant.String))
        vert_fields.append(QgsField("neighborD", QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            output_fields,
            source.wkbType(),
            source.sourceCrs(),
        )

        (perp_sink, perp_dest_id) = self.parameterAsSink(
            parameters,
            self.PERP_OUTPUT,
            context,
            perp_fields,
            QgsWkbTypes.LineString,
            source.sourceCrs(),
        )

        (vert_sink, vert_dest_id) = self.parameterAsSink(
            parameters,
            self.VERT_OUTPUT,
            context,
            vert_fields,
            QgsWkbTypes.Point,
            source.sourceCrs(),
        )

        (sec_perp_sink, sec_perp_dest_id) = self.parameterAsSink(
            parameters,
            self.SEC_PERP_OUTPUT,
            context,
            sec_perp_fields,
            QgsWkbTypes.LineString,
            source.sourceCrs(),
        )

        pair_conn_fields = QgsFields()
        pair_conn_fields.append(QgsField("pair_id", QVariant.Int))
        pair_conn_fields.append(QgsField("pair_status", QVariant.String))
        pair_conn_fields.append(QgsField("id_conexao", QVariant.Int))
        pair_conn_fields.append(QgsField("keyFather", QVariant.String))
        pair_conn_fields.append(QgsField("keyMother", QVariant.String))
        pair_conn_fields.append(QgsField("vtxKeyFather", QVariant.String))
        pair_conn_fields.append(QgsField("vtxKeyMother", QVariant.String))
        pair_conn_fields.append(QgsField("lenght", QVariant.Double))
        pair_conn_fields.append(QgsField("Cstatus", QVariant.String))
        pair_conn_fields.append(QgsField("Final", QVariant.String))

        (pair_conn_sink, pair_conn_dest_id) = self.parameterAsSink(
            parameters,
            self.PAIR_CONN_OUTPUT,
            context,
            pair_conn_fields,
            QgsWkbTypes.LineString,
            source.sourceCrs(),
        )

        source_features = list(source.getFeatures())
        standardized_records = []
        standardized_features = []

        for current, feature in enumerate(source_features):
            key_prim = f"O{current:04d}"
            standardized_record = VectorLayerGeometry.standardize_line_feature(
                feature, spacing, temp_fields, key=key_prim
            )
            standardized_records.append(standardized_record)
            standardized_features.append(standardized_record["feature"])

        (
            spatial_index,
            feat_dict,
            fid_to_primary_key,
        ) = VectorLayerGeometry.create_spatial_context(
            standardized_features, primary_key_attr
        )

        feature_count = len(standardized_records)
        total = 100.0 / feature_count if feature_count > 0 else 0
        global_sec_counter = 0
        secondary_segment_features = []
        secondary_sensor_features = []
        secondary_segment_id = 0
        segment_vertex_keys_by_keysec = {}

        for current, standardized_record in enumerate(standardized_records):
            if feedback.isCanceled():
                break

            points = standardized_record["points"]
            key_prim = standardized_record["key"]

            sensor_records = VectorLayerGeometry.generate_perpendicular_records(
                points, sensor_limit, key=key_prim
            )
            sensor_records = VectorLayerGeometry.trim_perpendicular_records(
                sensor_records,
                sensor_limit,
                spatial_index,
                feat_dict,
                standardized_record["feature"].id(),
                fid_to_primary_key,
                neighbor_key_attr_name=primary_key_attr,
            )

            vertex_records = VectorLayerGeometry.populate_vertex_neighbors(
                points, sensor_records, key=key_prim
            )
            global_sec_counter = VectorLayerGeometry.assign_keysec(
                vertex_records, global_sec_counter
            )
            VectorLayerGeometry.enforce_minimum_group_size(
                vertex_records, min_segment
            )
            segment_records = VectorLayerGeometry.partition_standardized_line(
                points,
                standardized_record["original_attrs"],
                vertex_records,
                key=key_prim,
            )

            for sensor_record in sensor_records:
                sensor_feature = QgsFeature(perp_fields)
                sensor_feature.setGeometry(sensor_record["geometry"])
                sensor_feature.setAttributes(
                    [
                        sensor_record["key"],
                        sensor_record["keyVertex"],
                        sensor_record["keyS1"],
                        sensor_record["side"],
                        sensor_record["neighbor"],
                    ]
                )
                perp_sink.addFeature(sensor_feature, QgsFeatureSink.FastInsert)

            for segment_record in segment_records:
                key_sec = segment_record.get("keySec")
                if key_sec not in (None, ""):
                    segment_vertex_keys_by_keysec[str(key_sec)] = list(
                        segment_record.get("vertex_keys") or []
                    )

                secondary_feature = QgsFeature(output_fields)
                secondary_feature.setId(secondary_segment_id)
                secondary_feature.setGeometry(segment_record["geometry"])
                secondary_feature.setAttributes(segment_record["attributes"])
                secondary_segment_features.append(secondary_feature)
                secondary_segment_id += 1

            for vertex_record in vertex_records:
                vertex_feature = QgsFeature(vert_fields)
                vertex_feature.setGeometry(
                    QgsGeometry.fromPointXY(vertex_record["point"])
                )
                vertex_feature.setAttributes(
                    [
                        vertex_record["key"],
                        vertex_record["keyVertex"],
                        vertex_record["keySec"],
                        vertex_record["neighborE"],
                        vertex_record["neighborD"],
                    ]
                )
                vert_sink.addFeature(vertex_feature, QgsFeatureSink.FastInsert)

            feedback.setProgress(int(current * total))

        (
            secondary_spatial_index,
            secondary_feat_dict,
            fid_to_secondary_key,
        ) = VectorLayerGeometry.create_spatial_context(
            secondary_segment_features, secondary_key_attr
        )

        for segment_feature in secondary_segment_features:
            segment_points = [
                point for point in segment_feature.geometry().vertices()
            ]
            if len(segment_points) < 2:
                continue

            secondary_sensor_records = (
                VectorLayerGeometry.generate_perpendicular_records(
                    segment_points,
                    sensor_limit,
                    key=segment_feature[secondary_key_attr],
                )
            )
            secondary_sensor_records = (
                VectorLayerGeometry.trim_perpendicular_records(
                    secondary_sensor_records,
                    sensor_limit,
                    secondary_spatial_index,
                    secondary_feat_dict,
                    segment_feature.id(),
                    fid_to_secondary_key,
                    neighbor_key_attr_name=secondary_key_attr,
                )
            )

            for sensor_record in secondary_sensor_records:
                sensor_feature = QgsFeature(sec_perp_fields)
                sensor_feature.setGeometry(sensor_record["geometry"])
                sensor_feature.setAttributes(
                    [
                        sensor_record["key"],
                        sensor_record["keyVertex"],
                        sensor_record["keyS1"],
                        sensor_record["side"],
                        sensor_record["neighbor"],
                    ]
                )
                secondary_sensor_features.append(sensor_feature)
                sec_perp_sink.addFeature(sensor_feature, QgsFeatureSink.FastInsert)

        secondary_sensor_features_e = [
            feature
            for feature in secondary_sensor_features
            if feature["side"] == "e"
        ]
        secondary_sensor_features_d = [
            feature
            for feature in secondary_sensor_features
            if feature["side"] == "d"
        ]

        neighbor_e_by_keysec = VectorLayerGeometry.get_most_common_target_by_key(
            secondary_sensor_features_e, secondary_key_attr, "neighbor"
        )
        neighbor_d_by_keysec = VectorLayerGeometry.get_most_common_target_by_key(
            secondary_sensor_features_d, secondary_key_attr, "neighbor"
        )

        output_field_names = output_fields.names()
        neighbor_e_index = output_field_names.index("neighborE")
        neighbor_d_index = output_field_names.index("neighborD")
        judge_layer = QgsVectorLayer("MultiLineString", "match_judge_preview", "memory")
        judge_features = []

        if judge_layer.isValid():
            judge_layer.setCrs(source.sourceCrs())
            judge_layer.dataProvider().addAttributes(
                [field for field in output_fields]
            )
            judge_layer.updateFields()

        for segment_feature in secondary_segment_features:
            output_attributes = VectorLayerGeometry.clear_attributes(
                segment_feature.attributes(),
                output_fields,
                ["neighborE", "neighborD"],
            )
            key_sec = segment_feature[secondary_key_attr]
            output_attributes[neighbor_e_index] = neighbor_e_by_keysec.get(key_sec)
            output_attributes[neighbor_d_index] = neighbor_d_by_keysec.get(key_sec)

            output_feature = QgsFeature(output_fields)
            output_feature.setGeometry(segment_feature.geometry())
            output_feature.setAttributes(output_attributes)
            sink.addFeature(output_feature, QgsFeatureSink.FastInsert)

            if judge_layer.isValid():
                judge_feature = QgsFeature(judge_layer.fields())
                judge_geometry = segment_feature.geometry()
                if judge_geometry and not judge_geometry.isEmpty():
                    judge_parts = (
                        judge_geometry.asMultiPolyline()
                        if judge_geometry.isMultipart()
                        else [judge_geometry.asPolyline()]
                    )
                    judge_feature.setGeometry(
                        QgsGeometry.fromMultiPolylineXY(judge_parts)
                    )
                judge_feature.setAttributes(output_attributes)
                judge_features.append(judge_feature)

        if judge_layer.isValid():
            judge_layer.dataProvider().addFeatures(judge_features)
            judge_layer.updateExtents()

            judge = MatchJudge(
                field_key_prim=primary_key_attr,
                field_key_sec=secondary_key_attr,
                field_neigh_e="neighborE",
                field_neigh_d="neighborD",
            )
            judge_result = judge.analyze(judge_layer)

            feedback.pushInfo("=== MatchJudge ===")
            feedback.pushInfo(
                "Resumo: validos={0} invalidos={1}".format(
                    len(judge_result["valid"]),
                    len(judge_result["invalid"]),
                )
            )
            feedback.pushInfo(judge.to_json(judge_result))

            for message in judge_result["log"]:
                feedback.pushInfo(message)

            judge_feature_by_keysec = {}
            for judge_feature in judge_result["layer"].getFeatures():
                key_sec = judge_feature[secondary_key_attr]
                if key_sec not in (None, ""):
                    judge_feature_by_keysec[str(key_sec)] = judge_feature

            pair_batches = [
                ("valid", judge_result["valid"]),
                ("invalid", judge_result["invalid"]),
            ]
            processed_pairs = 0
            pair_connection_records = []

            for pair_status, pairs in pair_batches:
                for key_a, key_b in pairs:
                    feat_a = judge_feature_by_keysec.get(str(key_a))
                    feat_b = judge_feature_by_keysec.get(str(key_b))

                    if feat_a is None or feat_b is None:
                        feedback.pushInfo(
                            "SimpleConnectionJudge: par ignorado por falta de geometria "
                            "apos MatchJudge ({0}, {1}).".format(key_a, key_b)
                        )
                        continue

                    order_a = (
                        str(feat_a[primary_key_attr] or ""),
                        str(feat_a[secondary_key_attr] or ""),
                    )
                    order_b = (
                        str(feat_b[primary_key_attr] or ""),
                        str(feat_b[secondary_key_attr] or ""),
                    )
                    if order_b < order_a:
                        feat_a, feat_b = feat_b, feat_a

                    geom_a = feat_a.geometry()
                    geom_b = feat_b.geometry()
                    if (
                        geom_a is None
                        or geom_b is None
                        or geom_a.isEmpty()
                        or geom_b.isEmpty()
                    ):
                        feedback.pushInfo(
                            "SimpleConnectionJudge: par ignorado por geometria vazia "
                            "({0}, {1}).".format(
                                feat_a[secondary_key_attr],
                                feat_b[secondary_key_attr],
                            )
                        )
                        continue

                    vertex_count_a = sum(1 for _ in geom_a.vertices())
                    vertex_count_b = sum(1 for _ in geom_b.vertices())
                    if vertex_count_a < 2 or vertex_count_b < 2:
                        feedback.pushInfo(
                            "SimpleConnectionJudge: par ignorado por possuir menos de 2 "
                            "vertices ({0}, {1}).".format(
                                feat_a[secondary_key_attr],
                                feat_b[secondary_key_attr],
                            )
                        )
                        continue

                    processed_pairs += 1
                    target_n = max(vertex_count_a - 1, vertex_count_b - 1, 1)
                    vertex_keys_a = segment_vertex_keys_by_keysec.get(
                        str(feat_a[secondary_key_attr]),
                        [],
                    )
                    vertex_keys_b = segment_vertex_keys_by_keysec.get(
                        str(feat_b[secondary_key_attr]),
                        [],
                    )
                    pair_connections = SimpleConnectionJudge.solve_nearest_with_criteria(
                        geom_a,
                        geom_b,
                        str(feat_a[secondary_key_attr]),
                        str(feat_b[secondary_key_attr]),
                        vertex_keys_a,
                        vertex_keys_b,
                    )

                    for connection in pair_connections:
                        connection_geom = connection["geom"]
                        pair_connection_records.append(
                            {
                                "pair_id": processed_pairs,
                                "pair_status": pair_status,
                                "id_conexao": connection.get("id", 0),
                                "keyFather": connection.get("keyFather"),
                                "keyMother": connection.get("keyMother"),
                                "vtxKeyFather": connection.get("vtxKeyFather"),
                                "vtxKeyMother": connection.get("vtxKeyMother"),
                                "lenght": VectorLayerGeometry.calculate_geometry_length(
                                    connection_geom
                                ),
                                "Cstatus": None,
                                "Final": None,
                                "geom": connection_geom,
                            }
                        )

            cstatus_summary = self._classify_pair_connection_statuses(
                pair_connection_records,
                SimpleConnectionJudge.ORPHAN_VERTEX_KEY,
            )
            final_summary = self._classify_pair_connection_final(
                pair_connection_records,
                SimpleConnectionJudge.ORPHAN_VERTEX_KEY,
                pts_per_vtx,
                secondary_spatial_index,
                secondary_feat_dict,
            )
            generated_pair_connections = len(pair_connection_records)

            for record in pair_connection_records:
                pair_feature = QgsFeature(pair_conn_fields)
                pair_feature.setGeometry(record["geom"])
                pair_feature.setAttributes(
                    [
                        record.get("pair_id", 0),
                        record.get("pair_status"),
                        record.get("id_conexao", 0),
                        record.get("keyFather"),
                        record.get("keyMother"),
                        record.get("vtxKeyFather"),
                        record.get("vtxKeyMother"),
                        record.get("lenght", 0.0),
                        record.get("Cstatus"),
                        record.get("Final"),
                    ]
                )
                pair_conn_sink.addFeature(
                    pair_feature,
                    QgsFeatureSink.FastInsert,
                )

            feedback.pushInfo("=== SimpleConnectionJudge ===")
            feedback.pushInfo(
                "Resumo: pares_processados={0} conexoes_geradas={1}".format(
                    processed_pairs,
                    generated_pair_connections,
                )
            )
            feedback.pushInfo(
                "Cstatus: normal={0} duplicated F={1} duplicated M={2} duplicated A={3}".format(
                    cstatus_summary.get("normal", 0),
                    cstatus_summary.get("duplicated F", 0),
                    cstatus_summary.get("duplicated M", 0),
                    cstatus_summary.get("duplicated A", 0),
                )
            )
            feedback.pushInfo(
                "Final (pts_por_vtx={0}, father+mother): valid={1} maxVertex={2} transpose={3}".format(
                    pts_per_vtx,
                    final_summary.get("valid", 0),
                    final_summary.get("maxVertex", 0),
                    final_summary.get("transpose", 0),
                )
            )
        else:
            feedback.pushInfo(
                "MatchJudge: nao foi possivel criar a camada temporaria de analise."
            )

        return {
            self.OUTPUT: dest_id,
            self.PERP_OUTPUT: perp_dest_id,
            self.SEC_PERP_OUTPUT: sec_perp_dest_id,
            self.VERT_OUTPUT: vert_dest_id,
            self.PAIR_CONN_OUTPUT: pair_conn_dest_id,
        }
