# Golden Model (Python) for Tianjic Core Array

高层 golden model：给定任意规模 Core 阵列、每核初始内存与 Send/Recv 原语序列，模拟路由完成后的“最终内存内容”（以 32B/Cell 为单位），不做时序级包级仿真。

## 功能
- 解析/导出内存镜像（`@addr HEX`，每行 32B）。
- 解析/生成路由表：每 32B 行包含两个 128b Message 配置。
- Send 模式：SendCell(8B 粒度)/SendNeuron(1B 粒度)。
- 地址生成：支持 `A_offset`/`Const`（Cell 下 A 以 8B 为单位，Neuron 下 A 以 1B 为单位）。
- tag 匹配：根据目的核 `Recv(tag_id)` 的 `recv_addr` 写回。
- 握手与缓冲：`handshake=true` 且目的核尚未有匹配 `Recv(tag)` 时，先缓存，待该 `Recv` 执行时再落库。

暂不支持/简化：多播、中继、依赖死锁分析、稀疏编码（`sparse` 字段占位但当前忽略）、Q/relay 路由策略细节。

## 目录
- `memory.py`：32B Cell 内存，支持 8B/1B 写、线性读、镜像读写。
- `router_table.py`：128b Message 解析/编码、256b(32B) 行拆装、路由表落库。
- `prims.py`：`SendPrim`/`RecvPrim` 与统一队列 `PrimOp`/`CoreConfig`。
- `core.py`：`CoreNode`、`NoCSimulator`，轮询执行 prim 队列，含握手缓冲逻辑。
- `simulator.py`：顶层封装 `run_simulation`。
- `runner.py`：命令行入口（读取 JSON，运行并导出结果）。
- `config/sample_config.json`：示例配置。

## 配置（JSON）
顶层：
```json
{
  "height": 1,
  "width": 2,
  "cores": [ { "y": 0, "x": 0, "config": { ... } } ]
}
```
每核 `config`：
- `init_mem_path`：可选，初始内存镜像路径。
- `prim_queue`：统一原语队列，顺序执行。
  - `{"kind":"send", "send": { ... }} | {"kind":"recv", "recv": { ... }}`

Send 原语：
- `cell_or_neuron`: 0=Cell(8B)，1=Neuron(1B)
- `message_num`: Message 数（0 视作 1）。若同时提供 `messages`，以 `messages` 长度为准。
- `send_addr`: 源 32B 起始地址。
- `para_addr`: 路由表基地址（每 32B 两条 message）。
- `messages`: 可选，直接在 JSON 中填写每条 128b message 的字段，runner 会在执行前写入 `para_addr`：

Recv 原语：
- `recv_addr`：目的 32B 起始地址
- `tag_id`：本次接收的标签
- 其余字段（`end_num/relay_mode/mc_x/mc_y`）占位，当前忽略

### A_offset/Const 规则
- 连续发送时，A 每个包自增 1。
- 每完成一组（组大小=`const_raw+1`，0 视作 1）后，对“下一包”额外执行 `A += (a_offset - 1)`。
  - 例：`const_raw=0, a_offset=1` → 紧凑写入（连续）。
  - 例：`const_raw=0, a_offset=5` → 每包（或每 Cell）之后空 4 个 A 单位（Cell 模式约等于隔一个 32B 行）。

## 运行
```bash
python -m golden_model.runner config/sample_config.json --out_dir out_mem
```
- 输出：`out_mem/core_Y_X.txt`（`@addr HEX`，全量 dump）。
- 若使用相对路径，请以仓库根为工作目录运行。

## 提示
- 若提供了 `messages`，无需手工在内存写路由表，runner 会按两条/32B 自动落库到 `para_addr`。
- `handshake=true` 时，如目的核尚未在队列中更早位置放置匹配 `Recv(tag)`，本模型会先缓存数据，到 `Recv(tag)` 执行时再落库。
- 目前未实现多播/中继/稀疏压缩实义；需要时可在该基础上扩展。
