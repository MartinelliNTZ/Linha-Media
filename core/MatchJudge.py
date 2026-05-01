"""
MatchJudge — análise de pares de linhas em QgsVectorLayer.

Uso:
    judge = MatchJudge(
        field_key_prim = "key_prim",
        field_key_sec  = "keySec",
        field_neigh_e  = "neighborE",
        field_neigh_d  = "neighborD",
    )
    result = judge.analyze(layer)
    # result["layer"]   -> QgsVectorLayer modificada
    # result["valid"]   -> [ (keySecA, keySecB), ... ]
    # result["invalid"] -> [ (keySecA, keySecB), ... ]
"""

import json
from qgis.core import QgsFeatureRequest, QgsVectorLayer


class MatchJudge:
    """
    Analisa pares de feições de linha a partir de relações de vizinhança
    definidas nos atributos da layer.

    Campos esperados (configuráveis no construtor):
        key_prim  — chave da mãe         ex: "O0001"
        key_sec   — chave da filha/linha  ex: "S0003"
        neigh_e   — vizinho esquerdo que referencia este key_sec
        neigh_d   — vizinho direito  que referencia este key_sec
    """

    def __init__(
        self,
        field_key_prim: str = "key_prim",
        field_key_sec:  str = "keySec",
        field_neigh_e:  str = "neighborE",
        field_neigh_d:  str = "neighborD",
    ):
        self.f_prim  = field_key_prim
        self.f_sec   = field_key_sec
        self.f_ne    = field_neigh_e
        self.f_nd    = field_neigh_d

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def analyze(self, layer: QgsVectorLayer) -> dict:
        """
        Executa os 4 passos e retorna:
            {
                "layer":   QgsVectorLayer,   # modificada se houve mescla
                "valid":   [(ksA, ksB), ...],
                "invalid": [(ksA, ksB), ...],
                "log":     [str, ...],
            }
        """
        log = []

        # ── Passo 1: indexar feições + comprimento real pela geometria ─────────
        index, lengths, siblings = self._build_index(layer, log)

        # ── Passo 2: montar todos os pares possíveis ──────────────────────────
        all_pairs = self._build_pairs(layer, index, log)

        # ── Passo 3: limpar A↔B == B→A (já garantido no passo 2 via frozenset) ─
        log.append(f"[3] Pares únicos após deduplicação: {len(all_pairs)}")

        # ── Passo 4: classificar pares — vela → tenta mesclar ─────────────────
        valid, invalid = self._classify(layer, all_pairs, index, lengths, siblings, log)

        log.append(
            f"[4] Resultado final → válidos={len(valid)}  inválidos={len(invalid)}"
        )

        return {
            "layer":   layer,
            "valid":   valid,
            "invalid": invalid,
            "log":     log,
        }

    def to_json(self, result: dict, indent: int = 2) -> str:
        """Serializa valid/invalid para JSON (tuplas viram listas)."""
        return json.dumps(
            {
                "valid":   [list(p) for p in result["valid"]],
                "invalid": [list(p) for p in result["invalid"]],
            },
            indent=indent,
            ensure_ascii=False,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Passos internos
    # ──────────────────────────────────────────────────────────────────────────

    def _build_index(self, layer: QgsVectorLayer, log: list) -> tuple:
        """
        Passo 1 — percorre a layer UMA vez e constrói:
            index    : { key_sec -> QgsFeature }
            lengths  : { key_sec -> float }  comprimento via geometria
            siblings : { key_prim -> [key_sec, ...] }
        """
        index    = {}
        lengths  = {}
        siblings = {}

        for feat in layer.getFeatures():
            ks = feat[self.f_sec]
            kp = feat[self.f_prim]
            if not ks:
                continue

            geom = feat.geometry()
            length = geom.length() if (geom and not geom.isEmpty()) else 0.0

            index[ks]   = feat
            lengths[ks] = length

            siblings.setdefault(kp, [])
            siblings[kp].append(ks)

        total = sum(lengths.values())
        log.append(
            f"[1] Feições indexadas: {len(index)}  |  "
            f"comprimento total (geometria): {total:.4f}"
        )
        return index, lengths, siblings

    # ─────────────────────────────────────────────────────────────────────────

    def _build_pairs(
        self, layer: QgsVectorLayer, index: dict, log: list
    ) -> list:
        """
        Passo 2 — para cada feição A, olha neighborE e neighborD.
        Se o vizinho existe na layer → forma um par.
        Passo 3 embutido: frozenset garante A↔B == B↔A sem duplicatas.

        Retorna lista de frozenset({ks_a, ks_b}).
        """
        seen   = set()
        pairs  = []

        for feat in layer.getFeatures():
            ks_a = feat[self.f_sec]
            if not ks_a:
                continue

            for nb in (feat[self.f_ne], feat[self.f_nd]):
                if not nb or nb not in index:
                    continue
                key = frozenset({ks_a, nb})
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(key)

        log.append(f"[2] Pares brutos montados: {len(pairs)}")
        return pairs

    # ─────────────────────────────────────────────────────────────────────────

    def _classify(
        self,
        layer:    QgsVectorLayer,
        pairs:    list,
        index:    dict,
        lengths:  dict,
        siblings: dict,
        log:      list,
    ) -> tuple:
        """
        Passo 4 — para cada par decide: válido, vela-mesclável ou inválido.

        Vela: A referencia B  E  B referencia A nos campos de vizinho.

        Regras de mescla (quando vela detectada):
            Busca irmão C de A (mesmo key_prim, keySec ≠ A) tal que:
                1. len(A) > len(C)         — A é maior
                2. neighborD(A) == neighborD(C)  — mesmo lado direito
            Se encontrar C → mescla geometria de C em A, remove C da layer.
            Caso contrário → tenta o mesmo pelo lado de B.
            Se nenhum lado conseguir mesclar → par inválido.

        Retorna (valid_list, invalid_list) de tuplas (ksA, ksB).
        """
        valid   = []
        invalid = []
        already_merged = set()   # key_secs absorvidos — não reutilizar como C

        layer.startEditing()

        for pair_key in pairs:
            ks_a, ks_b = tuple(pair_key)

            # Recarregar feições (podem ter sido editadas numa iteração anterior)
            feat_a = self._reload(layer, ks_a, index)
            feat_b = self._reload(layer, ks_b, index)

            if feat_a is None or feat_b is None:
                # Feição foi deletada numa mescla anterior — ignorar par
                continue

            # ── Verificar se é vela ───────────────────────────────────────────
            a_refs_b = feat_a[self.f_ne] == ks_b or feat_a[self.f_nd] == ks_b
            b_refs_a = feat_b[self.f_ne] == ks_a or feat_b[self.f_nd] == ks_a
            is_candle = a_refs_b and b_refs_a

            if not is_candle:
                valid.append((ks_a, ks_b))
                log.append(f"    VÁLIDO  : {ks_a} ↔ {ks_b}")
                continue

            log.append(f"    VELA    : {ks_a} ↔ {ks_b}  → tentando mescla...")

            # ── Tentar mesclar pelo lado A ────────────────────────────────────
            merged = self._try_merge(
                layer, feat_a, ks_a, lengths, siblings, already_merged, index, log
            )

            # ── Se não conseguiu, tentar pelo lado B ─────────────────────────
            if not merged:
                merged = self._try_merge(
                    layer, feat_b, ks_b, lengths, siblings, already_merged, index, log
                )

            if merged:
                valid.append((ks_a, ks_b))
                log.append(f"    MESCLADO→VÁLIDO: {ks_a} ↔ {ks_b}")
            else:
                invalid.append((ks_a, ks_b))
                log.append(f"    INVÁLIDO: {ks_a} ↔ {ks_b}  (vela sem irmão mesclável)")

        layer.commitChanges()
        return valid, invalid

    # ──────────────────────────────────────────────────────────────────────────
    # Auxiliares
    # ──────────────────────────────────────────────────────────────────────────

    def _try_merge(
        self,
        layer:          QgsVectorLayer,
        feat_main:      object,          # QgsFeature de A (ou B)
        ks_main:        str,
        lengths:        dict,
        siblings:       dict,
        already_merged: set,
        index:          dict,
        log:            list,
    ) -> bool:
        """
        Procura irmão C de feat_main que satisfaça as 3 condições e, se
        encontrar, funde a geometria de C em feat_main na layer.

        Condições:
            1. C é irmão de A  (mesmo key_prim, keySec diferente)
            2. len(A) > len(C) usando comprimento calculado pela geometria
            3. neighborD(A) == neighborD(C)  e ambos não vazios

        Retorna True se mescla realizada, False caso contrário.
        """
        kp_main = feat_main[self.f_prim]
        nd_main = feat_main[self.f_nd]
        len_main = lengths.get(ks_main, 0.0)

        for ks_c in siblings.get(kp_main, []):
            if ks_c == ks_main:
                continue                     # não comparar consigo mesmo
            if ks_c in already_merged:
                continue                     # C já foi consumido

            feat_c = self._reload(layer, ks_c, index)
            if feat_c is None:
                continue                     # já deletado

            len_c = lengths.get(ks_c, 0.0)
            nd_c  = feat_c[self.f_nd]

            # Condição 1: A > C
            if len_main <= len_c:
                continue

            # Condição 2: mesmo neighborD, não vazio
            if not nd_main or nd_c != nd_main:
                continue

            # ── Mesclar: combinar geometrias e deletar C ──────────────────
            geom_main   = feat_main.geometry()
            geom_c      = feat_c.geometry()
            merged_geom = geom_main.combine(geom_c)

            layer.changeGeometry(feat_main.id(), merged_geom)
            layer.deleteFeature(feat_c.id())

            # Atualizar índice de comprimentos com o novo comprimento real
            lengths[ks_main] = merged_geom.length()
            already_merged.add(ks_c)

            log.append(
                f"      mescla: {ks_main} absorveu {ks_c} "
                f"[len_A={len_main:.4f} > len_C={len_c:.4f}, "
                f"neighborD='{nd_main}']"
            )
            return True

        return False

    def _reload(self, layer: QgsVectorLayer, ks: str, index: dict):
        """
        Retorna a feição atualizada da layer para o keySec dado.
        Usa getFeatures com filtro de atributo para pegar o estado atual.
        Retorna None se a feição não existir mais (foi deletada).
        """
        escaped_ks = str(ks).replace("'", "''")
        request = QgsFeatureRequest().setFilterExpression(
            f'"{self.f_sec}" = \'{escaped_ks}\''
        )
        return next(layer.getFeatures(request), None)


# ─── Uso no console Python do QGIS ───────────────────────────────────────────
#
#   from match_judge import MatchJudge
#
#   judge = MatchJudge(
#       field_key_prim = "key_prim",
#       field_key_sec  = "keySec",
#       field_neigh_e  = "neighborE",
#       field_neigh_d  = "neighborD",
#   )
#
#   layer  = layer a ser analisada
#   result = judge.analyze(layer)
#
#   print(judge.to_json(result))
#
#   for msg in result["log"]:
#       print(msg)
