# Benchmark 无效局自动重排设计

- 日期：2026-09-05
- 状态：已确认
- 范围：`benchmark_runner.py` 的单模型运行、断点恢复和命令行参数

## 目标

每个模型仍以 12 道固定题、每题 3 个固定槽位为目标，共需 36 个有效局。评分发现无效局后，runner 自动归档对应 trial，并重新执行同一题目的同一槽位。单模型累计最多执行 100 个 trial；达到 36 个有效局或累计尝试达到 100 次时结束。

## 尝试次数语义

- 上限按模型独立计算。
- 首轮 trial 计入累计尝试次数。
- 主持、玩家、基础设施或 judge 判定造成的所有无效局均计入。
- 已启动的 trial 即计为一次尝试；进程中断后该次数不会返还。
- 每轮只启动剩余额度允许的数量。例如已累计 96 次且仍有 8 个无效槽位，只启动 4 个。
- 默认上限为 100，可通过 `--max-attempts-per-player` 修改；参数必须不小于目标有效局数 36。

## 数据布局

每个模型新增 `attempts.json`，至少记录：

- `player_slug`
- `target_valid_games`
- `max_attempts`
- `attempts_started`
- `retry_round`
- `updated_at`

状态文件使用现有原子 JSON 写入。首次在旧 run 上启用时，从当前 canonical trial、旧式 `trial-XX-retry-*` 目录和 `retry-archives` 中已有 trial 恢复物理尝试数；记录值与物理计数取较大值，防止重启后重复获得额度。

自动归档路径为：

`retry-archives/auto/<player-slug>/round-XXX/games/<player-slug>/<puzzle-id>/trial-XX/`

归档保留 `game.json`、日志、preliminary、score 和其他 trial 文件。对应题目的旧 `judge.json` 会一并归档或失效，保证新 trial 会重新评分。最终 summary 仅保留当前 36 个 canonical 槽位的结果。

## 运行流程

1. 加载或恢复该模型的尝试状态。
2. 为尚未存在的 canonical 槽位预留尝试额度，原子更新 `attempts_started` 后启动。
3. 等待本轮对局结束。
4. 对包含新 trial 的题目执行 judge，生成全部 canonical score。
5. 统计有效与无效槽位。
6. 有效局达到 36：生成 summary 并结束。
7. 仍有无效局且尚有额度：归档无效 trial，增加 `retry_round`，按剩余额度重新排队。
8. 累计达到上限：停止归档和重试，以当前 canonical 结果生成 summary，并记录 `attempt_limit_reached: true`。

每轮保留有效 trial，不重复运行。多个模型继续按既有顺序执行；单模型内部沿用 `--concurrency` 并发限制。

## 断点恢复

- canonical trial 已终局但尚未评分：继续 judge。
- canonical trial 处于非终局：沿用现有 resume 语义继续该槽位，不额外增加尝试次数。
- 无效 score 尚未归档：恢复后进入下一次自动归档。
- 归档完成但新 trial 尚未启动：根据 `attempts.json` 和物理目录恢复，不突破上限。
- 状态文件缺失：扫描物理目录初始化累计次数。

## 错误处理

- `max_attempts < 36`：启动前报错。
- 归档目标冲突：停止该模型并报错，不覆盖历史记录。
- judge 连续失败：保持现有三次 judge 重试；仍失败时停止该模型，避免把 judge 故障批量消耗成玩家 trial。
- 达到 100 次仍不足 36 个有效局：正常生成部分 summary，并明确记录尝试上限状态。

## 测试

新增或调整自动化测试，覆盖：

- 首轮全部有效时只运行 36 次。
- 部分无效时归档并只重跑无效槽位。
- 96 次后只允许再启动 4 局。
- 100 次后停止重试并生成部分 summary。
- 有效局达到 36 后立即停止。
- 旧 run 缺少状态文件时可从物理目录恢复次数。
- 重启不会重复获得尝试额度。
- 参数小于 36 时拒绝运行。
- 归档保留有效 trial，并使对应题目重新 judge。

仓库版与 `situation-puzzle` 技能版 runner 必须保持相同行为，并分别运行完整测试。
