"""
ml_engine/deep — modèles d'apprentissage profond (PyTorch).

- `recommandation.py` : recommandation de produits (vente croisée) par un réseau
  Wide & Deep, évalué en walk-forward contre des références triviales et deux
  modèles non profonds.

PyTorch est une dépendance OPTIONNELLE : l'API et les agents ne lisent que les
recommandations précalculées (`output/recommandations.json`). Sans PyTorch,
l'entraînement compare les modèles non profonds et le registre le signale.
"""
