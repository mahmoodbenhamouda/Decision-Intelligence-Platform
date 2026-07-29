"""
ml_engine/nlp/tender_matcher.py
===============================
Matching SÉMANTIQUE (NLP) entre les appels d'offres captés par la veille et la
base clients / le domaine métier d'Overlyne.

Pourquoi : le matching par simple chevauchement de tokens rate les formulations
différentes ("CHU Sfax" vs "Centre Hospitalier Universitaire de Sfax",
"réactifs d'immuno-analyse" vs "kits ELISA"). Un modèle sémantique rapproche les
sens, pas seulement les mots.

Conception robuste (comme le reste de la plateforme) :
  - Backend principal : embeddings de phrases (sentence-transformers, multilingue)
    → similarité cosinus dans un espace vectoriel dense (deep learning).
  - Repli automatique : TF-IDF caractères (n-grammes 3–5) + cosinus (scikit-learn),
    tolérant aux variantes orthographiques. → fonctionne SANS dépendance lourde.

API :
    TenderMatcher(candidates).match(text) -> (index, score)
    domain_relevance(text) -> score ∈ [0,1]  (proximité au domaine diagnostic)
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

try:  # embeddings denses (optionnel)
    from sentence_transformers import SentenceTransformer  # type: ignore
    _ST = True
except Exception:  # pragma: no cover
    _ST = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _SK = True
except Exception:  # pragma: no cover
    _SK = False

# Vocabulaire de référence du domaine (diagnostic / biologie médicale)
_DOMAIN_REFERENCE = (
    "réactifs de laboratoire diagnostic in vitro biologie médicale immunologie "
    "sérologie hématologie biochimie microbiologie PCR ELISA automate analyseur "
    "dispositif médical consommable hospitalier CHU analyses médicales"
)

_MODEL_SINGLETON = None


def _get_st_model():
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        _MODEL_SINGLETON = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _MODEL_SINGLETON


class TenderMatcher:
    """Indexe une liste de candidats (noms de clients, familles produit) et
    renvoie le meilleur appariement sémantique pour un texte d'appel d'offres."""

    def __init__(self, candidates: List[str]):
        self.candidates = [c for c in candidates if c and str(c).strip()]
        self.backend = "none"
        self._matrix = None
        self._vectorizer = None
        if not self.candidates:
            return
        if _ST:
            try:
                self._model = _get_st_model()
                self._matrix = self._model.encode(self.candidates, normalize_embeddings=True)
                self.backend = "sentence-transformers"
                return
            except Exception:
                pass
        if _SK:
            self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
            self._matrix = self._vectorizer.fit_transform(self.candidates)
            self.backend = "tfidf-char"

    def _vec(self, text: str):
        if self.backend == "sentence-transformers":
            return self._model.encode([text], normalize_embeddings=True)
        return self._vectorizer.transform([text])

    def match(self, text: str) -> Tuple[int, float]:
        """Retourne (index du meilleur candidat, score cosinus ∈ [0,1])."""
        if self._matrix is None or not text:
            return -1, 0.0
        v = self._vec(text)
        if self.backend == "sentence-transformers":
            sims = (self._matrix @ v[0])
        else:
            sims = cosine_similarity(v, self._matrix)[0]
        j = int(np.argmax(sims))
        return j, float(sims[j])


_DOMAIN_MATCHER: Optional[TenderMatcher] = None


def domain_relevance(text: str) -> float:
    """Proximité sémantique d'un titre au domaine du diagnostic médical ∈ [0,1]."""
    global _DOMAIN_MATCHER
    if _DOMAIN_MATCHER is None:
        _DOMAIN_MATCHER = TenderMatcher([_DOMAIN_REFERENCE])
    _, score = _DOMAIN_MATCHER.match(text or "")
    return score


def match_candidates(text: str, candidates: List[str], threshold: float = 0.0
                     ) -> Tuple[Optional[str], float]:
    """Meilleur candidat sémantique pour `text`, ou (None, score) si sous le seuil."""
    m = TenderMatcher(candidates)
    j, s = m.match(text or "")
    if j < 0 or s < threshold:
        return None, s
    return candidates[j], s


def backend_name() -> str:
    return "sentence-transformers" if _ST else ("tfidf-char" if _SK else "aucun")
