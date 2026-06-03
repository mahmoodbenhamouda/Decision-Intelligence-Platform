from pathlib import Path
import pandas as pd

data_dir = Path(r"c:\Users\Mahmoud\Desktop\satge_pfe\data_pfe")

for path in sorted(data_dir.glob("*.csv")):
    try:
        # Just count lines without loading into pandas
        with open(path, "rb") as f:
            line_count = sum(1 for _ in f)
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"{path.name:60s}  lines={line_count:>10,}  size={size_mb:>8.2f} MB")
    except Exception as e:
        print(f"{path.name}: ERROR {e}")