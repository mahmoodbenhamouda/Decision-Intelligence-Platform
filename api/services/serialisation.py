"""Conversion des résultats des moteurs (numpy, pandas) en valeurs JSON."""

from __future__ import annotations

from typing import Any

import pandas as pd


def json_safe(value: Any):
    """Types numpy et pandas → types Python ; NaN → None ; clés en texte."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and pd.isna(value):
        return None
    return value
