# Cursor 项目说明与迁移指南

本文件用于在 Cursor 中快速上手与持续协作，帮助你把仓库迁移到任意位置后，仍能基于当前上下文与约定无缝继续开发。

## 项目概述
- 目标：提供 Tianjic Core 阵列的高层 golden model。输入各核的初始内存、统一顺序队列的 Send/Recv 原语与路由表；输出为路由完成后各核最终的内存镜像（以 32B/Cell 为单位）。
- 范围：关注功能正确性与最终结果，不做时序/信用/死锁等硬件级细节模拟。

## 基本原理（高层语义）
- 两种发送粒度：
  - SendCell：以 8B 为包粒度，1 个 32B cell = 4 个 8B 包；A 字段单位为 8B；`cnt` 为 cell 数。
  - SendNeuron：以 1B 为包粒度；A 字段单位为 1B；`cnt` 为 neuron(字节) 数；第一个 message 从 `send_addr` 对齐的 cell 首字节开始，后续 message 紧接前一 message。
- A 地址生成（A_offset/Const）：连续发送时 A 每包自增 1；每完成一组（组大小=`const_raw+1`，0 视为 1）后，对下一包额外执行 `A += (a_offset - 1)`。
- 写回基址：目的核按 `Recv(tag_id)` 的 `recv_addr` 写回；Cell 模式把 A 的 8B 地址映射为 cell 偏移+段索引，Neuron 模式把 A 的 1B 地址映射为 cell 偏移+字节索引。
- 握手与缓冲：若 message `handshake=true` 且目的核尚未挂载匹配 `Recv(tag)`，则将该 message 的载荷与路由信息暂存于目的核；当后续 `Recv(tag)` 执行时，按 A 规则写入内存。
- 简化：当前不实现多播/中继/稀疏压缩(Q/relay/sparse)真实逻辑，不做依赖/死锁分析。

位宽映射（与 `tb_router_unit_full.sv` 一致）：
- `y,x`：6b 有符号；`a0`：14b；`cnt`：12b；`a_offset`：12b 有符号；`const_raw`：7b；`handshake`：1b；`tag_id`：8b；`en`：1b。

## 目录结构
- `golden_model/memory.py`：32B Cell 内存；8B/1B 掩码写、线性读、镜像读写。
- `golden_model/router_table.py`：128b message 解析/编码；32B(256b) 行拆装；路由表写入/读取。
- `golden_model/prims.py`：`SendPrim`、`RecvPrim` 与统一队列 `PrimOp`/`CoreConfig`；`SendPrim.messages` 支持在执行前自动落表到 `para_addr`（两条/32B）。
- `golden_model/core.py`：`CoreNode`、`NoCSimulator`；轮询执行 per-core `prim_queue`；含握手缓冲。
- `golden_model/simulator.py`：顶层 `run_simulation` 封装。
- `golden_model/runner.py`：命令行入口，读取 JSON，运行并导出各核最终内存。
- `golden_model/examples/sample_config.json`：最小示例配置。

## 使用方法
- 依赖：Python 3.9+。
- 运行：
  ```bash
  python -m golden_model.runner golden_model/examples/sample_config.json --out_dir out_mem
  ```
- 输出：`out_mem/core_Y_X.txt`（`@addr HEX`，每行 32B，完整 dump）。

## JSON 配置要点（统一队列）
- 顶层：`height/width/cores`。
- 每核 `config`：
  - `init_mem_path`：可选，初始内存镜像路径（与 `inputs.txt` 同格式）。
  - `prim_queue`：顺序执行的原语队列：
    - `{ "kind": "send", "send": { ... } }`
    - `{ "kind": "recv", "recv": { ... } }`
- Send 关键字段：
  - `cell_or_neuron`：0=Cell(8B)，1=Neuron(1B)
  - `message_num`：message 数；若提供 `messages`，以其长度为准
  - `send_addr`：源 32B 起始；`para_addr`：路由表起始（每 32B 两条 message）
  - `messages`：可直接填写每条 128b message 的字段（`y/x/a0/cnt/a_offset/const_raw/handshake/tag_id/en/sparse`），runner 在执行前自动写表（当前忽略 `sparse` 语义）
- Recv 关键字段：`recv_addr`、`tag_id`

## 与本对话的变更记录（便于无缝继续）
- 已完成：
  - 合并 Send/Recv 为统一队列 `prim_queue`，轮询执行。
  - `SendPrim.messages` 支持手动配置并自动落表到 `para_addr`。
  - 握手缓冲：`handshake=true` 且目的核未就绪时先缓存，待 `Recv(tag)` 执行再落库。
  - A 地址生成规则（A_offset/Const）在 Cell/Neuron 模式下生效。
- 仍待/可扩展：
  - 多播/中继与路径策略；`Recv.end_num` 更完整校验；稀疏压缩真实语义；单元测试与 CLI 转换工具。

## 迁移与在 Cursor 中继续协作
- 若示例配置中引用的相对路径（如 `Tianjic/design/...`）在新仓库结构下变化，请同步更新。
- 迁移后可直接在 Cursor 中：
  - 描述新的阵列与 `prim_queue`/`messages`，我可生成 JSON 与运行命令。
  - 指定需要修改的规则（如 A 生成/握手语义），我将精确编辑相应文件并验证。
  - 若要与 SV 用例对齐，可贴出关键字段，我会生成等价 JSON 并对齐最终内存。

---
如需我为新仓库初始化同样结构（含 README、示例、runner），请告知新路径与期望示例规模。
