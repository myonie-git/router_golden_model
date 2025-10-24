from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Literal, Union

from myhdl import bin, intbv

def to_signed_bits(val, width=16):
    if not -(1 << (width-1)) <= val < (1 << (width-1)):
        raise ValueError("超出范围: %d位有符号数" % width)
    return val & ((1 << width) - 1)

def to_unsigned_bits(val, width=16):
    if not 0 <= val < (1 << width):
        raise ValueError("超出范围: %d位无符号数" % width)
    return val & ((1 << width) - 1) 

@dataclass
class SendPrim:
    """
    High-level Send primitive.

    - cell_or_neuron: 0 -> SendCell (8B packets aggregated per 32B cell);
                      1 -> SendNeuron (1B packets)
    - neuron_type: reserved (always 0 for 8-bit in this golden model)
    - message_num: number of messages in router table (stored as N-1 in memory)
    - send_addr:   16-bit cell address aligned (32B addressing)
    - para_addr:   base address for router table entries (32B addressing)
    - messages:    Optional manual message specs; if provided, runner writes them
                   into memory at para_addr (two per cell) before execution.
    """

    deps: int = 0
    cell_or_neuron: int = 0 # 0=cell, 1=neuron
    neuron_type: int = 0
    message_num: int = 0
    send_addr: int = 0
    para_addr: int = 0
    messages: Optional[List[dict]] = None


@dataclass
class RecvPrim:
    """
    High-level Recv primitive.
    - recv_addr: base cell address (32B addressing)
    - tag_id: tag to accept
    - end_num: optional upper bound of end markers (unused in high-level model)
    - relay_mode / mc_x / mc_y: ignored at high level here
    """

    deps: int = 0
    recv_addr: int = 0
    tag_id: int = 0
    end_num: int = 0
    relay_mode: int = 0
    CXY: int = 0
    mc_y: int = 0
    mc_x: int = 0
    # High-level model only: if True, Recv waits until (end_num+1) messages delivered
    use_end_num: bool = False


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
# One primitive per 32B cell (256 bits) starting at address 0x0.
# All-zero cell (or uninitialized) marks end of prim queue.
# Unified Layout (supports send and recv in the same primitive):
# Using bit-level encoding with intbv:
#   FLAGS:
#     bit[4]     : send_valid flag (1=enabled, 0=disabled)
#     bit[5]     : recv_valid flag (1=enabled, 0=disabled)
#   SEND (present if bit[4] == 1):
#     bit[48]         : cell_or_neuron (0=cell, 1=neuron)
#     bit[64:48]      : send_addr (u16, 32B addressing)
#     bit[80:64]      : message_num_minus1 (stored as N-1)
#     bit[96:80]      : para_addr (u16, 32B addressing)
#   RECV (present if bit[5] == 1):
#     bit[112:96]     : recv_addr (u16, 32B addressing)
#     bit[120:112]    : tag_id (u8)
#     bit[128:120]    : end_num (u8, optional; 0 if unused)
#     bit[136:128]    : relay_mode (u8)
#     bit[144:136]    : mc_y (u8)
#     bit[152:144]    : mc_x (u8)
#   STOP (special encoding):
#     bit[8:0]   : 0x03 (PRIM_KIND_STOP)
#     bit[256:8] : reserved (0)

PRIM_KIND_SEND = 1
PRIM_KIND_RECV = 2
PRIM_KIND_STOP = 3


def encode_prim_cell(op: "PrimOp") -> bytes:
    """使用位级别编码原语，返回32字节"""
    pic = intbv(0, min=0, max=(1<<256))
    
    # STOP special-case
    if op.kind == "stop":
        pic[4:0] = 0
        pic[8:4] = 3
        return int(pic).to_bytes(32, byteorder='big')

    # Unified encoding with flags at bit[4] (send) and bit[5] (recv)
    if op.send is not None:
        pic[4:0] = 0x6
        pic[4] = 1  # send_valid flag
        pic[16:8] = to_unsigned_bits(op.send.deps)
        pic[64:48] = to_unsigned_bits(op.send.send_addr, 16)
        pic[168] = to_unsigned_bits(op.send.cell_or_neuron, 1)
        # message_num uses minus-one storage (N-1). Accept 0 as 0 (meaning 1 after decode)
        pic[184:176] = to_unsigned_bits(max(0, op.send.message_num - 1), 8)
        pic[256:240] = to_unsigned_bits(op.send.para_addr, 16)

    if op.recv is not None:
        pic[4:0] = 0x6
        pic[5] = 1  # recv_valid flag
        pic[16:8] = to_unsigned_bits(op.recv.deps)
        pic[48:32] = to_unsigned_bits(op.recv.recv_addr, 16)
        pic[174:172] = to_unsigned_bits(op.recv.CXY, 2)
        pic[198:192] = to_signed_bits(op.recv.mc_x, 6)
        pic[190:184] = to_signed_bits(op.recv.mc_y, 6)
        pic[208:200] = to_unsigned_bits(op.recv.tag_id, 8)
        pic[216:208] = to_unsigned_bits(op.recv.end_num, 8)

    # If neither flag is set, returns zeroed cell (terminator)
    return int(pic).to_bytes(32, byteorder='big')


def decode_prim_cell(cell_bytes: bytes) -> Optional["PrimOp"]:
    """使用位级别解码原语，从32字节解析"""
    if len(cell_bytes) != 32:
        raise ValueError("prim cell must be 32 bytes")
    
    # 将字节转换为 intbv
    pic = intbv(int.from_bytes(cell_bytes, byteorder='big'), min=0, max=(1<<256))
    
    # 检查是否全零
    if int(pic) == 0:
        return None
    
    # STOP special-case: bit[8:0] == 0x3
    if int(pic[8:0]) == PRIM_KIND_STOP:
        return PrimOp(kind="stop", stop=StopPrim())

    # 检查标志位
    send_valid = bool(pic[4])
    recv_valid = bool(pic[5])

    if not send_valid and not recv_valid:
        # Unknown/incomplete -> treat as terminator
        return None

    send_prim = None
    recv_prim = None
    
    if send_valid:
        deps = int(pic[16:8])
        send_addr = int(pic[64:48])
        cell_or_neuron = int(pic[168])
        # Decode minus-one storage back to actual N
        message_num = int(pic[184:176]) + 1
        para_addr = int(pic[256:240])
        send_prim = SendPrim(
            deps = deps,
            cell_or_neuron=cell_or_neuron, 
            message_num=message_num, 
            send_addr=send_addr, 
            para_addr=para_addr
        )
    
    if recv_valid:
        deps = int(pic[16:8])
        recv_addr = int(pic[48:32])
        CXY = int(pic[174:172])
        mc_x = int(pic[198:192])
        mc_y = int(pic[190:184])
        tag_id = int(pic[208:200])
        end_num = int(pic[216:208])
        recv_prim = RecvPrim(
            deps = deps,
            recv_addr=recv_addr,
            tag_id=tag_id,
            end_num=end_num,
            relay_mode=CXY,
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