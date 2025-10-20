from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .core import NoCSimulator
from .prims import CoreConfig


@dataclass
class ArrayConfig:
    height: int
    width: int
    cores: Dict[Tuple[int, int], CoreConfig]


def run_simulation(cfg: ArrayConfig) -> NoCSimulator:
    sim = NoCSimulator((cfg.height, cfg.width), cfg.cores)
    sim.run()
    return sim




