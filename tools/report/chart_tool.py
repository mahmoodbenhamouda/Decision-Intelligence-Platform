"""
tools/report/chart_tool.py
==========================
Outil LangChain pour générer des graphiques matplotlib.
"""
import json
import traceback
from pathlib import Path
from langchain.tools import tool

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

@tool("generate_chart")
def generate_chart(chart_type: str, data_json: str, title: str) -> str:
    """
    Génère un graphique simple et retourne le chemin d'accès.
    Args:
        chart_type: 'bar', 'line', ou 'scatter'
        data_json: JSON string au format {'x': [1,2,3], 'y': [4,5,6]}
        title: Titre du graphique
    """
    try:
        if not HAS_MATPLOTLIB:
            return json.dumps({"error": "matplotlib non installé"})
            
        data = json.loads(data_json)
        x = data.get("x", [])
        y = data.get("y", [])
        
        plt.figure(figsize=(10, 6))
        if chart_type == "bar":
            plt.bar(x, y, color="#2196F3")
        elif chart_type == "line":
            plt.plot(x, y, color="#FF9800", marker="o")
        elif chart_type == "scatter":
            plt.scatter(x, y, color="#4CAF50")
            
        plt.title(title)
        plt.tight_layout()
        
        out_dir = Path("reports/plots")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"chart_{chart_type}.png"
        
        plt.savefig(out_path)
        plt.close()
        
        return json.dumps({"success": True, "path": str(out_path)})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
