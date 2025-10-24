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

## 运行
```bash
python -m golden_model.runner config/sample_config.json --out_dir out_mem
```
- 输出：`out_mem/x_y_mem_config.txt`（`@addr HEX`，全量 dump）。
- 若使用相对路径，请以仓库根为工作目录运行。

## 提示
- 若提供了 `messages`，无需手工在内存写路由表，runner 会按两条/32B 自动落库到 `para_addr`。
- `handshake=true` 时，如目的核尚未在队列中更早位置放置匹配 `Recv(tag)`，本模型会先缓存数据，到 `Recv(tag)` 执行时再落库。
- 目前未实现多播/中继/稀疏压缩实义；需要时可在该基础上扩展。
