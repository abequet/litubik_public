# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thematic clustering of a corpus (roadmap chantier 11), pure computation.

TF-IDF on title + abstract + keywords (1–2-grams, English + French stop
words) → TruncatedSVD (≤ 100 dims) → 2-D layout by t-SNE (≤ TSNE_MAX_DOCS
documents; beyond, the first axes of the SVD) → k-means **on the layout
itself**, k chosen by silhouette over 2–12 unless requested. Salient terms
per cluster = highest mean TF-IDF weights.

Clustering in the plane rather than in the 100-D space is deliberate: on
a real corpus (900 heterogeneous references) k-means in 100 dimensions has
a silhouette near 0.05 and its clusters interleave on the t-SNE map (only
57 % of a dot's ten nearest neighbours share its colour), so the map reads
as confetti. Clustering the map gives contiguous regions (92 %) with an
equal or better TF-IDF coherence (mean intra-cluster cosine minus
inter-cluster), and a silhouette that actually discriminates k.

scikit-learn is imported lazily so the rest of the app (and the test suite)
never pays for it until a map is actually computed.
"""
import re

MAX_SVD_DIMS = 100
TSNE_MAX_DOCS = 10000   # ~13 s for 5000 documents, Barnes-Hut
FALLBACK_DIMS = 10      # beyond: cluster in the first SVD axes, plot the first two
K_RANGE = (2, 12)
TERMS_PER_CLUSTER = 8
MIN_DOCS = 6
# the layout is rescaled on its 1st–99th percentiles (then clipped) so that a
# handful of stray dots cannot squash the rest of the map into the centre
CLIP_PERCENTILES = (1.0, 99.0)

# a compact French list — sklearn only ships English
FRENCH_STOP_WORDS = """
a à afin ai ainsi alors après au aucun aucune aujourd hui auprès auquel
aura auront aussi autre autres aux avaient avait avant avec avoir ayant bien car
ce ceci cela celle celles celui cependant certain certaine certaines certains ces
cet cette ceux chacun chaque chez ci comme comment concernant d dans de depuis
des deux devant devrait différent différentes différents doit donc dont du elle
elles en encore entre envers est et étaient était étant été être eu eux faire
fait faites font grâce il ils j je jusqu jusque l la laquelle le lequel les
lesquelles lesquels leur leurs lors lorsque lui m ma mais me même mêmes mes moi
moins mon n ne ni nos notre nous nouveau nouveaux nouvelle nouvelles on ont ou où
par parce parmi pas pendant peu peut peuvent plus plusieurs pour pourquoi
pourrait pu puis puisque qu quand que quel quelle quelles quels qui quoi s sa sans
se selon sera seront ses si sien sienne soi soit son sont sous sur t ta te tel
telle telles tels tes toi ton toujours tous tout toute toutes très trop tu un une
vers via voici voilà vos votre vous y étude études résultats méthode méthodes
objectif objectifs conclusion conclusions contexte
""".split()

# boilerplate of structured abstracts, in both languages
EXTRA_STOP_WORDS = """
abstract background objective objectives aim aims purpose method methods
methodology results result conclusion conclusions findings study studies
paper article research approach using based use used data analysis
significant significantly however also may might well new within
jats
""".split()

_KW_LINE = re.compile(r"^KW\s+-\s*(.+)$", re.MULTILINE)


def record_keywords(raw_ris: str) -> list[str]:
    """KW lines of the archived RIS, when the source carried keywords."""
    return [m.group(1).strip() for m in _KW_LINE.finditer(raw_ris or "")]


def document_text(title: str, abstract: str, keywords: list[str]) -> str:
    # the title is repeated: it is short and carries the most signal
    return " ".join([title or "", title or "", abstract or "",
                     " ".join(keywords or [])]).strip()


def _choose_k(matrix, k_requested: int | None, n_docs: int):
    """k-means with the requested k, or the k in K_RANGE with the best
    silhouette (bounded by n_docs // 3 so tiny corpora stay readable).
    Clusters are renumbered by decreasing size. Returns (labels, k,
    silhouette)."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    def fit(k):
        model = KMeans(n_clusters=k, n_init=10, random_state=0)
        labels = model.fit_predict(matrix)
        score = (silhouette_score(matrix, labels)
                 if 1 < k < n_docs else None)
        return labels, score

    upper = max(2, min(K_RANGE[1], n_docs // 3))
    if k_requested:
        k = max(2, min(int(k_requested), max(2, n_docs - 1)))
        labels, score = fit(k)
    else:
        best = None
        for k in range(min(K_RANGE[0], upper), upper + 1):
            labels, score = fit(k)
            if best is None or (score is not None and score > best[2]):
                best = (labels, k, score)
        labels, k, score = best
    order = np.argsort(-np.bincount(labels, minlength=k), kind="stable")
    rank = np.empty(k, dtype=int)
    rank[order] = np.arange(k)
    return rank[labels], k, score


def compute_topics(docs: list[dict], k_requested: int | None = None) -> dict:
    """docs: [{"id", "title", "abstract", "keywords": [...]}, ...].
    Returns {"points": [{"id", "x", "y", "cluster"}], "clusters": [{"id",
    "size", "terms"}], "k", "silhouette", "projection", "n_docs"}."""
    import numpy as np
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    from sklearn.preprocessing import normalize

    n = len(docs)
    if n < MIN_DOCS:
        raise ValueError(f"At least {MIN_DOCS} documents are needed to map themes "
                         f"({n} in this scope)")
    texts = [document_text(d.get("title", ""), d.get("abstract", ""),
                           d.get("keywords") or []) for d in docs]
    stop = list(ENGLISH_STOP_WORDS) + FRENCH_STOP_WORDS + EXTRA_STOP_WORDS
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words=stop,
                                 min_df=2 if n >= 20 else 1, max_df=0.9,
                                 sublinear_tf=True, max_features=50000,
                                 token_pattern=r"(?u)\b[^\W\d_][^\W_]{2,}\b")
    tfidf = vectorizer.fit_transform(texts)
    vocab = np.array(vectorizer.get_feature_names_out())
    if tfidf.shape[1] < 2:
        raise ValueError("The documents hold too little text to map themes "
                         "(titles and abstracts are needed)")

    dims = max(2, min(MAX_SVD_DIMS, tfidf.shape[1] - 1, n - 1))
    svd = TruncatedSVD(n_components=dims, random_state=0)
    reduced = normalize(svd.fit_transform(tfidf))

    if n <= TSNE_MAX_DOCS:
        from sklearn.manifold import TSNE
        perplexity = max(2.0, min(30.0, (n - 1) / 3.0))
        coords = TSNE(n_components=2, perplexity=perplexity, init="pca",
                      learning_rate="auto", random_state=0).fit_transform(reduced)
        space = coords
        projection = "tsne"
    else:
        space = normalize(reduced[:, :min(FALLBACK_DIMS, dims)])
        coords = space[:, :2]
        projection = "svd"
    # clusters are regions of the map the user sees (see the module docstring)
    labels, k, silhouette = _choose_k(space, k_requested, n)

    # robust rescale to [-1, 1]: centre and span from the 1st–99th
    # percentiles, the rare outliers clipped to the border
    lo, hi = np.percentile(coords, CLIP_PERCENTILES, axis=0)
    centre, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    half[half <= 0] = 1.0
    coords = np.clip((coords - centre) / half, -1.0, 1.0)

    clusters = []
    for cid in range(k):
        members = np.where(labels == cid)[0]
        if len(members) == 0:
            clusters.append({"id": cid, "size": 0, "terms": []})
            continue
        centroid = np.asarray(tfidf[members].mean(axis=0)).ravel()
        top = centroid.argsort()[::-1]
        terms, seen = [], set()
        for idx in top:
            if centroid[idx] <= 0:
                break
            term = str(vocab[idx])
            # skip a bigram whose words are both already listed, and vice versa
            words = set(term.split())
            if words <= seen:
                continue
            terms.append(term)
            seen |= words
            if len(terms) >= TERMS_PER_CLUSTER:
                break
        clusters.append({"id": cid, "size": int(len(members)), "terms": terms})

    points = [{"id": d["id"], "x": round(float(coords[i, 0]), 4),
               "y": round(float(coords[i, 1]), 4), "cluster": int(labels[i])}
              for i, d in enumerate(docs)]
    return {"points": points, "clusters": clusters, "k": int(k),
            "silhouette": (round(float(silhouette), 4) if silhouette is not None
                           else None),
            "projection": projection, "n_docs": n}
