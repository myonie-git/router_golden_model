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
class StopPrim:
    """
    High-level Stop primitive.
    Marks the end of primitive execution for a core.
    No additional parameters needed.
    """
    pass


@dataclass
class PrimOp:
    kind: Literal["send", "recv", "stop"]
    send: Optional[SendPrim] = None
    recv: Optional[RecvPrim] = None
    stop: Optional[StopPrim] = None
    # Optional: if provided in config, runner will write this op into memory at
    # this 32B cell address before parsing prim queue from memory.
    mem_addr: Optional[int] = None


# -------------------------- Prim encoding in memory --------------------------
# One primitive per 32B cell starting at address 0x0.
# All-zero cell (or uninitialized) marks end of prim queue.
# Unified Layout (supports send and recv in the same primitive):
#   FLAGS:
#     [4]     : send_valid flag (1=enabled, 0=disabled)
#     [5]     : recv_valid flag (1=enabled, 0=disabled)
#   SEND (present if [4] == 1):
#     [6]     : cell_or_neuron (0=cell, 1=neuron)
#     [7:9]   : message_num (u16, big-endian; 0 treated as 1)
#     [9:11]  : send_addr   (u16, big-endian; 32B addressing)
#     [11:13] : para_addr   (u16, big-endian; 32B addressing)
#   RECV (present if [5] == 1):
#     [13]    : tag_id (u8)
#     [14:16] : recv_addr (u16, big-endian; 32B addressing)
#     [16]    : end_num (u8, optional; 0 if unused)
#     [17]    : relay_mode (u8)
#     [18]    : mc_y (u8)
#     [19]    : mc_x (u8)
#   RESERVED:
#     [0:4], [20:32] reserved (0)
#   STOP (special encoding):
#     [0]     : 0x0
#     [1]     : 0x3
#     [2:32]  : reserved (0)

PRIM_KIND_SEND = 1
PRIM_KIND_RECV = 2
PRIM_KIND_STOP = 3


def encode_prim_cell(op: "PrimOp") -> bytes:
    buf = bytearray(32)
    # STOP special-case
    if op.kind == "stop":
        buf[0] = 0x0
        buf[1] = PRIM_KIND_STOP  # 0x3
        return bytes(buf)

    # Unified encoding with flags at [4] (send) and [5] (recv)
    if op.send is not None:
        buf[4] = 0x1
        buf[6] = op.send.cell_or_neuron & 0xFF
        msgn = op.send.normalized_message_num()
        buf[7:9] = int(msgn & 0xFFFF).to_bytes(2, byteorder="big", signed=False)
        buf[9:11] = int(op.send.send_addr & 0xFFFF).to_bytes(2, byteorder="big", signed=False)
        buf[11:13] = int(op.send.para_addr & 0xFFFF).to_bytes(2, byteorder="big", signed=False)
    if op.recv is not None:
        buf[5] = 0x1
        buf[13] = op.recv.tag_id & 0xFF
        buf[14:16] = int(op.recv.recv_addr & 0xFFFF).to_bytes(2, byteorder="big", signed=False)
        # Optional fields encoded for completeness
        buf[16] = (op.recv.end_num or 0) & 0xFF
        buf[17] = op.recv.relay_mode & 0xFF
        buf[18] = op.recv.mc_y & 0xFF
        buf[19] = op.recv.mc_x & 0xFF

    # If neither flag is set, returns zeroed cell (terminator)
    return bytes(buf)


def decode_prim_cell(cell_bytes: bytes) -> Optional["PrimOp"]:
    if len(cell_bytes) != 32:
        raise ValueError("prim cell must be 32 bytes")
    if all(b == 0 for b in cell_bytes):
        return None
    # STOP special-case: [0]=0x0, [1]=0x3
    if cell_bytes[0] == 0x0 and cell_bytes[1] == PRIM_KIND_STOP:
        return PrimOp(kind="stop", stop=StopPrim())

    send_valid = (cell_bytes[4] != 0)
    recv_valid = (cell_bytes[5] != 0)

    if not send_valid and not recv_valid:
        # Unknown/incomplete -> treat as terminator
        return None

    send_prim = None
    recv_prim = None
    if send_valid:
        cell_or_neuron = cell_bytes[6]
        message_num = int.from_bytes(cell_bytes[7:9], byteorder="big", signed=False)
        send_addr = int.from_bytes(cell_bytes[9:11], byteorder="big", signed=False)
        para_addr = int.from_bytes(cell_bytes[11:13], byteorder="big", signed=False)
        send_prim = SendPrim(cell_or_neuron=cell_or_neuron, message_num=message_num, send_addr=send_addr, para_addr=para_addr)
    if recv_valid:
        tag_id = cell_bytes[13]
        recv_addr = int.from_bytes(cell_bytes[14:16], byteorder="big", signed=False)
        end_num = cell_bytes[16]
        relay_mode = cell_bytes[17]
        mc_y = cell_bytes[18]
        mc_x = cell_bytes[19]
        recv_prim = RecvPrim(
            recv_addr=recv_addr,
            tag_id=tag_id,
            end_num=(end_num if end_num != 0 else None),
            relay_mode=relay_mode,
            mc_y=mc_y,
            mc_x=mc_x,
        )

    kind = "send" if send_valid else "recv"
    return PrimOp(kind=kind, send=send_prim, recv=recv_prim)


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




