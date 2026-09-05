# Benchmark Invalid Trial Auto-Requeue Implementation Plan

**Goal:** 让每个模型自动重跑无效 trial，累计尝试达到 100 次后停止。

**Architecture:** 在现有固定 36 槽位模型上增加持久化尝试状态。`run_player` 每轮运行缺失槽位、评分、保留有效槽位并归档无效槽位，直至 36 个有效局或额度耗尽。

**Tech Stack:** Python 3.11、`asyncio`、`unittest`、原子 JSON 文件。

---

### Task 1: 尝试额度与状态恢复

**Files:**
- Modify: `src/turtlebench/benchmark_runner.py`
- Test: `tests/test_benchmark_runner.py`

1. 先写失败测试，覆盖物理目录计数、记录值取较大值、96 次仅分配 4 次。
2. 运行聚焦测试确认失败。
3. 实现状态加载、物理尝试扫描和本轮槽位规划。
4. 运行聚焦测试确认通过。

### Task 2: 自动归档与重排循环

**Files:**
- Modify: `src/turtlebench/benchmark_runner.py`
- Test: `tests/test_benchmark_runner.py`

1. 先写异步失败测试，模拟首轮部分无效并验证只重跑无效槽位。
2. 实现自动归档、judge 失效和循环终止条件。
3. 增加达到 100 次后生成部分 summary 的测试。
4. 运行 benchmark runner 测试。

### Task 3: CLI、技能同步与完整验证

**Files:**
- Modify: `src/turtlebench/benchmark_runner.py`
- Modify: `tests/test_benchmark_runner.py`
- Modify: `~/.hermes/skills/entertainment/situation-puzzle/scripts/benchmark_runner.py`
- Modify: `~/.hermes/skills/entertainment/situation-puzzle/scripts/test_benchmark_runner.py`

1. 增加 `--max-attempts-per-player`，默认 100，小于 36 时拒绝。
2. 同步仓库实现到技能脚本。
3. 分别运行仓库和技能完整测试。
4. 提交并推送功能分支，快进合并到 `main`。
