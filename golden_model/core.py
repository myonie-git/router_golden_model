from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from .memory import CoreMemory, iter_cells_span_from_A_8B, iter_cells_span_from_A_1B
from .prims import SendPrim, RecvPrim, CoreConfig, PrimOp, encode_prim_cell, decode_prim_cell
from .router_table import parse_router_table_from_memory, RouterTableEntry, encode_packet_from_fields, write_router_table_to_memory


@dataclass
class CoreNode:
    """
    Represent one core in the array, holding memory and primitive queues.
    """

    y: int
    x: int
    mem: CoreMemory
    prim_queue: List[PrimOp]
    # runtime buffer for unmatched sends (by tag)
    pending_by_tag: Dict[int, List[Tuple[bool, dict, bytes]]]  # (is_cell_mode, rte_fields, payload)

    def load_init_if_any(self, init_path: str | None) -> None:
        if init_path:
            self.mem.load_from_inputs_file(init_path)


class NoCSimulator:
    """
    High-level simulator applying send/recv semantics to produce final memories.

    Simplifications:
    - No per-cycle timing, no credit/ready. Handshake only enforces that a matching
      Recv(tag) exists anywhere in the array for the destination, else the message is skipped.
    - Q/multicast ignored for now (single-destination based on (Y,X) offset).
    - Tags buffer: if Recv(tag) not yet posted at destination, data still delivered
      (consistent with tb comment: unmatched messages buffered until Recv loads).
    """

    def __init__(self, grid_shape: Tuple[int, int], core_configs: Dict[Tuple[int, int], CoreConfig]) -> None:
        self.h, self.w = grid_shape
        self.cores: Dict[Tuple[int, int], CoreNode] = {}
        for y in range(self.h):
            for x in range(self.w):
                cfg = core_configs.get((y, x), CoreConfig())
                node = CoreNode(
                    y=y,
                    x=x,
                    mem=CoreMemory(),
                    prim_queue=[],
                    pending_by_tag={},
                )
                node.load_init_if_any(cfg.init_mem_path)
                # Register node first so seeding helpers can access it via self.cores
                self.cores[(y, x)] = node
                # Seed config-provided prims/messages into memory, then parse prim queue from memory
                self._seed_config_into_memory((y, x), cfg)
                node.prim_queue = self._parse_prims_from_memory(node.mem)

    # -------------------------- Helpers --------------------------
    def _wrap_coord(self, y: int, x: int) -> Tuple[int, int]:
        return (y % self.h, x % self.w)

    def _find_recv_acceptor(self, dst: Tuple[int, int], tag: int) -> bool:
        core = self.cores[dst]
        for op in core.prim_queue:
            if op.recv is not None and op.recv.tag_id == tag:
                return True
        return False

    # -------------------------- Prim IO in memory --------------------------
    def _seed_config_into_memory(self, coord: Tuple[int, int], cfg: CoreConfig) -> None:
        node = self.cores[coord]
        # 1) Write configured prims into memory.
        #    If mem_addr is specified, honor it. Otherwise place sequentially from 0.
        occupied = set()
        for addr, buf in node.mem._cells.items():
            # consider non-zero cells as occupied
            if any(b != 0 for b in buf):
                occupied.add(addr)

        # first pass: explicit addresses
        for op in (cfg.prim_queue or []):
            if op.mem_addr is not None:
                cell_bytes = encode_prim_cell(op)
                node.mem._cells[op.mem_addr] = bytearray(cell_bytes)
                occupied.add(op.mem_addr)

        # second pass: assign addresses for remaining ops sequentially from 0
        next_addr = 0
        for op in (cfg.prim_queue or []):
            if op.mem_addr is None:
                while next_addr in occupied and next_addr < node.mem.num_cells:
                    next_addr += 1
                if next_addr >= node.mem.num_cells:
                    break
                cell_bytes = encode_prim_cell(op)
                node.mem._cells[next_addr] = bytearray(cell_bytes)
                occupied.add(next_addr)
                next_addr += 1
        # 2) For ops with inline send messages, write router table packets into memory at para_addr
        for op in (cfg.prim_queue or []):
            if op.send is not None and op.send.messages:
                packets = [encode_packet_from_fields(m) for m in op.send.messages]
                write_router_table_to_memory(node.mem, op.send.para_addr, packets)

    def _parse_prims_from_memory(self, mem: CoreMemory) -> List[PrimOp]:
        prims: List[PrimOp] = []
        addr = 0
        while addr < mem.num_cells:
            cell = mem.read_cell(addr)
            op = decode_prim_cell(cell)
            if op is None:
                break
            prims.append(op)
            addr += 1
        return prims

    # -------------------------- Simulation --------------------------
    def run(self) -> None:
        """Execute all cores' prim_queue in round-robin order until all empty or stopped."""
        indices = {k: 0 for k in self.cores.keys()}
        stopped = {k: False for k in self.cores.keys()}  # Track stopped cores
        remaining = sum(len(n.prim_queue) for n in self.cores.values())
        while remaining > 0:
            progressed = False
            for coord, node in self.cores.items():
                if stopped[coord]:
                    # Skip cores that have encountered a stop primitive
                    continue
                idx = indices[coord]
                if idx >= len(node.prim_queue):
                    continue
                op = node.prim_queue[idx]
                if op.kind == "stop":
                    # Mark this core as stopped, no further primitives will be executed
                    stopped[coord] = True
                else:
                    # Execute recv first (to post acceptors), then send
                    if op.recv is not None:
                        self._execute_recv(coord, op.recv)
                    if op.send is not None:
                        self._prepare_router_msgs_if_needed(coord, op.send)
                        self._execute_send(coord, op.send)
                indices[coord] += 1
                remaining -= 1
                progressed = True
            if not progressed:
                break

    def _prepare_router_msgs_if_needed(self, src: Tuple[int, int], sp: SendPrim) -> None:
        if sp.messages:
            packets = [encode_packet_from_fields(m) for m in sp.messages]
            write_router_table_to_memory(self.cores[src].mem, sp.para_addr, packets)

    def _execute_send(self, src: Tuple[int, int], sp: SendPrim) -> None:
        src_core = self.cores[src]
        msg_num = sp.normalized_message_num()
        # Parse router table from source memory
        rtes = parse_router_table_from_memory(src_core.mem, sp.para_addr, msg_num)
        # Precompute per-message counts (normalize 0->1)
        msg_counts = [(r.cnt if r.cnt != 0 else 1) for r in rtes]
        # Process each message
        for msg_idx, rte in enumerate(rtes):
            if not rte.en:
                # Skip data consumption as per spec
                continue
            # Resolve destination core (wrap torus-like)
            dst = self._wrap_coord(src_core.y + rte.y, src_core.x + rte.x)
            # Handshake policy: require that dst has a Recv with matching tag to proceed
            if rte.handshake and not self._find_recv_acceptor(dst, rte.tag_id):
                # No acceptor -> buffer at destination until Recv arrives
                self._buffer_send_payload(src_core, dst, sp, rte, msg_idx, msg_counts)
                continue
            if sp.cell_or_neuron == 0:
                self._send_cell_mode(src_core, dst, sp, rte, msg_idx, msg_counts)
            else:
                self._send_neuron_mode(src_core, dst, sp, rte, msg_idx, msg_counts)

    def _buffer_send_payload(self, src_core: CoreNode, dst_coord: Tuple[int, int], sp: SendPrim, rte: RouterTableEntry, msg_idx: int, msg_counts: List[int]) -> None:
        # Materialize payload bytes as if we would send (for simplicity) and stash by tag at destination.
        dst_core = self.cores[dst_coord]
        tag = rte.tag_id
        if tag not in dst_core.pending_by_tag:
            dst_core.pending_by_tag[tag] = []
        if sp.cell_or_neuron == 0:
            # Flatten this message's cells into 4x8B segments in final packet order
            cell_per_message = rte.cnt if rte.cnt != 0 else 1
            data = bytearray()
            src_cell_base = sp.send_addr + sum(msg_counts[:msg_idx])
            for i in range(cell_per_message):
                cell = src_core.mem.read_cell(src_cell_base + i)
                data.extend(cell)  # 32B per cell
            dst_core.pending_by_tag[tag].append((True, rte.__dict__, bytes(data)))
        else:
            neuron_per_message = rte.cnt if rte.cnt != 0 else 1
            prev = sum(msg_counts[:msg_idx])
            start_cell = sp.send_addr + (prev // 32)
            start_off = prev % 32
            data = bytearray()
            for _ in range(neuron_per_message):
                b = src_core.mem.read_bytes_linear(start_cell, start_off, 1)
                data.extend(b)
                start_off += 1
                if start_off == 32:
                    start_off = 0
                    start_cell += 1
            dst_core.pending_by_tag[tag].append((False, rte.__dict__, bytes(data)))

    # -------------------------- Send modes --------------------------
    def _send_cell_mode(self, src_core: CoreNode, dst_coord: Tuple[int, int], sp: SendPrim, rte: RouterTableEntry, msg_idx: int, msg_counts: List[int]) -> None:
        dst_core = self.cores[dst_coord]
        # Number of cells for this message (0 meaning 1)
        cell_per_message = rte.cnt if rte.cnt != 0 else 1
        group_size = rte.group_size
        a = rte.a0  # 8B addressing for cell mode
        # Starting src cell index for this message
        src_cell_base = sp.send_addr + sum(msg_counts[:msg_idx])
        # Iterate per cell
        for i in range(cell_per_message):
            src_cell_addr = src_cell_base + i
            # Build 4x8B segments from source cell
            cell_data = src_core.mem.read_cell(src_cell_addr)
            for seg in range(4):
                data8 = cell_data[seg * 8 : seg * 8 + 8]
                cell_delta, seg_idx = iter_cells_span_from_A_8B(a)
                dst_cell_addr = dst_core_offset_cell(dst_core, sp, rte, cell_delta)
                dst_seg_idx = seg_idx
                dst_core.mem.write_8B(dst_cell_addr, dst_seg_idx, data8)
                a += 1  # next 8B packet increases A by 1 in 8B units
            # After finishing one cell, handle A_offset/Const step
            if ((i + 1) % group_size) == 0:
                # After a group, adjust so that distance (last_8B -> next_first_8B) equals A_offset.
                # Since 'a' is already last+1, we add (A_offset - 1).
                a += (rte.a_offset - 1)

    def _send_neuron_mode(self, src_core: CoreNode, dst_coord: Tuple[int, int], sp: SendPrim, rte: RouterTableEntry, msg_idx: int, msg_counts: List[int]) -> None:
        dst_core = self.cores[dst_coord]
        neuron_per_message = rte.cnt if rte.cnt != 0 else 1
        group_size = rte.group_size
        a = rte.a0  # 1B addressing in neuron mode
        # Neuron stream starts at send_addr cell boundary for first message, then continues across messages
        # Compute byte stream offset from start of send_addr across previous messages
        prev_neurons = sum(msg_counts[:msg_idx])
        # Start reading from send_addr (32B aligned), but with byte offset prev_neurons % 32
        start_cell = sp.send_addr + (prev_neurons // 32)
        start_off = prev_neurons % 32
        remaining = neuron_per_message
        # Consume source bytes and write to destination according to A progression
        while remaining > 0:
            chunk = min(remaining, 1)
            data_byte = src_core.mem.read_bytes_linear(start_cell, start_off, 1)
            byte_val = data_byte[0]
            cell_delta, byte_idx = iter_cells_span_from_A_1B(a)
            dst_cell_addr = dst_core_offset_cell(dst_core, sp, rte, cell_delta)
            dst_core.mem.write_1B(dst_cell_addr, byte_idx, byte_val)
            # Advance source pointer by 1 byte
            start_off += 1
            if start_off == 32:
                start_off = 0
                start_cell += 1
            remaining -= 1
            # A increments by 1 per 1B
            a += 1
            # After finishing a group of group_size neurons, apply A_offset
            sent_count = (neuron_per_message - remaining)
            if (sent_count % group_size) == 0:
                a += (rte.a_offset - 1)

    # -------------------------- Recv --------------------------
    def _execute_recv(self, dst: Tuple[int, int], rp: RecvPrim) -> None:
        # Apply any buffered messages for this tag if exist
        dst_core = self.cores[dst]
        tag = rp.tag_id
        if tag not in dst_core.pending_by_tag:
            return
        pending_list = dst_core.pending_by_tag.pop(tag)
        # As we don't have original RTE fields for A progression per message in buffer,
        # we stored rte.__dict__. Use it to reconstruct minimal fields.
        for is_cell_mode, rte_fields, payload in pending_list:
            rte = RouterTableEntry.from_packet128(encode_packet_from_fields(rte_fields))
            if is_cell_mode:
                # Re-emit write with the same logic as _send_cell_mode but using payload
                a = rte.a0
                group_size = rte.group_size
                # payload is 32B * cells
                for i in range(0, len(payload), 32):
                    cell_bytes = payload[i : i + 32]
                    for seg in range(4):
                        data8 = cell_bytes[seg * 8 : seg * 8 + 8]
                        cell_delta, seg_idx = iter_cells_span_from_A_8B(a)
                        dst_cell_addr = dst_core_offset_cell(dst_core, None, rte, cell_delta)
                        dst_core.mem.write_8B(dst_cell_addr, seg_idx, data8)
                        a += 1
                    sent_cells = (i // 32) + 1
                    if (sent_cells % group_size) == 0:
                        a += (rte.a_offset - 1)
            else:
                a = rte.a0
                group_size = rte.group_size
                for idx, byte_val in enumerate(payload):
                    cell_delta, byte_idx = iter_cells_span_from_A_1B(a)
                    dst_cell_addr = dst_core_offset_cell(dst_core, None, rte, cell_delta)
                    dst_core.mem.write_1B(dst_cell_addr, byte_idx, byte_val)
                    a += 1
                    if ((idx + 1) % group_size) == 0:
                        a += (rte.a_offset - 1)


# -------------------------- Small utilities --------------------------
def dst_core_offset_cell(dst_core: CoreNode, sp: SendPrim, rte: RouterTableEntry, cell_delta: int) -> int:
    # recv base for destination is provided by its Recv(tag) with matching tag; if multiple recv prims for same tag,
    # we choose the first
    recv_base = 0
    for op in dst_core.prim_queue:
        if op.recv is not None and op.recv.tag_id == rte.tag_id:
            recv_base = op.recv.recv_addr
            break
    return recv_base + cell_delta
