"""
rag/rag_engine.py — Moteur RAG (Retrieval-Augmented Generation) pour FinBot.

Rôle : permettre au copilote de répondre à des questions "externes" (secteur du
diagnostic médical, marchés publics/TUNEPS, réglementation, notions générales…)
qui ne se trouvent PAS dans les données ERP internes, en s'appuyant sur une base
documentaire (PDF / TXT / MD) placée dans rag/documents/.

Pipeline :
  1. Ingestion des documents (rag/documents/)
  2. Découpage en chunks (~500 caractères, chevauchement 50)
  3. Embeddings SÉMANTIQUES (sentence-transformers multilingue) + index FAISS
     → repli automatique TF-IDF (scikit-learn) si les libs sémantiques ou le
       modèle ne sont pas disponibles : le RAG fonctionne toujours, même hors ligne.
  4. Persistance de l'index dans rag/index/
  5. Recherche des passages les plus pertinents pour une question.

Usage CLI :
    python -m rag.rag_engine build            # (ré)indexer rag/documents/
    python -m rag.rag_engine query "question"  # tester une recherche
"""

from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parent
DOCS_DIR = BASE / "documents"
INDEX_DIR = BASE / "index"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 4
SCORE_THRESHOLD = 0.15          # similarité minimale pour retenir un passage
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Lecture des documents
# ─────────────────────────────────────────────────────────────────────────────
def _read_pdf(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def load_documents(docs_dir: Path = DOCS_DIR) -> List[Dict[str, str]]:
    """Retourne [{source, text}] pour chaque fichier lisible de rag/documents/."""
    docs: List[Dict[str, str]] = []
    if not docs_dir.exists():
        return docs
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext == ".pdf":
            text = _read_pdf(path)
        elif ext in (".txt", ".md", ".markdown", ".csv"):
            text = _read_text(path)
        else:
            continue
        text = (text or "").strip()
        if len(text) > 30:
            docs.append({"source": path.name, "text": text})
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# 2. Découpage en chunks
# ─────────────────────────────────────────────────────────────────────────────
def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    # Normalisation légère des espaces
    text = re.sub(r"[ \t]+", " ", text)
    # On coupe d'abord par paragraphes pour garder du sens
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buff = ""
    for p in paragraphs:
        if len(buff) + len(p) + 1 <= size:
            buff = f"{buff}\n{p}".strip()
        else:
            if buff:
                chunks.append(buff)
            # Paragraphe trop long → découpage glissant
            if len(p) > size:
                start = 0
                while start < len(p):
                    chunks.append(p[start:start + size])
                    start += size - overlap
                buff = ""
            else:
                buff = p
    if buff:
        chunks.append(buff)
    return [c for c in chunks if len(c.strip()) > 20]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Backends d'embeddings (sémantique prioritaire, repli TF-IDF)
# ─────────────────────────────────────────────────────────────────────────────
class _SemanticBackend:
    """Embeddings sentence-transformers + index FAISS (cosine via produit scalaire)."""
    kind = "semantic"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # noqa
        self._model = SentenceTransformer(EMBED_MODEL)
        self._index = None

    def _embed(self, texts: List[str]):
        import numpy as np
        vecs = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype="float32")

    def build(self, chunks: List[str]) -> None:
        import faiss
        emb = self._embed(chunks)
        self._index = faiss.IndexFlatIP(emb.shape[1])
        self._index.add(emb)

    def save(self, index_dir: Path) -> None:
        import faiss
        faiss.write_index(self._index, str(index_dir / "faiss.index"))

    def load(self, index_dir: Path) -> None:
        import faiss
        self._index = faiss.read_index(str(index_dir / "faiss.index"))

    def search(self, query: str, k: int):
        scores, idx = self._index.search(self._embed([query]), k)
        return list(zip(idx[0].tolist(), scores[0].tolist()))


class _TfidfBackend:
    """Repli 100% offline : TF-IDF (scikit-learn) + similarité cosinus."""
    kind = "tfidf"

    def __init__(self) -> None:
        self._vec = None
        self._matrix = None

    def build(self, chunks: List[str]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self._matrix = self._vec.fit_transform(chunks)

    def save(self, index_dir: Path) -> None:
        with open(index_dir / "tfidf.pkl", "wb") as f:
            pickle.dump({"vec": self._vec, "matrix": self._matrix}, f)

    def load(self, index_dir: Path) -> None:
        with open(index_dir / "tfidf.pkl", "rb") as f:
            d = pickle.load(f)
        self._vec, self._matrix = d["vec"], d["matrix"]

    def search(self, query: str, k: int):
        from sklearn.metrics.pairwise import linear_kernel
        qv = self._vec.transform([query])
        sims = linear_kernel(qv, self._matrix).ravel()
        top = sims.argsort()[::-1][:k]
        return [(int(i), float(sims[i])) for i in top]


def _make_backend(prefer_semantic: bool = True):
    """Instancie le backend sémantique si possible, sinon TF-IDF."""
    if prefer_semantic:
        try:
            return _SemanticBackend()
        except Exception:
            pass
    return _TfidfBackend()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Index RAG (build / load / search) avec persistance
# ─────────────────────────────────────────────────────────────────────────────
class RagIndex:
    def __init__(self) -> None:
        self.backend = None
        self.chunks: List[Dict[str, str]] = []   # [{source, text}]

    # -- construction --
    def build(self, docs_dir: Path = DOCS_DIR) -> int:
        docs = load_documents(docs_dir)
        self.chunks = []
        for d in docs:
            for ch in chunk_text(d["text"]):
                self.chunks.append({"source": d["source"], "text": ch})
        if not self.chunks:
            return 0
        self.backend = _make_backend(prefer_semantic=True)
        self.backend.build([c["text"] for c in self.chunks])
        self._save()
        return len(self.chunks)

    def _save(self) -> None:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        with open(INDEX_DIR / "chunks.pkl", "wb") as f:
            pickle.dump(self.chunks, f)
        self.backend.save(INDEX_DIR)
        (INDEX_DIR / "manifest.json").write_text(
            json.dumps({"backend": self.backend.kind, "n_chunks": len(self.chunks),
                        "model": EMBED_MODEL}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -- chargement --
    def load(self) -> bool:
        manifest = INDEX_DIR / "manifest.json"
        chunks_f = INDEX_DIR / "chunks.pkl"
        if not manifest.exists() or not chunks_f.exists():
            return False
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
            with open(chunks_f, "rb") as f:
                self.chunks = pickle.load(f)
            if info.get("backend") == "semantic":
                self.backend = _SemanticBackend()
            else:
                self.backend = _TfidfBackend()
            self.backend.load(INDEX_DIR)
            return True
        except Exception:
            return False

    # -- recherche --
    def search(self, query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
        if not self.chunks or self.backend is None:
            return []
        results = []
        for idx, score in self.backend.search(query, k):
            if 0 <= idx < len(self.chunks) and score >= SCORE_THRESHOLD:
                c = self.chunks[idx]
                results.append({"source": c["source"], "text": c["text"], "score": round(float(score), 3)})
        return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. Singleton + fonctions pratiques (import léger côté agent)
# ─────────────────────────────────────────────────────────────────────────────
_INDEX: Optional[RagIndex] = None


def _get_index() -> RagIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = RagIndex()
        _INDEX.load()   # silencieux si pas d'index
    return _INDEX


def build_index(docs_dir: Path = DOCS_DIR) -> int:
    """(Ré)indexe les documents et renvoie le nombre de passages indexés."""
    global _INDEX
    _INDEX = RagIndex()
    n = _INDEX.build(docs_dir)
    return n


def search(query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
    """Renvoie les passages les plus pertinents (peut être vide)."""
    try:
        return _get_index().search(query, k)
    except Exception:
        return []


def is_available() -> bool:
    """Vrai s'il existe un index consultable."""
    return bool(_get_index().chunks)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        n = build_index()
        kind = "sémantique" if (INDEX_DIR / "faiss.index").exists() else "TF-IDF"
        print(f"✅ Index RAG construit : {n} passage(s) — backend {kind}.")
        if n == 0:
            print("⚠️  Aucun document trouvé. Placez des fichiers PDF/TXT/MD dans rag/documents/ puis relancez.")
    elif cmd == "query":
        q = " ".join(sys.argv[2:]) or "marchés publics tunisiens"
        for r in search(q):
            print(f"[{r['score']}] ({r['source']}) {r['text'][:160]}…")
    else:
        print("Usage : python -m rag.rag_engine [build|query \"...\"]")
