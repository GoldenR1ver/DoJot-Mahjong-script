# DoJot 1.0.0 使用流程

## 项目简介

`DoJot` 是一个面向雀魂对局的 AI 脚本项目，支持：

- 使用可导入参数配置控制策略行为
- 自动采集并导出对局统计数据（gameData）
- 通过高斯过程回归（GPR）贝叶斯优化器生成下一组参数
- 人工导入新参数后继续迭代优化

---

## 目录说明

- `DoJot_1.0.0.user.js`：主脚本（Tampermonkey/Greasemonkey）
- `Parameter/defaultParameter.importable.json`：参数导入模板
- `Parameter/defaultParameter.json`：参数边界和类型定义
- `GameData/`：导出的对局数据
- `Optimizer/BayesianOptimizer.py`：离线贝叶斯优化器
- `Optimizer/suggestedParameter.importable.json`：优化器输出的新参数

---

## 环境准备

1. 浏览器安装用户脚本插件（如 Tampermonkey）
2. 安装 Python 3.9+（建议 3.10/3.11）
3. 安装依赖包：

```bash
pip install numpy scipy scikit-learn
```

---

## 日常使用流程（推荐）

1. **加载脚本**
   - 将 `DoJot_1.0.0.user.js` 导入用户脚本管理器并启用

2. **导入参数**
   - 在脚本界面导入 `Parameter/defaultParameter.importable.json`
   - 或导入上一次优化输出的参数文件

3. **运行对局并收集数据**
   - 正常自动对局
   - 脚本会持续记录每场大局统计（本地存储）

4. **导出 gameData**
   - 导出到 `GameData/` 目录（示例：`gameData_YYYYMMDDHHmmss.json`）

5. **运行优化器**

```bash
python Optimizer/BayesianOptimizer.py --game-data GameData/gameData_你的时间戳.json
```

6. **获取新参数**
   - 生成文件：`Optimizer/suggestedParameter.importable.json`
   - 在脚本中手动导入该文件继续下一轮对局

7. **循环迭代**
   - 重复“对局 -> 导出 -> 优化 -> 导入”流程

---

## BayesianOptimizer 常用参数

```bash
python Optimizer/BayesianOptimizer.py ^
  --game-data GameData/gameData_20260324135920.json ^
  --param-spec Parameter/defaultParameter.json ^
  --template Parameter/defaultParameter.importable.json ^
  --out Optimizer/suggestedParameter.importable.json ^
  --seed 42 ^
  --candidates 4000
```

- `--game-data`：导出的历史对局数据
- `--param-spec`：参数类型/边界定义
- `--template`：输出参数模板
- `--out`：输出参数文件
- `--seed`：随机种子
- `--candidates`：EI 候选点数量（越大越慢，通常越稳）

---

## 调优建议

- 先固定参数跑 20+ 局再做一次优化，噪声更小
- 每次只替换一份建议参数，避免多变量来源混杂
- 若行为波动过大，可降低迭代频率并扩大样本数
- 记录每轮参数文件和 gameData，便于回滚与对照

---

## 故障排查

- **优化器提示样本不足**
  - 检查 `gameData` 是否包含 `records[].metadata.ai_parameters`
- **导入参数后无变化**
  - 检查是否导入了 `importable` 结构 JSON
- **脚本刷新后数据丢失**
  - 检查浏览器是否清理了 `localStorage`

---

## 版本信息

- 项目名：`DoJot`
- 项目版本：`1.0.0`
