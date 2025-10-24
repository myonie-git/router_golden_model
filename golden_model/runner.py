#TODO: 缓冲机制的触发是有误的，需要修改
#TODO: 需要添加多播机制
#TODO: 需要添加对Normal和Single Mode的支持
#TODO: _buffer_send_payload的处理并没有考虑A0,Const
#TODO: 添加对End_Num的支持

from __future__ import annotations

import sys
from pathlib import Path
# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
import warnings
from typing import Dict, Tuple

from golden_model.memory import CoreMemory
from golden_model.prims import SendPrim, RecvPrim, StopPrim, CoreConfig, PrimOp
from golden_model.simulator import ArrayConfig, run_simulation
from golden_model.core import NoCSimulator


def load_core_config(obj: dict, warn_deprecated: bool = False) -> CoreConfig:

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
            if isinstance(send_obj, dict):
                s = dict(send_obj)
                msgs = s.get("messages")
                if isinstance(msgs, list):
                    new_msgs = []
                    for m in msgs:
                        if isinstance(m, dict):
                            m2 = dict(m)
                            if  ("cnt" in m2):
                                try:
                                    m2["cnt"] = int(m2["cnt"]) + 1 
                                except Exception:
                                    pass
                            new_msgs.append(m2)
                    s["messages"] = new_msgs
                    s["message_num"] = len(new_msgs)
                else:
                    if ("message_num" in s):
                        try:
                            s["message_num"] = int(s["message_num"]) + 1
                        except Exception:
                            pass
                send = SendPrim(**s)
            else:
                send = None
            recv = None
            if isinstance(recv_obj, dict):
                r = dict(recv_obj)
                r["use_end_num"] = ("end_num" in r)
                recv = RecvPrim(**r)
            if send is None and recv is None:
                raise ValueError("prim_queue entry must specify 'send', 'recv', or 'stop'")
            entry_kind = "send" if send is not None else "recv"
            q.append(PrimOp(kind=entry_kind, send=send, recv=recv, mem_addr=mem_addr))
        return CoreConfig(init_mem_path=obj.get("init_mem_path"), prim_queue=q)
        
    if ("send_queue" in obj or "recv_queue" in obj):
        if "prim_queue" in obj:
            warnings.warn(
                "DEPRECATED: Detected send_queue/recv_queue; they are ignored when prim_queue is present. "
                "Please migrate fully to prim_queue and remove legacy fields.",
                UserWarning,
            )
        else:
            warnings.warn(
                "DEPRECATED: Using legacy send_queue/recv_queue; auto-converting to prim_queue. "
                "This path will be removed in the future. Please migrate to prim_queue.",
                UserWarning,
            )

    sends_input = obj.get("send_queue", [])
    sends: list[SendPrim] = []
    for s_in in sends_input:
        if not isinstance(s_in, dict):
            continue
        s = dict(s_in)
        msgs = s.get("messages")
        if isinstance(msgs, list):
            new_msgs = []
            for m in msgs:
                if isinstance(m, dict):
                    m2 = dict(m)
                    if  ("cnt" in m2):
                        try:
                            m2["cnt"] = max(1, int(m2["cnt"]) + 1)
                        except Exception:
                            pass
                    new_msgs.append(m2)
            s["messages"] = new_msgs
            s["message_num"] = len(new_msgs)
        else:
            if ("message_num" in s):
                try:
                    s["message_num"] = int(s["message_num"]) + 1
                except Exception:
                    pass
        sends.append(SendPrim(**s))
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
            out_path = seeded_dir / f"{y}_{x}_mem_config.txt"
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
                seeded_path = str(Path(args.emit_seeded_dir) / f"{y}_{x}_mem_config.txt")
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
        out_path = out_dir / f"{y}_{x}_mem_config.txt"
        node.mem.dump_to_file(str(out_path))
    print(f"Wrote memories to {out_dir}")


if __name__ == "__main__":
    main()