"""
Golden model package for Tianjic Core array send/recv routing at high level.

This package simulates final SRAM contents across an arbitrary-sized
core array given:
- Per-core initial memory image (addr-hex format like inputs.txt)
- Per-core Send/Recv primitive queues
- Per-primitive router table entries (per-message config)

Focus: High-level data movement results (no per-packet timing).
"""

__all__ = [
    "memory",
    "router_table",
    "prims",
    "core",
    "simulator",
]




