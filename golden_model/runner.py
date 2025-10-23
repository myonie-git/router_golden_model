from __future__ import annotations

import sys
from pathlib import Path
# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from typing import Dict, Tuple

from golden_model.memory import CoreMemory
from golden_model.prims import SendPrim, RecvPrim, StopPrim, CoreConfig, PrimOp
from golden_model.simulator import ArrayConfig, run_simulation
from golden_model.core import NoCSimulator


def load_core_config(obj: dict) -> CoreConfig:
    # Preferred unified queue
    if "prim_queue" in obj:
        q = []
        for it in obj["prim_queue"]:
            mem_addr = it.get("mem_addr")
            kind = it.get("kind")
            # STOP primitive (by kind or explicit boolean field)
            if kind == "stop" or it.get("stop") is True:
                q.append(PrimOp(kind="stop", stop=StopPrim(), mem_addr=mem_addr))
                continue
            # Combined support: allow both 'send' and 'recv' fields in one entry
            send_obj = it.get("send")
            recv_obj = it.get("recv")
            send = SendPrim(**send_obj) if isinstance(send_obj, dict) else None
            recv = RecvPrim(**recv_obj) if isinstance(recv_obj, dict) else None
            if send is None and recv is None:
                raise ValueError("prim_queue entry must specify 'send', 'recv', or 'stop'")
            entry_kind = "send" if send is not None else "recv"
            q.append(PrimOp(kind=entry_kind, send=send, recv=recv, mem_addr=mem_addr))
        return CoreConfig(init_mem_path=obj.get("init_mem_path"), prim_queue=q)
    # Back-compat
    sends = [SendPrim(**s) for s in obj.get("send_queue", [])]
    recvs = [RecvPrim(**r) for r in obj.get("recv_queue", [])]
    q = [PrimOp(kind="send", send=s) for s in sends] + [PrimOp(kind="recv", recv=r) for r in recvs]
    return CoreConfig(init_mem_path=obj.get("init_mem_path"), prim_queue=q)


def main():
    ap = argparse.ArgumentParser(description="Golden model runner for Tianjic Core array")
    ap.add_argument("--config", "-c", type=str, default="config/sample_config.json", help="JSON file describing array and cores")
    ap.add_argument("--out_dir", type=str, default="out_mem", help="Where to write resulting memories")
    ap.add_argument("--emit_seeded_dir", type=str, default=None, help="If set, export seeded (phase-1) memories after writing prims/messages into memory")
    ap.add_argument("--seed_only", action="store_true", help="Only do seeding (phase-1) and export to --emit_seeded_dir, then exit")
    args =  ap.parse_args()

    cfg_json = json.loads(Path(args.config).read_text())
    h = int(cfg_json["height"]) ; w = int(cfg_json["width"]) ;
    cores_cfg: Dict[Tuple[int, int], CoreConfig] = {}
    for ent in cfg_json.get("cores", []):
        y, x = int(ent["y"]), int(ent["x"]) ;
        cores_cfg[(y, x)] = load_core_config(ent["config"])

    # Phase-1: build simulator (which seeds prims/messages into memory and parses prims from memory)
    sim_seed = NoCSimulator((h, w), cores_cfg)
    if args.emit_seeded_dir:
        seeded_dir = Path(args.emit_seeded_dir)
        seeded_dir.mkdir(parents=True, exist_ok=True)
        for (y, x), node in sim_seed.cores.items():
            out_path = seeded_dir / f"core_{y}_{x}.txt"
            node.mem.dump_to_file(str(out_path))
        print(f"Seeded memories written to {seeded_dir}")
    if args.seed_only:
        # Stop after phase-1 if requested
        return

    # Phase-2: if seeded_dir provided, re-load from those memories without seeding again
    if args.emit_seeded_dir:
        cores_cfg_run: Dict[Tuple[int, int], CoreConfig] = {}
        for y in range(h):
            for x in range(w):
                seeded_path = str(Path(args.emit_seeded_dir) / f"core_{y}_{x}.txt")
                cores_cfg_run[(y, x)] = CoreConfig(init_mem_path=seeded_path, prim_queue=[])  # skip seeding; parse from memory
        sim_run = NoCSimulator((h, w), cores_cfg_run)
        sim_run.run()
        final_sim = sim_run
    else:
        # Legacy single-phase: seed-and-run in one shot
        final_sim = NoCSimulator((h, w), cores_cfg)
        final_sim.run()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for (y, x), node in final_sim.cores.items():
        out_path = out_dir / f"core_{y}_{x}.txt"
        node.mem.dump_to_file(str(out_path))
    print(f"Wrote memories to {out_dir}")


if __name__ == "__main__":
    main()




