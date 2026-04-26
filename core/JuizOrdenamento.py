# -*- coding: utf-8 -*-

REGRAS = {
    'N*S':   {'pri': lambda p, _: -p, 'sec': lambda p, _:  p},
    'L*O':   {'pri': lambda p, _:  p, 'sec': lambda p, _: -p},
    'NO*SE': {'pri': lambda p, _:  p, 'sec': lambda p, _: -p},
    'SO*NE': {'pri': lambda p, _: -p, 'sec': lambda p, _:  p},
}

PERPENDICULAR = {
    'N*S': 'L*O', 'L*O': 'N*S',
    'NO*SE': 'SO*NE', 'SO*NE': 'NO*SE',
}


class JuizOrdenamento:
    """
    Recebe lista de QgsFeature (curvas classificadas) e um eixo primário.
    Devolve lista de (QgsFeature, ordem_espacial).

    Ordenamento baseado exclusivamente nas posições ponderadas
    lnPri e lnSec. Sem centroide. Sem soma. Sem média.
    Órfãos (sem nenhuma intersecção) ficam ao final, em ordem de chegada.
    """

    EPSILON = 0.5

    def __init__(self, eixo_primario):
        assert eixo_primario in REGRAS, 'Eixo invalido: %s' % eixo_primario
        self.eixo  = eixo_primario
        self.perp  = PERPENDICULAR[eixo_primario]
        self.r_pri = REGRAS[eixo_primario]['pri']
        self.r_sec = REGRAS[self.perp]['pri']

    # ── leitura ────────────────────────────────────────────────────────

    def _n_cols(self, feat, prefixo):
        i = 0
        while feat.fields().indexOf('%s%d' % (prefixo, i)) >= 0:
            i += 1
        return i

    def _pos_ponderada(self, feat, prefixo, n):
        """
        Posição contínua da curva no eixo indicado.
        Peso = 1/rank  (rank 1 = mais extremo = mais peso).
        Retorna (indices_cobertos, posicao) ou ([], None) se sem intersecção.
        """
        covered, sw, si = [], 0.0, 0.0
        for i in range(n):
            try:
                v = feat['%s%d' % (prefixo, i)]
                r = int(v) if v not in (None, '', 'NULL') else 0
            except Exception:
                r = 0
            if r > 0:
                covered.append(i)
                w   = 1.0 / r
                si += i * w
                sw += w
        return (covered, si / sw) if covered else ([], None)

    # ── perfil ─────────────────────────────────────────────────────────

    def _perfil(self, feat):
        n_pri = self._n_cols(feat, 'lnPri')
        n_sec = self._n_cols(feat, 'lnSec')
        _, pri_pos = self._pos_ponderada(feat, 'lnPri', n_pri)
        _, sec_pos = self._pos_ponderada(feat, 'lnSec', n_sec)
        return {
            'feat':    feat,
            'pri_pos': pri_pos,
            'sec_pos': sec_pos,
            'orfao':   pri_pos is None and sec_pos is None,
            'ordem':   None,
        }

    # ── chave ──────────────────────────────────────────────────────────

    def _chave(self, p):
        k1 = self.r_pri(p['pri_pos'], 0) if p['pri_pos'] is not None else None
        k2 = self.r_sec(p['sec_pos'], 0) if p['sec_pos'] is not None else None
        return (k1, k2)

    # ── julgamento ─────────────────────────────────────────────────────

    def julgar(self, features):
        from itertools import groupby

        perfis  = [self._perfil(f) for f in features]
        normais = [p for p in perfis if not p['orfao']]
        orfaos  = [p for p in perfis if p['orfao']]

        # Ordena: primário, depois secundário; None vai para o final
        def sort_key(p):
            k1, k2 = self._chave(p)
            return (
                0 if k1 is not None else 1,
                k1 if k1 is not None else 0.0,
                0 if k2 is not None else 1,
                k2 if k2 is not None else 0.0,
            )

        normais.sort(key=sort_key)

        # Agrupa por empate dentro do EPSILON
        contador  = 1
        chave_ant = None
        for p in normais:
            c = self._chave(p)
            if chave_ant is not None:
                k1_ant, k2_ant = chave_ant
                k1, k2 = c
                muda_pri = (k1 is None) != (k1_ant is None) or (
                    k1 is not None and k1_ant is not None and
                    abs(k1 - k1_ant) >= self.EPSILON
                )
                muda_sec = (k2 is None) != (k2_ant is None) or (
                    k2 is not None and k2_ant is not None and
                    abs(k2 - k2_ant) >= self.EPSILON
                )
                if muda_pri or muda_sec:
                    contador += 1
            p['ordem'] = contador
            chave_ant = c

        # Fragmentos (mesmo grupo): desempata pela posição secundária
        resultado = []
        for _, grupo in groupby(normais, key=lambda p: p['ordem']):
            membros = list(grupo)
            if len(membros) > 1:
                membros.sort(key=lambda p: (
                    0 if p['sec_pos'] is not None else 1,
                    self.r_sec(p['sec_pos'], 0) if p['sec_pos'] is not None else 0.0,
                ))
            for m in membros:
                m['ordem'] = len(resultado) + 1
                resultado.append(m)

        # Órfãos ao final, na ordem em que chegaram
        base = len(resultado)
        for i, p in enumerate(orfaos):
            p['ordem'] = base + i + 1
            resultado.append(p)

        return [(p['feat'], p['ordem']) for p in resultado]