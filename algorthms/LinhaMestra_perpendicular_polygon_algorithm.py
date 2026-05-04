# -*- coding: utf-8 -*-

import math

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from ..core.vector_utils import VectorUtils


class LinhaPerpendicularPoligonoAlgorithm(QgsProcessingAlgorithm):
    INPUT_POLYGON = "INPUT_POLYGON"
    INPUT_LINES_MAES = "INPUT_LINES_MAES"
    DISTANCE = "DISTANCE"
    ESTILO_CONEXAO = "ESTILO_CONEXAO"
    TRIM_COLLISION = "TRIM_COLLISION"
    OUTPUT = "OUTPUT"

    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_POLYGON,
                self.tr("Camada de Poligonos (para gerar perpendiculares)"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINES_MAES,
                self.tr("Camada de Linhas Maes (Opcional - 2 feicoes)"),
                [QgsProcessing.TypeVectorLine],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DISTANCE,
                self.tr("Distancia Fixa (se nao houver Linhas Maes)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=500,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.ESTILO_CONEXAO,
                self.tr("Estilo de Conexao"),
                options=["Proximidade", "Perpendicular"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.TRIM_COLLISION,
                self.tr("Cortar segmentos na colisao com outras feicoes"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Linhas Perpendiculares Geradas"),
                QgsProcessing.TypeVectorLine,
            )
        )

    def shortHelpString(self):
        return self.tr(
            "Gera segmentos perpendiculares a partir dos vertices do anel externo "
            "dos poligonos. Por enquanto, apenas o tipo de entrada foi ajustado; "
            "a logica principal permanece equivalente a versao de linhas."
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_polygon_source = self.parameterAsSource(
            parameters, self.INPUT_POLYGON, context
        )
        input_maes_source = self.parameterAsSource(
            parameters, self.INPUT_LINES_MAES, context
        )
        distance = self.parameterAsDouble(parameters, self.DISTANCE, context)
        estilo_conexao = self.parameterAsInt(parameters, self.ESTILO_CONEXAO, context)
        trim_collision = self.parameterAsBool(
            parameters, self.TRIM_COLLISION, context
        )

        if input_polygon_source is None:
            raise QgsProcessingException(
                self.tr("Camada de poligonos de entrada invalida.")
            )

        mother_line1_geom = None
        mother_line2_geom = None

        if input_maes_source:
            maes_features = list(input_maes_source.getFeatures())
            if len(maes_features) != 2:
                raise QgsProcessingException(
                    self.tr(
                        "A camada de Linhas Maes deve conter exatamente 2 feicoes."
                    )
                )

            mother_line1_geom = maes_features[0].geometry()
            mother_line2_geom = maes_features[1].geometry()

            if input_maes_source.sourceCrs() != input_polygon_source.sourceCrs():
                feedback.pushInfo(
                    self.tr(
                        "Reprojetando Linhas Maes para o CRS da camada de entrada..."
                    )
                )
                mother_line1_geom = VectorUtils.reproject_geometry(
                    mother_line1_geom,
                    input_maes_source.sourceCrs(),
                    input_polygon_source.sourceCrs(),
                    context,
                )
                mother_line2_geom = VectorUtils.reproject_geometry(
                    mother_line2_geom,
                    input_maes_source.sourceCrs(),
                    input_polygon_source.sourceCrs(),
                    context,
                )

            mother_line1_geom = VectorUtils.orient_northwest(mother_line1_geom)
            mother_line2_geom = VectorUtils.orient_northwest(mother_line2_geom)

        fields_output = QgsFields()
        fields_output.append(QgsField("parent_id", QVariant.LongLong))
        fields_output.append(QgsField("vertex_id", QVariant.Int))
        fields_output.append(QgsField("azimuth", QVariant.Double))
        fields_output.append(QgsField("touch_id", QVariant.LongLong))
        fields_output.append(QgsField("side", QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields_output,
            QgsWkbTypes.LineString,
            input_polygon_source.sourceCrs(),
        )

        spatial_index = QgsSpatialIndex(input_polygon_source.getFeatures())
        feat_dict = {feature.id(): feature for feature in input_polygon_source.getFeatures()}

        total_features = input_polygon_source.featureCount()
        max_ray_len = (distance / 2.0) if not mother_line1_geom else 10000.0

        for current_feat_idx, feature in enumerate(input_polygon_source.getFeatures()):
            if feedback.isCanceled():
                break

            rings = self._extract_exterior_rings(feature.geometry())
            vertex_offset = 0

            for ring in rings:
                if len(ring) < 3:
                    vertex_offset += len(ring)
                    continue

                for v_idx, vertex in enumerate(ring):
                    p_start = QgsPointXY(vertex.x(), vertex.y())
                    az_local = self._get_ring_vertex_azimuth(ring, v_idx)
                    dirs = [(az_local + 90) % 360, (az_local - 90) % 360]

                    for az_ray in dirs:
                        ray_geom = QgsGeometry.fromPolylineXY(
                            [
                                p_start,
                                self._project_point(p_start, az_ray, max_ray_len),
                            ]
                        )

                        hit_geom = None
                        hit_id = -1
                        impact_pt = None
                        min_dist = float("inf")

                        if mother_line1_geom:
                            for mother_geometry in [
                                mother_line1_geom,
                                mother_line2_geom,
                            ]:
                                intersection = ray_geom.intersection(mother_geometry)
                                if not intersection.isEmpty():
                                    point = VectorUtils._get_closest_point(
                                        intersection, p_start
                                    )
                                    if point:
                                        distance_to_hit = p_start.distance(point)
                                        if distance_to_hit < min_dist:
                                            min_dist = distance_to_hit
                                            hit_geom = mother_geometry
                                            impact_pt = point

                        if trim_collision:
                            candidates = spatial_index.intersects(
                                ray_geom.boundingBox()
                            )
                            for candidate_id in candidates:
                                if candidate_id == feature.id():
                                    continue

                                intersection = ray_geom.intersection(
                                    feat_dict[candidate_id].geometry()
                                )
                                if not intersection.isEmpty():
                                    point = VectorUtils._get_closest_point(
                                        intersection, p_start
                                    )
                                    if point:
                                        distance_to_hit = p_start.distance(point)
                                        if 0.001 < distance_to_hit < min_dist:
                                            min_dist = distance_to_hit
                                            hit_geom = feat_dict[candidate_id].geometry()
                                            hit_id = candidate_id
                                            impact_pt = point

                        if hit_geom is None:
                            if estilo_conexao == 0:
                                continue
                            final_p_end = self._project_point(
                                p_start, az_ray, max_ray_len
                            )
                            touch_id = -1
                        else:
                            if estilo_conexao == 0:
                                p_prox = VectorUtils._get_closest_point(
                                    hit_geom, p_start
                                )
                                final_p_end = p_prox if p_prox else impact_pt
                                touch_id = hit_id
                            else:
                                final_p_end = impact_pt
                                touch_id = hit_id

                        feat_out = QgsFeature(fields_output)
                        feat_out.setGeometry(
                            QgsGeometry.fromPolylineXY([p_start, final_p_end])
                        )
                        feat_out.setAttributes(
                            [
                                feature.id(),
                                vertex_offset + v_idx + 1,
                                az_ray,
                                int(touch_id),
                                VectorUtils.get_cardinal_direction(az_ray),
                            ]
                        )
                        sink.addFeature(feat_out, QgsFeatureSink.FastInsert)

                vertex_offset += len(ring)

            feedback.setProgress(
                int(((current_feat_idx + 1) / total_features) * 100)
                if total_features
                else 0
            )

        return {self.OUTPUT: dest_id}

    def _extract_exterior_rings(self, geometry):
        if geometry is None or geometry.isEmpty():
            return []

        polygons = (
            geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
        )
        rings = []

        for polygon in polygons:
            if not polygon:
                continue

            exterior_ring = self._normalize_ring(polygon[0])
            if exterior_ring:
                rings.append(exterior_ring)

        return rings

    def _normalize_ring(self, ring):
        normalized_ring = [
            QgsPointXY(point.x(), point.y())
            for point in ring
        ]
        if (
            len(normalized_ring) > 1
            and normalized_ring[0].x() == normalized_ring[-1].x()
            and normalized_ring[0].y() == normalized_ring[-1].y()
        ):
            normalized_ring = normalized_ring[:-1]
        return normalized_ring

    def _get_ring_vertex_azimuth(self, ring, index):
        total = len(ring)
        if total < 2:
            return 0.0
        if total == 2:
            return ring[0].azimuth(ring[1])

        current_point = ring[index]
        previous_point = ring[(index - 1) % total]
        next_point = ring[(index + 1) % total]

        az1 = previous_point.azimuth(current_point)
        az2 = current_point.azimuth(next_point)
        diff = az2 - az1
        if diff > 180:
            diff -= 360
        if diff < -180:
            diff += 360
        return (az1 + diff / 2.0) % 360

    def _project_point(self, start_point, azimuth, distance):
        radians = math.radians(azimuth)
        return QgsPointXY(
            start_point.x() + distance * math.sin(radians),
            start_point.y() + distance * math.cos(radians),
        )

    def name(self):
        return "linha_perpendicular_media_poligono"

    def displayName(self):
        return self.tr("Gerador de Perpendiculares Medias (Poligono)")

    def group(self):
        return self.tr("Linha Mestra")

    def groupId(self):
        return "linhamestra"

    def tr(self, string):
        return QCoreApplication.translate(
            "LinhaPerpendicularPoligonoAlgorithm", string
        )

    def createInstance(self):
        return LinhaPerpendicularPoligonoAlgorithm()
