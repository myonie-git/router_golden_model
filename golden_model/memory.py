from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

MEM_CELL_BYTES = 32  # 256-bit wide

def _hex_to_bytes_32B(hex_str: str) -> bytes:
    s = "".join(hex_str.strip().split())
    # Accept longer/shorter by trimming/padding to 32B
    if len(s) < MEM_CELL_BYTES * 2:
        s = s.zfill(MEM_CELL_BYTES * 2)
    elif len(s) > MEM_CELL_BYTES * 2:
        s = s[-MEM_CELL_BYTES * 2 :]
    return bytes.fromhex(s)

@dataclass
class CoreMemory:
    """
    Simple 32-byte-cell addressable memory used by golden model.

    - Address unit is 32B (one cell), matching SV core memory top.
    - Supports 8B and 1B masked writes to a 32B cell.
    - Can load/store files in the '@XXXX <hex>' format like inputs.txt.
    """

    num_cells: int = 24576

    def __post_init__(self) -> None:
        self._cells: Dict[int, bytearray] = {}

    # -------------------------- Load/Store --------------------------
    def load_from_inputs_file(self, path: str) -> None: 
        """
        Parse lines like: '@0000 <64-hex>' and fill memory cells.
        Extra whitespace after hex is ignored. Lines not starting with '@' are ignored.
        """
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or not line.startswith("@"):
                    continue
                # '@' + 4 hex of cell address
                addr_hex, *rest = line.split()
                addr = int(addr_hex[1:], 16)
                if addr < 0 or addr >= self.num_cells:
                    # Out-of-range lines are ignored (compatible with partial images)
                    continue
                payload = "".join(rest) if rest else ""
                data = _hex_to_bytes_32B(payload)
                self._cells[addr] = bytearray(data)

    def dump_to_file(self, path: str, start_addr: int = 0, num_cells: int | None = None) -> None:
        if num_cells is None:
            num_cells = self.num_cells - start_addr
        with open(path, "w") as f:
            for i in range(start_addr, start_addr + num_cells):
                data = self.read_cell(i)
                f.write(f"@{i:04x} {data.hex()}\n")

    # -------------------------- Read helpers --------------------------
    def read_cell(self, addr: int) -> bytes:
        self._bounds_check_cell(addr)
        return bytes(self._cells.get(addr, bytearray(MEM_CELL_BYTES)))

    def read_bytes_linear(self, start_cell_addr: int, start_byte_offset: int, length: int) -> bytes:
        """
        Read arbitrary-length byte window crossing 32B cell boundaries.
        """
        assert 0 <= start_byte_offset < MEM_CELL_BYTES
        out = bytearray()
        cell = start_cell_addr
        off = start_byte_offset
        remaining = length
        while remaining > 0:
            chunk = min(remaining, MEM_CELL_BYTES - off)
            data = self.read_cell(cell)
            out.extend(data[off : off + chunk])
            remaining -= chunk
            cell += 1
            off = 0
        return bytes(out)

    # -------------------------- Masked writes --------------------------
    def write_8B(self, cell_addr: int, segment_idx: int, data8: bytes) -> None:
        """Write one 8B segment (segment_idx in [0..3]) into a 32B cell."""
        self._bounds_check_cell(cell_addr)
        if not (0 <= segment_idx <= 3):
            raise ValueError("segment_idx must be in 0..3")
        if len(data8) != 8:
            raise ValueError("data8 must be exactly 8 bytes")
        base = self._get_cell_buf(cell_addr)
        start = segment_idx * 8
        base[start : start + 8] = data8

    def write_1B(self, cell_addr: int, byte_idx: int, value: int) -> None:
        """Write a single byte (0..255) into a 32B cell at byte_idx (0..31)."""
        self._bounds_check_cell(cell_addr)
        if not (0 <= byte_idx < MEM_CELL_BYTES):
            raise ValueError("byte_idx must be in 0..31")
        if not (0 <= value <= 0xFF):
            raise ValueError("value must be a byte")
        base = self._get_cell_buf(cell_addr)
        base[byte_idx] = value

    # -------------------------- Internal --------------------------
    def _get_cell_buf(self, addr: int) -> bytearray:
        if addr not in self._cells:
            self._cells[addr] = bytearray(MEM_CELL_BYTES)
        return self._cells[addr]

    def _bounds_check_cell(self, addr: int) -> None:
        if not (0 <= addr < self.num_cells):
            raise IndexError(f"cell addr out of range: {addr}")


def iter_cells_span_from_A_8B(a_8b: int) -> Tuple[int, int]:
    """
    Map A (8B addressing) to (cell_addr_delta, segment_idx).
    A is measured in 8B units; 4 segments per 32B cell.
    """
    cell_delta = a_8b >> 2
    seg_idx = a_8b & 0x3
    return cell_delta, seg_idx


def iter_cells_span_from_A_1B(a_1b: int) -> Tuple[int, int]:
    """
    Map A (1B addressing) to (cell_addr_delta, byte_idx).
    A is measured in 1B units; 32 bytes per 32B cell.
    """
    cell_delta = a_1b >> 5
    byte_idx = a_1b & 0x1F
    return cell_delta, byte_idx




