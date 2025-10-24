from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class Field:
    name: str
    start: int   # LSB-first bit index
    width: int   # 位宽(比特数)，不是结束位

# ===== 修正后的字段定义（位宽都写成"多少位"）=====
# 约定：LSB 是 bit0（最右边的十六进制最低位）

# 第一种数据格式的字段定义 send_prim
FIELDS_TYPE1: List[Field] = [
    Field("op_low_nibble",    0,  4),   # 0x6
    Field("op_high_nibble",   4,  4),   # 0x0  -> 组合见下方 SendRecv_AB/BA
    Field("deps",             8, 16),   # 16 位
    Field("Send_Tag",        4,  1),   # 1 位
    Field("Recv_Tag",        5,  1),   # 1 位
    Field("recv_addr",       32, 16),   # 16 位
    Field("send_addr",       48, 16),   # 16 位
    # 下面这些位宽/起始位按你的图继续放，这里给成 1/若干位的“示例值”
    Field("cell_or_neuron", 168,  1),
    Field("CXY",            172,  3),   # 若是 2 位就写成 2
    Field("pack_head_num",  176,  8),
    Field("mc_y",           184,  6),
    Field("mc_x",           192,  6),
    Field("tag_id",         200,  8),
    Field("end_num",        208,  8),
    Field("router_table_addr", 240, 16),  # 高 16 位（如果不是 16 位，请改成实际位宽）
]

# 第二种数据格式的字段定义 Msg
# 字段顺序：S T E Q LVDS(Empty) Y X A0 cell/pack_per_Rhead A_offset Const handshake tag_id en Rsv
# 位宽：    1 1 1 1 2           6 6 14 12               12       7     1         8      1  183
FIELDS_TYPE2: List[Field] = [
    Field("S",                  0,   1),   # 1 位
    Field("T",                  1,   1),   # 1 位
    Field("E",                  2,   1),   # 1 位
    Field("Q",                  3,   1),   # 1 位
    Field("LVDS_Empty",         4,   2),   # 2 位
    Field("Y",                  6,   6),   # 6 位
    Field("X",                 12,   6),   # 6 位
    Field("A0",                18,  14),   # 14 位
    Field("cell_pack_per_Rhead", 32, 12),  # 12 位
    Field("A_offset",          44,  12),   # 12 位
    Field("Const",             56,   7),   # 7 位
    Field("handshake",         63,   1),   # 1 位
    Field("tag_id",            64,   8),   # 8 位
    Field("en",                72,   1),   # 1 位
    Field("send_addr",         73,   1),   # 16 位
    Field("Rsv",               74, 53),   # 53 位（保留位）
]

FIELDS_TYPE3: List[Field] = [
    Field("S",                  0,   1),   # 1 位
    Field("T",                  1,   1),   # 1 位
    Field("E",                  2,   1),   # 1 位
    Field("Q",                  3,   1),   # 1 位
    Field("LVDS_Empty",         4,   2),   # 2 位
    Field("Y",                  6,   6),   # 6 位
    Field("X",                 12,   6),   # 6 位
    Field("Addr",                18,  14),   # 14 位
    Field("Data",                32, 64),  # 12 位
]

FIELDS_PACKET_HEADER: List[Field] = [
    Field("S",      0,  1),   # 数据/特殊包标识
    Field("T",      1,  1),   # 类型标识
    Field("E",      2,  1),   # 结束包标识
    Field("Q",      3,  1),   # 中继/多播标识
    Field("LVDS",   4,  2),   # LVDS接口标识
    Field("dY",     6,  6),   # 目的核竖直距离
    Field("dX",    12,  6),   # 目的核水平距离
    Field("Addr",  18, 14),   # 地址
]

FIELDS_PACKET_REQ: List[Field] = [
    Field("tag_id",   0,  8),   # 标签ID
    Field("Y",        10,  6),   # Y坐标
    Field("X",       18,  6),   # X坐标
    Field("Rsv",     24, 40),   # 保留位
]

FIELDS_PACKET_1B: List[Field] = [
    Field("Mask",     0,  4),   
    # Field("Data0   Pos  ",   4, 5), 
    Field("Value0",   4, 8),  
    Field("Pos1",   12, 5), 
    Field("Value1", 17, 8),   
    Field("Pos2",   25, 5), 
    Field("Value2", 30, 8),   
    Field("Pos3",   38, 5), 
    Field("Value3", 43, 8),   
    Field("Pos4",   51, 5),  
    Field("Value4", 56, 8),   
]

FIELDS_PACKET_8B: List[Field] = [
    Field("Data",     0,  64)
]



def parse_packet_format(hex24: str) -> Dict[str, Any]:
    """解析第四种数据格式 (新数据包格式) - 32位包头 + 64位数据 = 96位"""
    s = hex24.strip().lower().replace("0x", "")
    if len(s) != 24:
        raise ValueError(f"需要 24 个十六进制字符（96 bit），当前为 {len(s)} 个。")
    u = int(s, 16)

    # 解析包头（前32位）
    header: Dict[str, int] = {}
    for f in FIELDS_PACKET_HEADER:
        header[f.name] = _bits(u, f.start, f.width)

    # 解析数据部分（后64位）
    data_value = _bits(u, 32, 64)

    # 根据包类型确定数据含义
    packet_type = ""
    data_fields: Dict[str, any] = {}

    S = header["S"]
    T = header["T"]
    E = header["E"]

    if S == 0:
        # 数据包
        if T == 0:
            packet_type = "1B数据包"
            # 1字节数据，前4位掩码，后60位存储5个12位值
            data_dict = {}
            for f in FIELDS_PACKET_1B:
                data_dict[f.name] = _bits(data_value, f.start, f.width)

            data_fields["Mask"] = data_dict["Mask"]
            data_fields["Pos"] = [
                data_dict["Pos1"], data_dict["Pos2"], data_dict["Pos3"], data_dict["Pos4"]
            ]
            data_fields["Values"] = [
                data_dict["Value0"], data_dict["Value1"], data_dict["Value2"],
                data_dict["Value3"], data_dict["Value4"]
            ]
            # 找出有效的值（掩码位为1的对应值）
            data_fields["Valid_Values"] = [
                data_fields["Values"][i] for i in range(5)
                if (data_fields["Mask"] & (1 << i)) != 0
            ]
        else:
            packet_type = "8B数据包"
            # 8字节数据，64位直接存储
            data_fields["Data_8B"] = f"0x{data_value:016X}"
            
    else:
        # 特殊包
        if T == 0:
            # 握手包
            if E == 0:
                packet_type = "握手请求包"
                # 数据包含 tag_id(8)+Y(8)+X(8)+Rsv(40)
                handshake_data = {}
                for f in FIELDS_PACKET_REQ:
                    handshake_data[f.name] = _bits(data_value, f.start, f.width)

                data_fields.update(handshake_data)
            else:
                packet_type = "握手应答包"
                data_fields["Data"] = "空"
        else:
            packet_type = "中断配置包"
            data_fields["Data"] = f"0x{data_value:016X}"

    # 组合结果
    result = {
        "packet_type": packet_type,
        "header": header,
        "data": data_fields
    }

    return result


def _bits(u: int, start: int, width: int) -> int:
    return (u >> start) & ((1 << width) - 1)

def parse_instruction_type1(hex64: str) -> Dict[str, int]:
    """解析第一种数据格式（原有格式）"""
    s = hex64.strip().lower().replace("0x", "")
    if len(s) != 64:
        raise ValueError(f"需要 64 个十六进制字符（256 bit），当前为 {len(s)} 个。")
    u = int(s, 16)

    out: Dict[str, int] = {}
    for f in FIELDS_TYPE1:
        out[f.name] = _bits(u, f.start, f.width)

    # 两种半字节组合方式都给出，方便核对（AB=高<<4|低；BA=低<<4|高）
    out["SendRecv_AB"] = (out["op_high_nibble"] << 4) | out["op_low_nibble"]
    out["SendRecv_BA"] = (out["op_low_nibble"]  << 4) | out["op_high_nibble"]
    return out

def parse_instruction_type2(hex64: str) -> Dict[str, int]:
    """解析第二种数据格式"""
    s = hex64.strip().lower().replace("0x", "")
    if len(s) != 64:
        raise ValueError(f"需要 64 个十六进制字符（256 bit），当前为 {len(s)} 个。")
    u = int(s, 16)

    out: Dict[str, int] = {}
    for f in FIELDS_TYPE2:
        out[f.name] = _bits(u, f.start, f.width)

    # 有符号修正：A0(14位) 和 A_offset(12位)
    if "A0" in out:
        out["A0"] = _to_signed_generic(out["A0"], 14)
    if "A_offset" in out:
        out["A_offset"] = _to_signed_generic(out["A_offset"], 12)

    return out

def parse_instruction_type3(hex64: str) -> Dict[str, int]:
    """解析第三种数据格式"""
    s = hex64.strip().lower().replace("0x", "")
    if len(s) != 24:
        raise ValueError(f"需要 12 个十六进制字符（256 bit），当前为 {len(s)} 个。")
    u = int(s, 16)

    out: Dict[str, int] = {}
    for f in FIELDS_TYPE3:
        out[f.name] = _bits(u, f.start, f.width)

    return out

def pretty_print_type1(parsed: Dict[str, int]) -> None:
    """打印第一种数据格式的解析结果"""
    order = [f.name for f in FIELDS_TYPE1]
    for k in order:
        v = parsed.get(k, 0)
        print(f"{k:20s}: 0x{v:X} ({v})")

def _parse_msg128_from_int(u128: int) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for f in FIELDS_TYPE2:
        out[f.name] = _bits(u128, f.start, f.width)
    # 有符号修正：A0(14位) 和 A_offset(12位)
    if "A0" in out:
        out["A0"] = _to_signed_generic(out["A0"], 14)
    if "A_offset" in out:
        out["A_offset"] = _to_signed_generic(out["A_offset"], 12)
    return out

def _pretty_print_type2_dict(parsed: Dict[str, int]) -> None:
    order = [f.name for f in FIELDS_TYPE2]
    for k in order:
        v = parsed.get(k, 0)
        if k == "A0":
            u = _unsigned_of_signed(v, 14)
            print(f"{k:25s}: 0x{u:X} ({v})")
        elif k == "A_offset":
            u = _unsigned_of_signed(v, 12)
            print(f"{k:25s}: 0x{u:X} ({v})")
        else:
            print(f"{k:25s}: 0x{v:X} ({v})")

def pretty_print_type2(data: Any) -> None:
    """打印第二种数据格式的解析结果

    兼容两种输入：
    - dict: 直接打印已解析的 Msg 字段（与旧行为一致）
    - hex str: 支持 128 位(32 hex) 或 256 位(64 hex)。当为 256 位时，分别解析并打印低/高 128 位
    """
    # 旧行为：传入 dict
    if isinstance(data, dict):
        _pretty_print_type2_dict(data)
        return

    # 新增：传入十六进制字符串
    if isinstance(data, (str, bytes)):
        s = str(data).strip().lower().replace("0x", "")

        if len(s) == 32:
            # 单个 128 位 Msg
            u128 = int(s, 16)
            parsed = _parse_msg128_from_int(u128)
            _pretty_print_type2_dict(parsed)
            return

        if len(s) == 64:
            # 256 位输入：拆为低/高 128 位分别解析
            u256 = int(s, 16)
            low128 = u256 & ((1 << 128) - 1)
            high128 = u256 >> 128

            print("=== 低128位 Msg ===")
            parsed_low = _parse_msg128_from_int(low128)
            _pretty_print_type2_dict(parsed_low)

            print("=== 高128位 Msg ===")
            parsed_high = _parse_msg128_from_int(high128)
            _pretty_print_type2_dict(parsed_high)
            return

        raise ValueError("Msg 输入长度应为 32 或 64 个十六进制字符（128/256 bit）")

    raise TypeError("pretty_print_type2 需要 dict 或 128/256 位十六进制字符串")

def pretty_print_type3(parsed: Dict[str, int]) -> None:
    """打印第三种数据格式的解析结果"""
    order = [f.name for f in FIELDS_TYPE3]
    for k in order:
        v = parsed.get(k, 0)
        print(f"{k:25s}: 0x{v:X} ({v})")

def _to_signed_8bit(value: int) -> int:
    """将8位无符号数转换为有符号数"""
    if value >= 128:  # 如果最高位为1，表示负数
        return value - 256  # 2^8 = 256
    return value

def _to_signed_6bit(value: int) -> int:
    """将6位无符号数转换为有符号数"""
    if value >= 32:  # 如果最高位为1，表示负数
        return value - 64  # 2^6 = 64
    return value

def _to_signed_generic(value: int, width: int) -> int:
    """将任意位宽的无符号数转换为有符号值"""
    mask = (1 << width) - 1
    value &= mask
    sign_bit = 1 << (width - 1)
    if value & sign_bit:
        return value - (1 << width)
    return value

def _unsigned_of_signed(value: int, width: int) -> int:
    """获取有符号值在给定位宽下的无符号表示（位模式）"""
    mask = (1 << width) - 1
    return value & mask

def pretty_print_packet(parsed: Dict[str, Any]) -> None:
    """打印第四种数据格式 (新数据包格式) 的解析结果"""
    packet_type = parsed.get("packet_type", "未知包类型")
    header = parsed.get("header", {})
    data = parsed.get("data", {})

    print(f"包类型: {packet_type}")
    print("=" * 50)

    # 打印包头信息
    print("包头字段:")
    field_order = ["S", "T", "E", "Q", "LVDS", "dY", "dX", "Addr"]
    for field_name in field_order:
        value = header.get(field_name, 0)
        if field_name == "S":
            desc = "数据/特殊包标识 (0=数据包, 1=特殊包)"
        elif field_name == "T":
            desc = "类型标识"
        elif field_name == "E":
            desc = "结束包标识"
        elif field_name == "Q":
            desc = "中继/多播标识"
        elif field_name == "LVDS":
            desc = "LVDS接口标识"
        elif field_name == "dY":
            desc = "目的核竖直距离"
        elif field_name == "dX":
            desc = "目的核水平距离"
        elif field_name == "Addr":
            desc = "地址"
        # 对dX和dY字段显示有符号数
        if field_name in ["dX", "dY"]:
            signed_value = _to_signed_6bit(value)
            print(f"  {field_name:8s}: 0x{value:X} ({signed_value}) - {desc}")
        else:
            print(f"  {field_name:8s}: 0x{value:X} ({value}) - {desc}")


    print("\n数据字段:")
    if packet_type == "单neuron数据包":
        data_8b = data.get("Data_8B", "无数据")
        print(f"  8B数据: {data_8b}")
    elif packet_type == "1B数据包":
        mask = data.get("Mask", 0)
        values = data.get("Values", [])
        poses = data.get("Pos", [])
        valid_values = data.get("Valid_Values", [])
        print(f"  掩码: 0x{mask:X} ({mask})")
        print(f"  五个值: {[f'0x{v:X}' for v in values]}")
        print(f"  有效值: {[f'0x{v:X}' for v in valid_values]}")
        print(f"  Pos: {[f'0x{v:X}' for v in poses]}")
    elif packet_type == "握手请求包":
        for field_name in ["tag_id", "Y", "X", "Rsv"]:
            value = data.get(field_name, 0)
            if field_name == "tag_id":
                desc = "标签ID"
            elif field_name == "Y":
                desc = "Y坐标"
            elif field_name == "X":
                desc = "X坐标"
            elif field_name == "Rsv":
                desc = "保留位"
            if field_name in ["Y", "X"]:
                signed_value = _to_signed_6bit(value)
                print(f"  {field_name:8s}: 0x{value:X} ({signed_value}) - {desc}")
            else:
                print(f"  {field_name:8s}: 0x{value:X} ({value}) - {desc}")
    elif packet_type == "握手应答包":
        print("  数据: 空")
    elif packet_type == "中断配置包":
        data_hex = data.get("Data", "无数据")
        print(f"  数据: {data_hex}")

    print("=" * 50)



# 保持向后兼容性的别名
pretty_print = pretty_print_type1

if __name__ == "__main__":
    # 测试第一种数据格式
    print("=== Send Prim ===")
    s1 = "1100000000000000000100000000000000000000000000001000000000000016"
    res1 = parse_instruction_type1(s1)
    pretty_print_type1(res1)
    
    print("=== Recv Prim ===")
    s1 = "0000000000040a00000000000000000000000000000000000000200000000026"
    res1 = parse_instruction_type1(s1)
    pretty_print_type1(res1)


    # print("=== Msg===")
    # s1 = "000000000000010d00ff900400801000000000000000010c0000500400001000"
    # pretty_print_type2(s1)
    
    # print("\n=== Packet ===")
    # # # 示例数据（你可以替换为实际的256位十六进制数据）
    # # # s2 = "0xdeadbef71234568040202131"
    # # s2 = "0x0000000000fc002200001001"
    # s2 = "0x000000000000020100080000"
    # res2 = parse_packet_format(s2)
    # pretty_print_packet(res2)
