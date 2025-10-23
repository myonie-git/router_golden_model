#!/usr/bin/env python3
"""
快速查看内存文件中指定地址的值
用法: 
  python3 view_mem.py <文件路径> <地址>
  python3 view_mem.py out_mem/core_0_0.txt 0
  python3 view_mem.py out_mem/core_0_0.txt 0x10
  python3 view_mem.py out_mem/core_0_0.txt 0-5  # 查看地址范围
"""

import sys
import re

def parse_addr(addr_str):
    """解析地址字符串，支持十进制、十六进制和范围"""
    if '-' in addr_str:
        # 范围查询
        start, end = addr_str.split('-')
        start = int(start, 0)  # 自动识别进制
        end = int(end, 0)
        return list(range(start, end + 1))
    else:
        # 单个地址
        return [int(addr_str, 0)]

def view_memory(filepath, addresses):
    """查看内存文件中指定地址的值"""
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    print(f"{'地址':<8} {'十六进制值':<66} {'十进制值':<20}")
    print("-" * 95)
    
    for addr in addresses:
        if addr < len(lines):
            line = lines[addr].strip()
            match = re.match(r'@([0-9a-fA-F]+)\s+([0-9a-fA-F]+)', line)
            if match:
                addr_hex = match.group(1)
                value_hex = match.group(2)
                value_dec = int(value_hex, 16)
                print(f"@{addr_hex:<6} {value_hex:<64} {value_dec}")
            else:
                print(f"地址 {addr}: 格式错误")
        else:
            print(f"地址 {addr}: 超出范围（文件只有 {len(lines)} 行）")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        print("\n示例:")
        print("  python3 view_mem.py out_mem/core_0_0.txt 0")
        print("  python3 view_mem.py out_mem/core_0_0.txt 0x10")
        print("  python3 view_mem.py out_mem/core_0_0.txt 0-5")
        sys.exit(1)
    
    filepath = sys.argv[1]
    addr_str = sys.argv[2]
    
    try:
        addresses = parse_addr(addr_str)
        view_memory(filepath, addresses)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

