from pathlib import Path

from data_preparation_pipeline import prepare_data_layer

if __name__ == "__main__":
    data_dir = Path(__file__).resolve().parent / "data_pfe"
    output_dir = Path(__file__).resolve().parent / "output"
    tables_clean, warehouse = prepare_data_layer(data_dir, output_dir)
    print(f"Output files written to: {output_dir.resolve()}")
    print(f"Clean tables: {len(tables_clean)}")
    print(f"Warehouse tables: {len(warehouse)}")
