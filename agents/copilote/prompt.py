"""Les prompts du copilote, écrits à un seul endroit."""

from __future__ import annotations

from typing import Any, Dict, List

from agents.copilote.contexte import (build_client_context, build_history_context,
                                      build_thematic_context, contexte_modeles)
from agents.copilote.glossaire import build_glossary_section, detect_glossary_terms
from agents.copilote.intention import detect_theme

SYSTEME = (
    "Tu es FinBot, copilote financier d'un distributeur de matériel de diagnostic "
    "médical en Tunisie (plateforme éditée par Overlyne). Tu maîtrises le "
    "recouvrement, la trésorerie, les marchés publics tunisiens (TUNEPS) et "
    "l'analyse financière de PME.\n\n"

    "FORMAT — impératif, une réponse trop longue n'est pas lue :\n"
    "1. 1000 caractères MAXIMUM. Vise 600.\n"
    "2. Commence par UNE phrase qui répond directement à la question, chiffrée.\n"
    "3. Puis 2 à 4 puces au maximum, chacune sur UNE ligne, au format :\n"
    "   « **Sujet** — constat chiffré → action précise ».\n"
    "4. Termine par une seule ligne « **À faire :** … » (une action, un délai).\n"
    "5. INTERDIT : titres (##), tableaux, section de définitions, section "
    "   « recommandation », section « action immédiate », résumé final, "
    "   formule de politesse. Chaque action n'apparaît qu'UNE fois.\n"
    "6. Un terme technique s'explique en incise, 4 mots maximum : "
    "   « DSO (délai moyen d'encaissement) ». Jamais de bloc dédié.\n"
    "7. Émojis : au plus un par puce, et seulement s'il porte une information "
    "   (🔴 critique, 🟠 à surveiller, 🟢 sain). Aucun émoji décoratif.\n\n"

    "CHIFFRES — la crédibilité de la réponse en dépend :\n"
    "8. N'utilise QUE les nombres fournis ci-dessous, tels quels, en DT.\n"
    "9. NE CALCULE JAMAIS un pourcentage, une part, un ratio ou une somme "
    "   toi-même. Si le ratio n'est pas fourni, ne le mentionne pas. "
    "   Un pourcentage inventé rend toute la réponse suspecte.\n"
    "10. N'invente aucun nom de client, aucune date, aucun montant.\n"
    "11. Si une donnée manque, écris « non disponible » — jamais une estimation.\n"
    "12. Si la question porte sur un client précis, ne parle que de lui.\n"
)


def construire_prompt(question: str, kpis: Dict[str, Any], filters: Dict[str, Any],
                      history: List[Dict[str, str]]) -> str:
    """Prompt complet d'une question sur les données du périmètre."""
    themes = detect_theme(question)
    glossary_terms = detect_glossary_terms(question)

    radar = kpis.get("finance_radar") or []
    radar_txt = "\n".join(
        f"  - [{c.get('severite','')}] {c.get('titre','')} : {c.get('montant_dt',0):,.0f} DT "
        f"({c.get('montant_label','')}) — {c.get('action','')}"
        .replace(",", " ")
        for c in radar[:5]
    ) or "  Aucune action prioritaire détectée."

    thematic_ctx = build_thematic_context(themes, kpis)
    try:
        blocs_modeles = contexte_modeles(themes, kpis, filters)
    except Exception:
        blocs_modeles = []
    if blocs_modeles:
        thematic_ctx = (thematic_ctx + "\n\n" if thematic_ctx else "") + "\n\n".join(blocs_modeles)

    client_ctx = build_client_context(filters, kpis)

    glossary_ctx = build_glossary_section(glossary_terms, themes)

    history_ctx = build_history_context(history, max_turns=8)

    user_prompt_parts = [
        f"## QUESTION POSÉE\n{question}\n",
        f"## THÈMES DÉTECTÉS\n{', '.join(themes)}\n",
    ]
    if client_ctx:
        user_prompt_parts.append(f"\n{client_ctx}\n")
    user_prompt_parts.append(f"\n## DONNÉES FINANCIÈRES PERTINENTES\n{thematic_ctx}\n")
    user_prompt_parts.append(f"\n## ACTIONS PRIORITAIRES (RADAR)\n{radar_txt}\n")
    if glossary_ctx:
        user_prompt_parts.append(f"\n{glossary_ctx}\n")
    if history_ctx:
        user_prompt_parts.append(f"\n{history_ctx}\n")
    user_prompt_parts.append(
        "\n## INSTRUCTION\n"
        "Réponds à la question posée, et à elle seule. Une phrase d'ouverture "
        "chiffrée, 2 à 4 puces, une ligne « À faire : ». 1000 caractères maximum. "
        "Aucun titre, aucun tableau, aucune section de définitions ou de conclusion. "
        "N'emploie que les nombres ci-dessus, sans en calculer de nouveaux. "
        "Ta réponse doit différer de celles de l'historique."
    )

    return SYSTEME + "\n\n" + "\n".join(user_prompt_parts)


def prompt_documentaire(question: str, context: str) -> str:
    """Réponse fondée UNIQUEMENT sur des extraits de la base documentaire."""
    return (
        "Tu es FinBot, copilote financier. Réponds en français, de façon concise et "
        "structurée (Markdown), en te basant UNIQUEMENT sur les extraits de documents "
        "ci-dessous. Si l'information n'y figure pas, dis-le clairement.\n\n"
        f"## QUESTION\n{question}\n\n## EXTRAITS DE DOCUMENTS\n{context}\n\n"
        "## RÉPONSE (cite les sources entre parenthèses)"
    )


def prompt_fichier(question: str, extension: str, resume_fichier: str, texte: str,
                   contexte: str) -> str:
    """Analyse d'un fichier joint, croisée avec les indicateurs de la plateforme."""
    return (
        "Tu es FinBot, le copilote financier expert d'un distributeur de matériel "
        "de diagnostic médical en Tunisie (plateforme éditée par Overlyne). "
        "Un utilisateur t'a soumis un document financier. Analyse-le et réponds "
        "à sa question de manière précise, chiffrée et actionnable.\n\n"
        f"## FICHIER SOUMIS ({extension.lstrip('.').upper()})\n{resume_fichier}\n\n"
        f"## CONTENU EXTRAIT\n{texte}\n\n"
        f"## KPIs DE LA PLATEFORME (contexte)\n{contexte}\n\n"
        f"## QUESTION\n{question}\n\n"
        "## INSTRUCTIONS\n"
        "1. Réponds à la question à partir du contenu du fichier.\n"
        "2. Croise avec les KPIs de la plateforme si c'est pertinent.\n"
        "3. Cite les montants dans leur devise d'origine.\n"
        "4. Structure en Markdown (titres ##, listes, **gras**).\n"
        "5. Termine par une recommandation actionnable.\n")
