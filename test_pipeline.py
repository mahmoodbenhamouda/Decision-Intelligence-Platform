import sys
from pathlib import Path

# Ajouter le répertoire courant au path pour les imports
sys.path.append(str(Path(__file__).parent))

from connectors.warehouse_connector import get_warehouse
from graphs.finance_graph import build_finance_graph

def run_test():
    print("========================================")
    print(" TEST GLOBAL : FINANCE AI AGENT (POC)")
    print("========================================")
    print("\n1. Chargement du Data Warehouse...")
    wh = get_warehouse()
    if not wh:
        print("Warning: Warehouse vide ou donnees introuvables.")
        # On continue quand même pour tester le graph vide
    else:
        print(f"OK: Warehouse charge avec {len(wh)} tables.")

    print("\n2. Compilation du LangGraph...")
    try:
        graph = build_finance_graph()
        print("OK: Graphe compile.")
    except Exception as e:
        print(f"Erreur de compilation : {e}")
        return

    question = "Quels sont mes meilleurs clients et le CA global ?"
    print(f"\n3. Invocation du Graph : '{question}'")
    
    config = {"configurable": {"thread_id": "test_session_001"}}
    state = {
        "question": question,
        "session_id": "test_session_001",
        "user_id": "user_1",
        "timestamp": "2026-06-11",
        "execution_plan": [],
        "messages": [("user", question)]
    }
    
    try:
        res = graph.invoke(state, config=config)
        print("\n--- RÉSULTATS DU GRAPHE ---")
        print(f"Intention detectee : {res.get('intent', {}).get('category')}")
        print(f"Plan d execution  : {res.get('execution_plan')}")
        
        if res.get('sql_results'):
            print(f"SQL Results      : {res.get('sql_results')}")
            
        if res.get('business_insights'):
            print(f"Business Insights : {res.get('business_insights')}")
            
        print(f"Reponse finale    : {res.get('final_answer')}")
        print("---------------------------")
        print("OK: Test reussi avec succes !")
    except Exception as e:
        print(f"Test echoue : {e}")

if __name__ == "__main__":
    run_test()
