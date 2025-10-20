from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict

from .memory import CoreMemory


def _sign_extend(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return (value ^ sign_bit) - sign_bit


@dataclass
class RouterTableEntry:
    """
    128-bit per-message entry as constructed in SV tb `genRouterTable`.

    Bit mapping (from tb_router_unit_full.sv):
      [0]   : S (unused by model)
      [1]   : T (unused by model)
      [2]   : E (unused by model)
      [3]   : Q (multicast flag; not implemented -> treated as 0/ignored)
      [11:6]: Y (6b, signed offset in cores)
      [17:12]: X (6b, signed offset in cores)
      [31:18]: A0 (14b; start offset; 8B units for cell mode, 1B for neuron)
      [43:32]: CNT (12b; pack_per_message for cell-mode, neuron_per_message for neuron-mode)
      [55:44]: A_OFFSET (12b signed; in pack units: 8B for cell, 1B for neuron)
      [62:56]: CONST (7b; group size = CONST+1, with 0 interpreted as 1)
      [63]   : HANDSHAKE (1b)
      [71:64]: TAG_ID (8b)
      [72]   : EN (1b)
    """

    s: int
    t: int
    e: int
    q: int
    y: int
    x: int
    a0: int
    cnt: int
    a_offset: int
    const_raw: int
    handshake: bool
    tag_id: int
    en: bool

    @property
    def group_size(self) -> int:
        # CONST=0 -> 1, else CONST+1
        return 1 if self.const_raw == 0 else (self.const_raw + 1)

    @staticmethod
    def from_packet128(packet: int) -> "RouterTableEntry":
        # Extract bits by mask/shift according to mapping above
        s = (packet >> 0) & 0x1
        t = (packet >> 1) & 0x1
        e = (packet >> 2) & 0x1
        q = (packet >> 3) & 0x1
        y = _sign_extend((packet >> 6) & 0x3F, 6)
        x = _sign_extend((packet >> 12) & 0x3F, 6)
        a0 = (packet >> 18) & 0x3FFF
        cnt = (packet >> 32) & 0xFFF
        a_offset = _sign_extend((packet >> 44) & 0xFFF, 12)
        const_raw = (packet >> 56) & 0x7F
        handshake = ((packet >> 63) & 0x1) == 1
        tag_id = (packet >> 64) & 0xFF
        en = ((packet >> 72) & 0x1) == 1
        return RouterTableEntry(
            s=s, t=t, e=e, q=q, y=y, x=x, a0=a0, cnt=cnt,
            a_offset=a_offset, const_raw=const_raw,
            handshake=handshake, tag_id=tag_id, en=en,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RTE(tag={self.tag_id}, en={self.en}, YX=({self.y},{self.x}), "
            f"A0={self.a0}, CNT={self.cnt}, A_OFF={self.a_offset}, CONST={self.const_raw})"
        )


def decode_two_packets_from_cell(cell_bytes: bytes) -> Tuple[int, int]:
    """
    In tb, a 256b entry packs two 128b packets: lower 128b then upper 128b.
    Memory is stored as 32B (big-endian hex lines). We'll treat the 32B
    as big-endian for conversion to int and then split.
    """
    if len(cell_bytes) != 32:
        raise ValueError("cell_bytes must be 32 bytes")
    # Interpret as big-endian integer to match hex string semantics
    word256 = int.from_bytes(cell_bytes, byteorder="big", signed=False)
    lower128 = word256 & ((1 << 128) - 1)
    upper128 = (word256 >> 128) & ((1 << 128) - 1)
    return lower128, upper128


def parse_router_table_from_memory(mem: CoreMemory, base_addr: int, message_num: int) -> List[RouterTableEntry]:
    """
    Parse `message_num` entries starting from `base_addr` in 32B cells.
    Each cell stores 2 entries (lower then upper). Extra entries are ignored.
    """
    entries: List[RouterTableEntry] = []
    needed_cells = (message_num + 1) // 2
    for i in range(needed_cells):
        cell = mem.read_cell(base_addr + i)
        low, up = decode_two_packets_from_cell(cell)
        entries.append(RouterTableEntry.from_packet128(low))
        if len(entries) < message_num:
            entries.append(RouterTableEntry.from_packet128(up))
    # Trim in case of odd count
    return entries[:message_num]


def encode_packet_from_fields(fields: Dict) -> int:
    """
    Build 128-bit packet from dict fields matching RouterTableEntry semantic names:
    { s,t,e,q,y,x,a0,cnt,a_offset,const_raw,handshake,tag_id,en }
    Signed fields (y:6, x:6, a_offset:12) are encoded in two's complement within their bit width.
    """
    def to_twos(v: int, bits: int) -> int:
        mask = (1 << bits) - 1
        return v & mask

    pkt = 0
    pkt |= (fields.get("s", 0) & 0x1) << 0
    pkt |= (fields.get("t", 0) & 0x1) << 1
    pkt |= (fields.get("e", 0) & 0x1) << 2
    pkt |= (fields.get("q", 0) & 0x1) << 3
    pkt |= to_twos(fields.get("y", 0), 6) << 6
    pkt |= to_twos(fields.get("x", 0), 6) << 12
    pkt |= (fields.get("a0", 0) & 0x3FFF) << 18
    pkt |= (fields.get("cnt", 1) & 0xFFF) << 32
    pkt |= to_twos(fields.get("a_offset", 0), 12) << 44
    pkt |= (fields.get("const_raw", 0) & 0x7F) << 56
    pkt |= (1 if fields.get("handshake", False) else 0) << 63
    pkt |= (fields.get("tag_id", 0) & 0xFF) << 64
    pkt |= (1 if fields.get("en", 1) else 0) << 72
    return pkt & ((1 << 128) - 1)


def write_router_table_to_memory(mem: CoreMemory, base_addr: int, packets: List[int]) -> None:
    """Write list of 128-bit packets into memory two per 32B cell (low then high)."""
    i = 0
    cell_idx = 0
    while i < len(packets):
        low = packets[i]
        up = packets[i + 1] if (i + 1) < len(packets) else 0
        word256 = (up << 128) | low
        mem._cells[base_addr + cell_idx] = bytearray(word256.to_bytes(32, byteorder="big"))
        i += 2
        cell_idx += 1




