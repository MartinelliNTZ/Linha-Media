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

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        sensor_limit = self.parameterAsInt(parameters, self.SENSOR_LIMIT, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)
        min_segment = self.parameterAsInt(parameters, self.MIN_SEGMENT, context)

        if source is None:
            raise QgsProcessingException(self.tr("Camada de entrada inválida."))

        temp_fields = source.fields()
        temp_fields.append(QgsField("key_prim", QVariant.String))

        output_fields = source.fields()
        output_fields.append(QgsField("key_prim", QVariant.String))
        output_fields.append(QgsField("keySec", QVariant.String))
        output_fields.append(QgsField("neighborE", QVariant.String))
        output_fields.append(QgsField("neighborD", QVariant.String))

        perp_fields = QgsFields()
        perp_fields.append(QgsField("key_prim", QVariant.String))
        perp_fields.append(QgsField("keyVertex", QVariant.String))
        perp_fields.append(QgsField("keyS1", QVariant.String))
        perp_fields.append(QgsField("side", QVariant.String))
        perp_fields.append(QgsField("neighbor", QVariant.String))

        vert_fields = QgsFields()
        vert_fields.append(QgsField("key_prim", QVariant.String))
        vert_fields.append(QgsField("keyVertex", QVariant.String))
        vert_fields.append(QgsField("keySec", QVariant.String))
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

        source_features = list(source.getFeatures())
        standardized_records = []
        standardized_features = []

        for current, feature in enumerate(source_features):
            key_prim = f"O{current:04d}"
            standardized_record = VectorLayerGeometry.standardize_line_feature(
                feature, spacing, key_prim, temp_fields
            )
            standardized_records.append(standardized_record)
            standardized_features.append(standardized_record["feature"])

        spatial_index, feat_dict, fid_to_key_prim = VectorLayerGeometry.create_spatial_context(
            standardized_features, "key_prim"
        )

        feature_count = len(standardized_records)
        total = 100.0 / feature_count if feature_count > 0 else 0
        global_sec_counter = 0

        for current, standardized_record in enumerate(standardized_records):
            if feedback.isCanceled():
                break

            points = standardized_record["points"]
            key_prim = standardized_record["key_prim"]

            sensor_records = VectorLayerGeometry.generate_perpendicular_records(
                points, key_prim, sensor_limit
            )
            sensor_records = VectorLayerGeometry.trim_perpendicular_records(
                sensor_records,
                sensor_limit,
                spatial_index,
                feat_dict,
                standardized_record["feature"].id(),
                fid_to_key_prim,
                "key_prim",
            )

            vertex_records = VectorLayerGeometry.populate_vertex_neighbors(
                points, key_prim, sensor_records
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
                key_prim,
                vertex_records,
            )

            for sensor_record in sensor_records:
                sensor_feature = QgsFeature(perp_fields)
                sensor_feature.setGeometry(sensor_record["geometry"])
                sensor_feature.setAttributes(
                    [
                        sensor_record["key_prim"],
                        sensor_record["keyVertex"],
                        sensor_record["keyS1"],
                        sensor_record["side"],
                        sensor_record["neighbor"],
                    ]
                )
                perp_sink.addFeature(sensor_feature, QgsFeatureSink.FastInsert)

            for segment_record in segment_records:
                line_feature = QgsFeature(output_fields)
                line_feature.setGeometry(segment_record["geometry"])
                line_feature.setAttributes(segment_record["attributes"])
                sink.addFeature(line_feature, QgsFeatureSink.FastInsert)

            for vertex_record in vertex_records:
                vertex_feature = QgsFeature(vert_fields)
                vertex_feature.setGeometry(
                    QgsGeometry.fromPointXY(vertex_record["point"])
                )
                vertex_feature.setAttributes(
                    [
                        vertex_record["key_prim"],
                        vertex_record["keyVertex"],
                        vertex_record["keySec"],
                        vertex_record["neighborE"],
                        vertex_record["neighborD"],
                    ]
                )
                vert_sink.addFeature(vertex_feature, QgsFeatureSink.FastInsert)

            feedback.setProgress(int(current * total))

        return {
            self.OUTPUT: dest_id,
            self.PERP_OUTPUT: perp_dest_id,
            self.VERT_OUTPUT: vert_dest_id,
        }
