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

    METODO_ARBITRARIO = 0
    METODO_BORDA = 1
    METODO_GRAFO = 2

    EPSILON = 0.5

    def __init__(self, eixo_primario, use_secondary=True):
        assert eixo_primario in REGRAS, 'Eixo invalido: %s' % eixo_primario
        self.eixo  = eixo_primario
        self.perp  = PERPENDICULAR[eixo_primario]
        self.r_pri = REGRAS[eixo_primario]['pri']
        self.r_sec = REGRAS[self.perp]['pri']
        self.use_secondary = use_secondary

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

    def _borda_score(self, feat):
        """Média das posições (ranks) atribuídas e contagem de votos (hits)."""
        ranks = []
        prefixes = ['lnPri', 'lnSec'] if self.use_secondary else ['lnPri']
        for prefix in prefixes:
            n = self._n_cols(feat, prefix)
            for i in range(n):
                try:
                    v = feat['%s%d' % (prefix, i)]
                    r = int(v) if v not in (None, '', 'NULL') else 0
                    if r > 0: ranks.append(r)
                except: continue
        if not ranks:
            return None, 0
        return sum(ranks) / len(ranks), len(ranks)

    def _calc_grafo_scores(self, perfis):
        """
        Implementa agregação por Grafo de Precedência (Método de Copeland).
        Calcula vitórias e derrotas em confrontos diretos entre cada par de curvas.
        """
        n = len(perfis)
        # matriz_confrontos[i][j] = quantas vezes a curva i veio antes da curva j
        matriz = [[0] * n for _ in range(n)]
        
        # 1. Mapear sensores (colunas lnPri/lnSec) para quem eles viram
        sensores = {} # { 'col_name': [(rank, perf_idx), ...] }
        for idx, p in enumerate(perfis):
            feat = p['feat']
            prefixes = ['lnPri', 'lnSec'] if self.use_secondary else ['lnPri']
            for prefix in prefixes:
                n_cols = self._n_cols(feat, prefix)
                for i in range(n_cols):
                    col = f"{prefix}{i}"
                    try:
                        r = int(feat[col]) if feat[col] not in (None, '', 'NULL') else 0
                        if r > 0:
                            if col not in sensores: sensores[col] = []
                            sensores[col].append((r, idx))
                    except: continue

        # 2. Preencher matriz de precedência (Pairwise Comparison)
        for col, hits in sensores.items():
            hits.sort() # Ordena pelo rank que o sensor deu
            for i in range(len(hits)):
                for j in range(i + 1, len(hits)):
                    vencedor_idx = hits[i][1]
                    perdedor_idx = hits[j][1]
                    matriz[vencedor_idx][perdedor_idx] += 1

        # 3. Calcular Score de Copeland (Vitórias Líquidas)
        scores = [0] * n
        for i in range(n):
            for j in range(i + 1, n):
                if matriz[i][j] > matriz[j][i]:
                    scores[i] += 1
                    scores[j] -= 1
                elif matriz[j][i] > matriz[i][j]:
                    scores[j] += 1
                    scores[i] -= 1
        return scores

    # ── perfil ─────────────────────────────────────────────────────────

    def _perfil(self, feat):
        n_pri = self._n_cols(feat, 'lnPri')
        n_sec = self._n_cols(feat, 'lnSec') if self.use_secondary else 0
        _, pri_pos = self._pos_ponderada(feat, 'lnPri', n_pri)
        _, sec_pos = self._pos_ponderada(feat, 'lnSec', n_sec) if self.use_secondary else ([], None)
        b_avg, b_hits = self._borda_score(feat)

        return {
            'feat':    feat,
            'pri_pos': pri_pos,
            'sec_pos': sec_pos,
            'borda_avg': b_avg,
            'borda_hits': b_hits,
            'grafo_score': 0, # Populado depois se necessário
            'orfao':   pri_pos is None and sec_pos is None,
            'ordem':   None,
        }

    # ── chave ──────────────────────────────────────────────────────────

    def _chave(self, p):
        k1 = self.r_pri(p['pri_pos'], 0) if p['pri_pos'] is not None else None
        k2 = self.r_sec(p['sec_pos'], 0) if p['sec_pos'] is not None else None
        return (k1, k2)

    # ── julgamento ─────────────────────────────────────────────────────

    def julgar(self, features, metodo=METODO_BORDA):
        from itertools import groupby

        perfis  = [self._perfil(f) for f in features]
        normais = [p for p in perfis if not p['orfao']]
        orfaos  = [p for p in perfis if p['orfao']]

        # Se for método de grafo, calcula os scores globais antes de ordenar
        if metodo == self.METODO_GRAFO and normais:
            g_scores = self._calc_grafo_scores(normais)
            for i, p in enumerate(normais):
                p['grafo_score'] = g_scores[i]

        def sort_key(p):
            if metodo == self.METODO_GRAFO:
                # Ordena pelo Score de Copeland (mais vitórias primeiro)
                # Desempate pelo Borda e depois Espacial
                return (
                    -p['grafo_score'],
                    p['borda_avg'] if p['borda_avg'] is not None else 999999,
                    -p['borda_hits']
                )

            if metodo == self.METODO_BORDA:
                # 1. Média de Ranks (Borda)
                # 2. Total de Votos (Hits) - maior primeiro (mais confiança)
                # 3. Posição Espacial (Desempate)
                avg = p['borda_avg'] if p['borda_avg'] is not None else 999999
                k1, k2 = self._chave(p)
                return (
                    avg,
                    -p['borda_hits'],
                    0 if k1 is not None else 1,
                    k1 if k1 is not None else 0.0,
                    0 if k2 is not None else 1,
                    k2 if k2 is not None else 0.0,
                )

            # METODO_ARBITRARIO: Ordena: primário, depois secundário
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
            c = sort_key(p)
            if chave_ant is not None:
                if metodo == self.METODO_ARBITRARIO:
                    k1_ant, k2_ant = chave_ant[1], chave_ant[3]
                    k1, k2 = c[1], c[3]
                    muda_pri = (k1 is None) != (k1_ant is None) or (
                        k1 is not None and k1_ant is not None and
                        abs(k1 - k1_ant) >= self.EPSILON
                    )
                    muda_sec = (k2 is None) != (k2_ant is None) or (
                        k2 is not None and k2_ant is not None and
                        abs(k2 - k2_ant) >= self.EPSILON
                    )
                    if muda_pri or muda_sec: contador += 1
                else:
                    # No Borda, qualquer mudança na chave de ordenação gera nova ordem
                    if c != chave_ant: contador += 1

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