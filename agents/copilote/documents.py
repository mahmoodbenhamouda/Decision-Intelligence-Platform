"""
agents/copilote/documents.py
============================
Réponses tirées de la base documentaire (RAG) : contrats, notices, procédures
indexés dans `rag/`, y compris les documents scannés ajoutés par l'OCR.

Utilisée quand la question commence par « doc: », ou quand elle ne relève
d'aucun thème des données internes.
"""

from __future__ import annotations

from typing import Optional

from agents.copilote import llm
from agents.copilote.prompt import prompt_documentaire


def reponse_documentaire(question: str) -> Optional[str]:
    """Synthèse LLM si une clé est disponible, sinon extraits sourcés ; None si
    rien de pertinent."""
    try:
        from rag.rag_engine import search as rag_search
    except Exception:
        return None
    try:
        hits = rag_search(question, k=4)
    except Exception:
        hits = []
    if not hits:
        return None

    context = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
    sources = ", ".join(sorted({h["source"] for h in hits}))

    # 1) Synthèse LLM si clé disponible
    if llm.cle_disponible():
        txt = llm.interroger(prompt_documentaire(question, context))
        if txt:
            return f"{txt}\n\n*Sources : {sources}*"

    # 2) Repli sans LLM : extraits les plus pertinents, sourcés
    lines = ["## 📚 D'après votre base documentaire\n"]
    for h in hits[:3]:
        snippet = " ".join(h["text"].split())
        if len(snippet) > 340:
            snippet = snippet[:340] + "…"
        lines.append(f"- {snippet}\n  *(source : {h['source']})*")
    lines.append("\n_Réponse issue des documents (RAG). Ajoutez des fichiers dans `rag/documents/` "
                 "puis relancez `python -m rag.rag_engine build` pour enrichir la base._")
    return "\n".join(lines)
