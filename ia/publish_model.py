"""Publish a model version in models/registry.json (brief 05, step H).

Registry entry per layer: {"mv": int, "file": str, "metrics": {...}}.
The Cloud API reads reg[layer]["mv"] and reg[layer]["file"].
"""
from __future__ import annotations

import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "models" / "registry.json"
LAYERS = ("edge", "fog", "cloud")


def publish(layer: str, src, mv: int, metrics: dict) -> None:
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {LAYERS}")
    dst_dir = ROOT / "models" / layer
    dst_dir.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(src)
    if src.resolve() != (dst_dir / src.name).resolve():
        shutil.copy(src, dst_dir / src.name)  # copy only if not already in place
    reg = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
    reg[layer] = {"mv": int(mv), "file": src.name, "metrics": metrics}
    missing = [k for k in LAYERS if k not in reg]
    if missing:
        raise ValueError(f"registry would lack layers {missing}")
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")