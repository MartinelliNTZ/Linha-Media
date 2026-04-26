# -*- coding: utf-8 -*-

import math
from qgis.core import QgsGeometry, QgsPointXY

class VectorLayerGeometry:
    """Classe genérica para manipulação de geometrias de camadas vetoriais."""

    @staticmethod
    def adjust_line_length(geometry, delta):
        """
        Estende ou reduz uma linha em ambas as extremidades.
        delta > 0: Estende a linha para fora.
        delta < 0: Reduz a linha para dentro (trim).
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
            
            # Ajuste do Início (Vértice 0)
            # Vetor do segundo para o primeiro ponto para definir a direção de saída
            p0 = polyline[0]
            p1 = polyline[1]
            dx0 = p0.x() - p1.x()
            dy0 = p0.y() - p1.y()
            dist0 = math.sqrt(dx0**2 + dy0**2)
            
            if dist0 > 0:
                new_poly[0] = QgsPointXY(p0.x() + (dx0/dist0) * delta, 
                                         p0.y() + (dy0/dist0) * delta)
            
            # Ajuste do Fim (Vértice n)
            # Vetor do penúltimo para o último ponto para definir a direção de saída
            pn = polyline[-1]
            pn_1 = polyline[-2]
            dxn = pn.x() - pn_1.x()
            dyn = pn.y() - pn_1.y()
            distn = math.sqrt(dxn**2 + dyn**2)
            
            if distn > 0:
                new_poly[-1] = QgsPointXY(pn.x() + (dxn/distn) * delta, 
                                          pn.y() + (dyn/distn) * delta)
            
            new_parts.append(new_poly)

        if is_multi:
            return QgsGeometry.fromMultiPolylineXY(new_parts)
        else:
            return QgsGeometry.fromPolylineXY(new_parts[0])