# -*- coding: utf-8 -*-
"""
JuizOrdenamento.py — Versão 3.0
================================
Juiz inteligente de ordenamento de curvas de nível.

Pipeline completo
-----------------
1. Montar perfis de cada curva (score de grid + vizinhança).
2. Classificar cada curva em: NORMAL, DEPENDENTE, GRUPO ou ORFAO.
3. Julgar NORMAIS pelo método escolhido (score ponderado 70/30).
4. Posicionar GRUPOS ISOLADOS como bloco no ranking dos normais.
5. Inserir DEPENDENTES adjacentes ao seu âncora:
      dep.ordem_grid < anc.ordem_grid  →  ANTES do âncora
      dep.ordem_grid > anc.ordem_grid  →  DEPOIS do âncora
6. Re-numerar tudo (push-down) de 1 a N.
7. Atributos extras por perfil: categoria, group_id, ancora_id.

Lógica de vizinhança decifrada empiricamente (v3.0)
----------------------------------------------------
A posição relativa do dependente em relação ao âncora é determinada
comparando onde o dependente ESTARIA no grid (pri_pos ponderada) com
onde o âncora realmente está. Se o dep viria antes → vai ANTES; se
viria depois → vai DEPOIS. Isso garante coerência topológica.
"""

from itertools import groupby
from collections import defaultdict

# ──────────────────────────────────────────────────────────────────────────────
# Regras de sinal por eixo primário
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Constantes configuráveis
# ──────────────────────────────────────────────────────────────────────────────
VIZ_THRESHOLD = 60.0   # % mínima de cobertura para ser considerado NORMAL
PESO_GRID     = 0.70   # peso do score de grid no score combinado
PESO_VIZ      = 0.30   # peso do score de vizinhança no score combinado
EPSILON       = 0.5    # tolerância de empate no método arbitrário

# Categorias de saída
CAT_NORMAL     = 'NORMAL'
CAT_DEPENDENTE = 'DEPENDENTE'
CAT_GRUPO      = 'GRUPO'
CAT_ORFAO      = 'ORFAO'


# ──────────────────────────────────────────────────────────────────────────────
# Union-Find para detecção de componentes conexos (grupos isolados)
# ──────────────────────────────────────────────────────────────────────────────
class _UnionFind:
    def __init__(self, ids):
        self._parent = {i: i for i in ids}

    def find(self, x):
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self):
        out = defaultdict(set)
        for x in self._parent:
            out[self.find(x)].add(x)
        return list(out.values())


# ──────────────────────────────────────────────────────────────────────────────
# Classe principal
# ──────────────────────────────────────────────────────────────────────────────
class JuizOrdenamento:
    """
    Recebe lista de QgsFeature (curvas classificadas) e o nome do eixo primário.
    Devolve lista de (QgsFeature, ordem_espacial) com push-down já aplicado.
    """

    METODO_ARBITRARIO = 0
    METODO_BORDA      = 1
    METODO_GRAFO      = 2
    METODO_CONSENSO   = 3

    def __init__(self, eixo_primario: str, use_secondary: bool = True):
        assert eixo_primario in REGRAS, 'Eixo inválido: %s' % eixo_primario
        self.eixo          = eixo_primario
        self.perp          = PERPENDICULAR[eixo_primario]
        self.r_pri         = REGRAS[eixo_primario]['pri']
        self.r_sec         = REGRAS[self.perp]['pri']
        self.use_secondary = use_secondary

        # Preenchidos por analisar_vizinhanca()
        self._contagem_viz: dict = {}   # fid → {viz_fid: n_sensores}
        self._viz_perc:     dict = {}   # fid → % cobertura
        self._viz_dir:      dict = {}   # fid → 'Ambos'|'L'|...
        self._viz_n:        dict = {}   # fid → n vizinhos únicos

    # ══════════════════════════════════════════════════════════════════
    # LEITURA DE CAMPOS DO GRID
    # ══════════════════════════════════════════════════════════════════

    def _n_cols(self, feat, prefixo: str) -> int:
        i = 0
        while feat.fields().indexOf('%s%d' % (prefixo, i)) >= 0:
            i += 1
        return i

    def _pos_ponderada(self, feat, prefixo: str, n: int):
        """Posição contínua ponderada por 1/rank. Retorna (covered, pos|None)."""
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
        """Média dos ranks e total de hits nos sensores de grid."""
        ranks = []
        for prefix in (['lnPri', 'lnSec'] if self.use_secondary else ['lnPri']):
            n = self._n_cols(feat, prefix)
            for i in range(n):
                try:
                    v = feat['%s%d' % (prefix, i)]
                    r = int(v) if v not in (None, '', 'NULL') else 0
                    if r > 0:
                        ranks.append(r)
                except Exception:
                    continue
        if not ranks:
            return None, 0
        return sum(ranks) / len(ranks), len(ranks)

    # ══════════════════════════════════════════════════════════════════
    # ANÁLISE DE VIZINHANÇA
    # ══════════════════════════════════════════════════════════════════

    def analisar_vizinhanca(self, perfis: list, sensores_features: list):
        """
        Processa os sensores perpendiculares e popula os campos de vizinhança.

        perfis            : lista de dicts gerados por _perfil()
        sensores_features : lista de QgsFeature (parent_id, touch_id, side, vertex_id)
        """
        mapa: dict = defaultdict(list)
        for sf in sensores_features:
            mapa[int(sf['parent_id'])].append(sf)

        for p in perfis:
            fid           = p['feat'].id()
            meus_sensores = mapa.get(fid, [])

            if not meus_sensores:
                p.update({'viz_n': 0, 'viz_dir': 'Nenhum', 'viz_perc': 0.0})
                self._contagem_viz[fid] = {}
                self._viz_perc[fid]     = 0.0
                self._viz_dir[fid]      = 'Nenhum'
                self._viz_n[fid]        = 0
                continue

            hits = [s for s in meus_sensores if int(s['touch_id']) != -1]

            contagem: dict = defaultdict(int)
            for s in hits:
                contagem[int(s['touch_id'])] += 1
            self._contagem_viz[fid] = dict(contagem)

            viz_unicos = set(contagem.keys())
            sides      = set(s['side'] for s in hits)

            if not sides:
                viz_dir = 'Nenhum'
            elif len(sides) > 1:
                viz_dir = 'Ambos'
            else:
                viz_dir = list(sides)[0]

            total    = len(meus_sensores)
            viz_perc = (len(hits) / total) * 100.0 if total > 0 else 0.0

            p.update({'viz_n': len(viz_unicos), 'viz_dir': viz_dir, 'viz_perc': viz_perc})
            self._viz_perc[fid] = viz_perc
            self._viz_dir[fid]  = viz_dir
            self._viz_n[fid]    = len(viz_unicos)

    # ══════════════════════════════════════════════════════════════════
    # PERFIL BASE
    # ══════════════════════════════════════════════════════════════════

    def _perfil(self, feat) -> dict:
        n_pri = self._n_cols(feat, 'lnPri')
        n_sec = self._n_cols(feat, 'lnSec') if self.use_secondary else 0
        _, pri_pos = self._pos_ponderada(feat, 'lnPri', n_pri)
        _, sec_pos = (self._pos_ponderada(feat, 'lnSec', n_sec)
                      if self.use_secondary else ([], None))
        b_avg, b_hits = self._borda_score(feat)
        fid = feat.id()

        return {
            'feat':         feat,
            'pri_pos':      pri_pos,
            'sec_pos':      sec_pos,
            'borda_avg':    b_avg,
            'borda_hits':   b_hits,
            'grafo_score':  0,
            'consenso_avg': None,
            'orfao':        pri_pos is None and sec_pos is None,
            'ordem':        None,
            'viz_n':        self._viz_n.get(fid, 0),
            'viz_dir':      self._viz_dir.get(fid, 'Nenhum'),
            'viz_perc':     self._viz_perc.get(fid, 0.0),
            'categoria':    CAT_NORMAL,
            'ancora_id':    None,
            'group_id':     None,
        }

    # ══════════════════════════════════════════════════════════════════
    # SCORE COMBINADO 70 / 30
    # ══════════════════════════════════════════════════════════════════

    def _score_grid(self, p: dict) -> float:
        avg  = p['borda_avg']
        hits = p['borda_hits']
        if avg is None:
            return 1.0
        base      = avg / max(avg, 1.0)
        confianca = 1.0 - (1.0 / (hits + 1))
        return base * (2.0 - confianca) / 2.0

    def _score_viz(self, p: dict) -> float:
        return 1.0 - (p['viz_perc'] / 100.0)

    def _score_combinado(self, p: dict) -> float:
        return PESO_GRID * self._score_grid(p) + PESO_VIZ * self._score_viz(p)

    # ══════════════════════════════════════════════════════════════════
    # CHAVE ESPACIAL
    # ══════════════════════════════════════════════════════════════════

    def _chave(self, p: dict):
        k1 = self.r_pri(p['pri_pos'], 0) if p['pri_pos'] is not None else None
        k2 = self.r_sec(p['sec_pos'], 0) if p['sec_pos'] is not None else None
        return k1, k2

    # ══════════════════════════════════════════════════════════════════
    # SCORES ESPECIAIS
    # ══════════════════════════════════════════════════════════════════

    def _calc_grafo_scores(self, perfis: list) -> list:
        n      = len(perfis)
        matriz = [[0] * n for _ in range(n)]
        sensores: dict = defaultdict(list)

        for idx, p in enumerate(perfis):
            feat = p['feat']
            for prefix in (['lnPri', 'lnSec'] if self.use_secondary else ['lnPri']):
                for i in range(self._n_cols(feat, prefix)):
                    col = '%s%d' % (prefix, i)
                    try:
                        r = int(feat[col]) if feat[col] not in (None, '', 'NULL') else 0
                        if r > 0:
                            sensores[col].append((r, idx))
                    except Exception:
                        continue

        for col, hits in sensores.items():
            hits.sort()
            for i in range(len(hits)):
                for j in range(i + 1, len(hits)):
                    matriz[hits[i][1]][hits[j][1]] += 1

        scores = [0] * n
        for i in range(n):
            for j in range(i + 1, n):
                if matriz[i][j] > matriz[j][i]:
                    scores[i] += 1; scores[j] -= 1
                elif matriz[j][i] > matriz[i][j]:
                    scores[j] += 1; scores[i] -= 1
        return scores

    def _calc_consenso_scores(self, perfis: list) -> list:
        sensores: dict = defaultdict(list)
        for idx, p in enumerate(perfis):
            feat = p['feat']
            for prefix in (['lnPri', 'lnSec'] if self.use_secondary else ['lnPri']):
                for i in range(self._n_cols(feat, prefix)):
                    col = '%s%d' % (prefix, i)
                    try:
                        v = feat[col]
                        r = int(v) if v not in (None, '', 'NULL') else 0
                        if r > 0:
                            sensores[col].append((r, idx))
                    except Exception:
                        continue

        n_p  = len(perfis)
        soma = [0.0] * n_p
        hits = [0] * n_p
        for col, hs in sensores.items():
            if not hs: continue
            hs.sort()
            n_h = len(hs)
            for rank, idx in hs:
                soma[idx] += (rank - 1) / (n_h - 1) if n_h > 1 else 0.0
                hits[idx] += 1
        return [(soma[i] / hits[i]) if hits[i] > 0 else None for i in range(n_p)]

    # ══════════════════════════════════════════════════════════════════
    # ÂNCORA
    # ══════════════════════════════════════════════════════════════════

    def _achar_ancora(self, fid: int) -> int:
        """Vizinho com mais aparições nos sensores. Empate: menor fid."""
        contagem = self._contagem_viz.get(fid, {})
        if not contagem:
            return -1
        max_c = max(contagem.values())
        return sorted(v for v, c in contagem.items() if c == max_c)[0]

    # ══════════════════════════════════════════════════════════════════
    # CLASSIFICAÇÃO
    # ══════════════════════════════════════════════════════════════════

    def _classificar(self, perfis: list):
        """
        Separa perfis em normais, dependentes, grupos e órfãos.
        Preenche 'categoria', 'ancora_id' e 'group_id' em cada perfil.
        Retorna (normais, dependentes, grupos, orfaos).
          grupos : list[ (group_id:int, fids:set) ]
        """
        todos_fids = {p['feat'].id() for p in perfis}
        perf_map   = {p['feat'].id(): p for p in perfis}

        # Órfãos: sem grid E sem qualquer vizinhança perpendicular
        orfaos_fids = {
            p['feat'].id() for p in perfis
            if p['orfao'] and self._viz_perc.get(p['feat'].id(), 0.0) == 0.0
        }
        candidatos = todos_fids - orfaos_fids

        # Grafo de vizinhança somente entre candidatos
        adj: dict = {fid: set() for fid in candidatos}
        for fid in candidatos:
            for viz in self._contagem_viz.get(fid, {}):
                if viz in adj:
                    adj[fid].add(viz)
                    adj[viz].add(fid)

        # Componentes conexos
        uf = _UnionFind(adj.keys()) if adj else _UnionFind([])
        for fid, vizinhos in adj.items():
            for v in vizinhos:
                uf.union(fid, v)
        componentes = uf.groups() if adj else []

        normais:     list = []
        dependentes: list = []
        grupos:      list = []
        orfaos:      list = [perf_map[f] for f in orfaos_fids if f in perf_map]
        grupo_id          = 0

        for comp in componentes:
            # Tem vizinhança externa?
            tem_externo = any(
                viz not in comp and viz not in orfaos_fids
                for fid in comp
                for viz in self._contagem_viz.get(fid, {})
            )

            if not tem_externo and len(comp) > 1:
                # Grupo isolado
                grupo_id += 1
                grupos.append((grupo_id, comp))
                for fid in comp:
                    if fid in perf_map:
                        perf_map[fid]['group_id'] = grupo_id
                        perf_map[fid]['categoria'] = CAT_GRUPO
                continue

            # Classificação individual dentro do componente
            for fid in comp:
                if fid not in perf_map:
                    continue
                p = perf_map[fid]
                if self._viz_perc.get(fid, 0.0) < VIZ_THRESHOLD:
                    p['ancora_id'] = self._achar_ancora(fid)
                    p['categoria'] = CAT_DEPENDENTE
                    dependentes.append(p)
                else:
                    p['categoria'] = CAT_NORMAL
                    normais.append(p)

        # Candidatos fora de qualquer componente (sem vizinhos entre si)
        em_comp = {fid for comp in componentes for fid in comp}
        for fid in candidatos - em_comp:
            if fid not in perf_map:
                continue
            p = perf_map[fid]
            if self._viz_perc.get(fid, 0.0) < VIZ_THRESHOLD:
                p['ancora_id'] = self._achar_ancora(fid)
                p['categoria'] = CAT_DEPENDENTE
                dependentes.append(p)
            else:
                p['categoria'] = CAT_NORMAL
                normais.append(p)

        return normais, dependentes, grupos, orfaos

    # ══════════════════════════════════════════════════════════════════
    # ORDENAMENTO INTERNO
    # ══════════════════════════════════════════════════════════════════

    def _ordenar_perfis(self, perfis: list, metodo: int) -> list:
        """Ordena lista de perfis e retorna com 'ordem' 1-based (sem inserções)."""
        normais = [p for p in perfis if not p['orfao']]
        orfaos  = [p for p in perfis if p['orfao']]

        if metodo == self.METODO_GRAFO and normais:
            gs = self._calc_grafo_scores(normais)
            for i, p in enumerate(normais):
                p['grafo_score'] = gs[i]

        if metodo == self.METODO_CONSENSO and normais:
            cs = self._calc_consenso_scores(normais)
            for i, p in enumerate(normais):
                p['consenso_avg'] = cs[i]

        def sort_key(p):
            sc   = self._score_combinado(p)
            k1, k2 = self._chave(p)

            if metodo == self.METODO_CONSENSO:
                avg = p['consenso_avg'] if p['consenso_avg'] is not None else 999999.0
                return (avg, -p['borda_hits'], sc)

            if metodo == self.METODO_GRAFO:
                return (-p['grafo_score'],
                        p['borda_avg'] if p['borda_avg'] is not None else 999999.0,
                        -p['borda_hits'], sc)

            if metodo == self.METODO_BORDA:
                avg = p['borda_avg'] if p['borda_avg'] is not None else 999999.0
                return (avg, -p['borda_hits'], sc,
                        0 if k1 is not None else 1,
                        k1 if k1 is not None else 0.0)

            # ARBITRÁRIO
            return (0 if k1 is not None else 1,
                    k1 if k1 is not None else 0.0,
                    0 if k2 is not None else 1,
                    k2 if k2 is not None else 0.0, sc)

        normais.sort(key=sort_key)

        contador, chave_ant = 1, None
        for p in normais:
            c = sort_key(p)
            if chave_ant is not None:
                if metodo == self.METODO_ARBITRARIO:
                    k1_a, k1 = chave_ant[1], c[1]
                    k2_a, k2 = chave_ant[3], c[3]
                    muda = (
                        ((k1 is None) != (k1_a is None)) or
                        (k1 is not None and abs(k1 - k1_a) >= EPSILON) or
                        ((k2 is None) != (k2_a is None)) or
                        (k2 is not None and abs(k2 - k2_a) >= EPSILON)
                    )
                    if muda:
                        contador += 1
                else:
                    if c != chave_ant:
                        contador += 1
            p['ordem'] = contador
            chave_ant  = c

        resultado = []
        for _, grp in groupby(normais, key=lambda p: p['ordem']):
            membros = list(grp)
            if len(membros) > 1:
                membros.sort(key=lambda p: (
                    0 if p['sec_pos'] is not None else 1,
                    self.r_sec(p['sec_pos'], 0) if p['sec_pos'] is not None else 0.0,
                ))
            for m in membros:
                m['ordem'] = len(resultado) + 1
                resultado.append(m)

        for i, p in enumerate(orfaos):
            p['ordem'] = len(resultado) + i + 1
            resultado.append(p)

        return resultado

    # ══════════════════════════════════════════════════════════════════
    # POSIÇÃO ESTIMADA NO GRID (para decidir lado de inserção)
    # ══════════════════════════════════════════════════════════════════

    def _grid_pos_estimada(self, p: dict, ranking: list) -> float:
        """
        Estima onde este perfil ficaria no ranking dos normais.
        Usa sua pri_pos para interpolar entre os normais ordenados.
        Retorna valor contínuo [0 .. len(ranking)+1].
        """
        if not ranking:
            return 0.0

        # Coleta (pri_pos, ordem) dos normais que têm pri_pos
        refs = [(rp['pri_pos'], rp['ordem'])
                for rp in ranking
                if rp['pri_pos'] is not None]
        if not refs:
            return 0.0

        pri = p.get('pri_pos')
        if pri is None:
            # Sem pos primária: usa score combinado para interpolar
            sc  = self._score_combinado(p)
            scs = [(self._score_combinado(rp), rp['ordem']) for rp in ranking]
            scs.sort()
            for sc_r, ord_r in scs:
                if sc <= sc_r:
                    return ord_r - 0.5
            return scs[-1][1] + 0.5

        # Interpola pela pri_pos
        refs.sort()
        if pri <= refs[0][0]:
            return refs[0][1] - 0.5
        if pri >= refs[-1][0]:
            return refs[-1][1] + 0.5
        for i in range(len(refs) - 1):
            p0, o0 = refs[i]
            p1, o1 = refs[i + 1]
            if p0 <= pri <= p1:
                t = (pri - p0) / (p1 - p0) if p1 != p0 else 0.5
                return o0 + t * (o1 - o0)
        return refs[-1][1] + 0.5

    # ══════════════════════════════════════════════════════════════════
    # INSERÇÃO DE GRUPO COMO BLOCO
    # ══════════════════════════════════════════════════════════════════

    def _inserir_grupo(self, ranking: list, grupo_fids: set,
                       perf_map: dict, metodo: int) -> list:
        """Ordena o grupo internamente e insere como bloco adjacente ao vizinho externo."""
        perfis_grupo = [perf_map[f] for f in grupo_fids if f in perf_map]
        if not perfis_grupo:
            return ranking

        perfis_grupo = self._ordenar_perfis(perfis_grupo, metodo)

        # Âncora externa: vizinho fora do grupo com maior contagem, presente no ranking
        melhor_fid, melhor_cnt = -1, -1
        for fid in grupo_fids:
            for viz_fid, cnt in self._contagem_viz.get(fid, {}).items():
                if viz_fid not in grupo_fids:
                    if any(rp['feat'].id() == viz_fid for rp in ranking):
                        if cnt > melhor_cnt:
                            melhor_cnt, melhor_fid = cnt, viz_fid

        if melhor_fid == -1:
            ranking.extend(perfis_grupo)
            return ranking

        pos_ancora = next(
            (i for i, rp in enumerate(ranking) if rp['feat'].id() == melhor_fid), None
        )
        if pos_ancora is None:
            ranking.extend(perfis_grupo)
            return ranking

        # Posição estimada do grupo vs âncora
        grid_grupo  = sum(self._grid_pos_estimada(p, ranking) for p in perfis_grupo) / len(perfis_grupo)
        grid_ancora = next(rp['ordem'] for rp in ranking if rp['feat'].id() == melhor_fid)

        if grid_grupo <= grid_ancora:
            for i, p in enumerate(perfis_grupo):
                ranking.insert(pos_ancora + i, p)
        else:
            for i, p in enumerate(perfis_grupo):
                ranking.insert(pos_ancora + 1 + i, p)

        return ranking

    # ══════════════════════════════════════════════════════════════════
    # INSERÇÃO DE DEPENDENTE
    # ══════════════════════════════════════════════════════════════════

    def _inserir_dependente(self, ranking: list, dep: dict) -> list:
        """
        Insere o dependente adjacente ao seu âncora.

        Regra de lado (decifrada empiricamente):
          grid_estimado(dep) < ordem(ancora)  →  ANTES
          grid_estimado(dep) > ordem(ancora)  →  DEPOIS
          empate                              →  ANTES
        """
        ancora_fid = dep['ancora_id']

        pos_ancora = next(
            (i for i, rp in enumerate(ranking) if rp['feat'].id() == ancora_fid), None
        )

        if pos_ancora is None:
            # Âncora não está no ranking ainda: posiciona pela estimativa de grid
            grid_est = self._grid_pos_estimada(dep, ranking)
            pos_ins  = len(ranking)
            for i, rp in enumerate(ranking):
                if rp['ordem'] > grid_est:
                    pos_ins = i
                    break
            ranking.insert(pos_ins, dep)
            return ranking

        ancora_perf  = ranking[pos_ancora]
        grid_ainda   = ancora_perf['ordem']          # posição atual do âncora
        grid_dep_est = self._grid_pos_estimada(dep, ranking)

        if grid_dep_est > grid_ainda:
            # DEPOIS do âncora
            ranking.insert(pos_ancora + 1, dep)
        else:
            # ANTES do âncora
            ranking.insert(pos_ancora, dep)

        return ranking

    # ══════════════════════════════════════════════════════════════════
    # RE-NUMERAÇÃO
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _renumerar(ranking: list) -> list:
        for i, p in enumerate(ranking):
            p['ordem'] = i + 1
        return ranking

    # ══════════════════════════════════════════════════════════════════
    # ENTRADA PÚBLICA: julgar()
    # ══════════════════════════════════════════════════════════════════

    def julgar(self, features: list, metodo: int = METODO_BORDA):
        """
        Parâmetros
        ----------
        features : list[QgsFeature]
        metodo   : int — METODO_ARBITRARIO | METODO_BORDA | METODO_GRAFO | METODO_CONSENSO

        Retorna
        -------
        list[ (QgsFeature, ordem_espacial) ]

        Cada perfil interno terá:
          p['categoria']  → 'NORMAL' | 'DEPENDENTE' | 'GRUPO' | 'ORFAO'
          p['ancora_id']  → fid do âncora (somente DEPENDENTE)
          p['group_id']   → id do grupo   (somente GRUPO)
          p['viz_n']      → n° de vizinhos únicos
          p['viz_dir']    → 'Ambos' | 'L' | 'O' | ... | 'Nenhum'
          p['viz_perc']   → % de cobertura de vizinhança
        """
        # 1. Monta perfis
        perfis   = [self._perfil(f) for f in features]
        perf_map = {p['feat'].id(): p for p in perfis}

        # Sincroniza valores de vizinhança do cache
        for p in perfis:
            fid = p['feat'].id()
            p['viz_perc'] = self._viz_perc.get(fid, p['viz_perc'])
            p['viz_dir']  = self._viz_dir.get(fid, p['viz_dir'])
            p['viz_n']    = self._viz_n.get(fid, p['viz_n'])

        # 2. Classifica
        normais, dependentes, grupos, orfaos = self._classificar(perfis)

        # 3. Ordena normais
        ranking = self._ordenar_perfis(normais, metodo)

        # 4. Insere grupos como bloco
        for _gid, grupo_fids in grupos:
            ranking = self._inserir_grupo(ranking, grupo_fids, perf_map, metodo)
        self._renumerar(ranking)

        # 5. Insere dependentes um a um.
        #    Ordem de inserção: pelo grid estimado (do mais "interior" ao mais "exterior")
        #    para garantir que âncoras de deps sejam inseridas primeiro.
        dependentes_ord = sorted(
            dependentes,
            key=lambda p: self._grid_pos_estimada(p, ranking)
        )

        for dep in dependentes_ord:
            ranking = self._inserir_dependente(ranking, dep)
            # Re-numera após cada inserção para manter 'ordem' consistente
            self._renumerar(ranking)

        # 6. Órfãos ao final
        for p in orfaos:
            p['categoria'] = CAT_ORFAO
            p['ordem']     = len(ranking) + 1
            ranking.append(p)

        # 7. Re-numeração final
        self._renumerar(ranking)

        return [(p['feat'], p['ordem']) for p in ranking]