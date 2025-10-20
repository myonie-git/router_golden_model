from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Literal, Union


@dataclass
class SendPrim:
    """
    High-level Send primitive.

    - cell_or_neuron: 0 -> SendCell (8B packets aggregated per 32B cell);
                      1 -> SendNeuron (1B packets)
    - neuron_type: reserved (always 0 for 8-bit in this golden model)
    - message_num: number of messages in router table (0 -> 1)
    - send_addr:   16-bit cell address aligned (32B addressing)
    - para_addr:   base address for router table entries (32B addressing)
    - messages:    Optional manual message specs; if provided, runner writes them
                   into memory at para_addr (two per cell) before execution.
    """

    cell_or_neuron: int  # 0=cell, 1=neuron
    neuron_type: int = 0
    message_num: int = 1
    send_addr: int = 0
    para_addr: int = 0
    messages: Optional[List[dict]] = None

    def normalized_message_num(self) -> int:
        return 1 if self.message_num == 0 else self.message_num


@dataclass
class RecvPrim:
    """
    High-level Recv primitive.
    - recv_addr: base cell address (32B addressing)
    - tag_id: tag to accept
    - end_num: optional upper bound of end markers (unused in high-level model)
    - relay_mode / mc_x / mc_y: ignored at high level here
    """

    recv_addr: int
    tag_id: int
    end_num: Optional[int] = None
    relay_mode: int = 0
    mc_y: int = 0
    mc_x: int = 0


@dataclass
class PrimOp:
    kind: Literal["send", "recv"]
    send: Optional[SendPrim] = None
    recv: Optional[RecvPrim] = None


@dataclass
class CoreConfig:
    """Configuration bundle for one core in the array."""

    init_mem_path: Optional[str] = None
    prim_queue: List[PrimOp] = None
    # Back-compat (optional): if present, the runner may fold them into prim_queue
    send_queue: Optional[List[SendPrim]] = None
    recv_queue: Optional[List[RecvPrim]] = None

    def __post_init__(self) -> None:
        if self.prim_queue is None:
            self.prim_queue = []
        if self.send_queue is None:
            self.send_queue = []
        if self.recv_queue is None:
            self.recv_queue = []




