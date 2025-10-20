from __future__ import annotations

import sys
from pathlib import Path
# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from typing import Dict, Tuple

from golden_model.memory import CoreMemory
from golden_model.prims import SendPrim, RecvPrim, CoreConfig, PrimOp
from golden_model.simulator import ArrayConfig, run_simulation


def load_core_config(obj: dict) -> CoreConfig:
    # Preferred unified queue
    if "prim_queue" in obj:
        q = []
        for it in obj["prim_queue"]:
            kind = it["kind"]
            if kind == "send":
                q.append(PrimOp(kind="send", send=SendPrim(**it["send"])) )
            elif kind == "recv":
                q.append(PrimOp(kind="recv", recv=RecvPrim(**it["recv"])) )
            else:
                raise ValueError(f"unknown prim kind: {kind}")
        return CoreConfig(init_mem_path=obj.get("init_mem_path"), prim_queue=q)
    # Back-compat
    sends = [SendPrim(**s) for s in obj.get("send_queue", [])]
    recvs = [RecvPrim(**r) for r in obj.get("recv_queue", [])]
    q = [PrimOp(kind="send", send=s) for s in sends] + [PrimOp(kind="recv", recv=r) for r in recvs]
    return CoreConfig(init_mem_path=obj.get("init_mem_path"), prim_queue=q)


def main():
    ap = argparse.ArgumentParser(description="Golden model runner for Tianjic Core array")
    ap.add_argument("config", type=str, help="JSON file describing array and cores")
    ap.add_argument("--out_dir", type=str, default="out_mem", help="Where to write resulting memories")
    args = ap.parse_args()

    cfg_json = json.loads(Path(args.config).read_text())
    h = int(cfg_json["height"]) ; w = int(cfg_json["width"]) ;
    cores_cfg: Dict[Tuple[int, int], CoreConfig] = {}
    for ent in cfg_json.get("cores", []):
        y, x = int(ent["y"]), int(ent["x"]) ;
        cores_cfg[(y, x)] = load_core_config(ent["config"])

    sim = run_simulation(ArrayConfig(height=h, width=w, cores=cores_cfg))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for (y, x), node in sim.cores.items():
        out_path = out_dir / f"core_{y}_{x}.txt"
        node.mem.dump_to_file(str(out_path))
    print(f"Wrote memories to {out_dir}")


if __name__ == "__main__":
    main()




