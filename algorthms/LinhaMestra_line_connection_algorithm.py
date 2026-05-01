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
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from ..core.VectorLayerGeometry import VectorLayerGeometry


class LinhaMestraLineConnectionAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    SENSOR_LIMIT = "SENSOR_LIMIT"
    SPACING = "SPACING"
    MIN_SEGMENT = "MIN_SEGMENT"
    OUTPUT = "OUTPUT"
    PERP_OUTPUT = "PERP_OUTPUT"
    SEC_PERP_OUTPUT = "SEC_PERP_OUTPUT"
    VERT_OUTPUT = "VERT_OUTPUT"

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
                defaultValue=400,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPACING,
                self.tr("Espaçamento entre Partições"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=25.0,
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

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        sensor_limit = self.parameterAsInt(parameters, self.SENSOR_LIMIT, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)
        min_segment = self.parameterAsInt(parameters, self.MIN_SEGMENT, context)
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

        return {
            self.OUTPUT: dest_id,
            self.PERP_OUTPUT: perp_dest_id,
            self.SEC_PERP_OUTPUT: sec_perp_dest_id,
            self.VERT_OUTPUT: vert_dest_id,
        }
