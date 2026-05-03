"""
MatchJudge - analise de pares de linhas em QgsVectorLayer.

Uso:
    judge = MatchJudge(
        field_key_prim="key_prim",
        field_key_sec="keySec",
        field_neigh_e="neighborE",
        field_neigh_d="neighborD",
    )
    result = judge.analyze(layer)
    # result["layer"]   -> QgsVectorLayer analisada
    # result["valid"]   -> [ (keySecA, keySecB), ... ]
    # result["invalid"] -> [ (keySecA, keySecB), ... ]
"""

import json

from qgis.core import QgsVectorLayer


class MatchJudge:
    """
    Analisa pares de feicoes de linha a partir de relacoes de vizinhanca
    definidas nos atributos da layer.

    Campos esperados (configuraveis no construtor):
        key_prim  - chave da mae         ex: "O0001"
        key_sec   - chave da filha/linha ex: "S0003"
        neigh_e   - vizinho esquerdo que referencia este key_sec
        neigh_d   - vizinho direito que referencia este key_sec
    """

    def __init__(
        self,
        field_key_prim: str = "key_prim",
        field_key_sec: str = "keySec",
        field_neigh_e: str = "neighborE",
        field_neigh_d: str = "neighborD",
    ):
        self.f_prim = field_key_prim
        self.f_sec = field_key_sec
        self.f_ne = field_neigh_e
        self.f_nd = field_neigh_d

    def analyze(self, layer: QgsVectorLayer) -> dict:
        """
        Executa os 4 passos e retorna:
            {
                "layer":   QgsVectorLayer,   # analisada sem alterar geometria
                "valid":   [(ksA, ksB), ...],
                "invalid": [(ksA, ksB), ...],
                "log":     [str, ...],
            }
        """
        log = []

        index = self._build_index(layer, log)
        all_pairs = self._build_pairs(layer, index, log)
        log.append(f"[3] Pares unicos apos deduplicacao: {len(all_pairs)}")
        valid, invalid = self._classify(all_pairs, index, log)
        log.append(
            f"[4] Resultado final -> validos={len(valid)} invalidos={len(invalid)}"
        )

        return {
            "layer": layer,
            "valid": valid,
            "invalid": invalid,
            "log": log,
        }

    def to_json(self, result: dict, indent: int = 2) -> str:
        """Serializa valid/invalid para JSON (tuplas viram listas)."""
        return json.dumps(
            {
                "valid": [list(pair) for pair in result["valid"]],
                "invalid": [list(pair) for pair in result["invalid"]],
            },
            indent=indent,
            ensure_ascii=False,
        )

    def _build_index(self, layer: QgsVectorLayer, log: list) -> dict:
        """
        Passo 1 - percorre a layer uma vez e constroi:
            index : { key_sec -> QgsFeature }
        """
        index = {}
        total = 0.0

        for feat in layer.getFeatures():
            ks = feat[self.f_sec]
            if not ks:
                continue

            geom = feat.geometry()
            total += geom.length() if (geom and not geom.isEmpty()) else 0.0
            index[ks] = feat

        log.append(
            f"[1] Feicoes indexadas: {len(index)}  |  "
            f"comprimento total (geometria): {total:.4f}"
        )
        return index

    def _build_pairs(self, layer: QgsVectorLayer, index: dict, log: list) -> list:
        """
        Monta pares validos entre linhas, impedindo:
            - duplicatas
            - auto referencia
            - incesto (mesmo key_prim)
        """
        seen = set()
        pairs = []
        incest_blocked = 0

        for feat in layer.getFeatures():
            ks_a = feat[self.f_sec]
            kp_a = feat[self.f_prim]

            if not ks_a:
                continue

            for nb in (feat[self.f_ne], feat[self.f_nd]):
                if not nb or nb not in index:
                    continue

                feat_b = index.get(nb)
                if feat_b is None:
                    continue

                ks_b = feat_b[self.f_sec]
                kp_b = feat_b[self.f_prim]

                if ks_a == ks_b:
                    continue

                if kp_a == kp_b:
                    incest_blocked += 1
                    log.append(
                        f"    INCESTO BLOQUEADO: {ks_a} <-> {ks_b} (key_prim={kp_a})"
                    )
                    continue

                key = frozenset({ks_a, ks_b})
                if key in seen:
                    continue

                seen.add(key)
                pairs.append(key)

        log.append(f"[2] Pares brutos montados: {len(pairs)}")
        log.append(f"[2.1] Pares bloqueados por incesto: {incest_blocked}")
        return pairs

    def _classify(self, pairs: list, index: dict, log: list) -> tuple:
        """
        Passo 4 - para cada par decide: valido ou invalido.

        Vela: A referencia B e B referencia A nos campos de vizinho.
        Quando ha vela, o par e tratado como invalido sem tentar mesclar irmas.

        Retorna (valid_list, invalid_list) de tuplas (ksA, ksB).
        """
        valid = []
        invalid = []

        for pair_key in pairs:
            ks_a, ks_b = tuple(pair_key)
            feat_a = index.get(ks_a)
            feat_b = index.get(ks_b)

            if feat_a is None or feat_b is None:
                continue

            a_refs_b = feat_a[self.f_ne] == ks_b or feat_a[self.f_nd] == ks_b
            b_refs_a = feat_b[self.f_ne] == ks_a or feat_b[self.f_nd] == ks_a
            is_candle = a_refs_b and b_refs_a

            if is_candle:
                invalid.append((ks_a, ks_b))
                log.append(f"    INVALIDO: {ks_a} <-> {ks_b} (vela)")
                continue

            valid.append((ks_a, ks_b))
            log.append(f"    VALIDO  : {ks_a} <-> {ks_b}")

        return valid, invalid
