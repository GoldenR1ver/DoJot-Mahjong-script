# DoJot 1.0.0 使用流程

## 项目简介

`DoJot` 是一个面向雀魂对局的 AI 脚本项目，支持：

- 使用可导入参数配置控制策略行为
- 自动采集并导出对局统计数据（gameData）
- 通过高斯过程回归（GPR）贝叶斯优化器生成下一组参数
- 人工导入新参数后继续迭代优化
- 使用F12查看具体参数（AI的逻辑还是蛮变态的）

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

----

## 效果展示

### 最有定力的兜牌

因为在金之间训练的，金之间最大的特点就是2位加分非常多，3位扣分非常少，总而言之，只要不是4位，一直打下去都是能上分的。

所以为了不掉到4位，兜牌的权重训练以后变的相当高。

比较有代表性的一把：末巡拒听两次一气通贯

![](Example\noTen1.png)

![](Example\noTen2.png)

看看总牌河

![](Example\allDiscard.png)

这是因为我的防守逻辑是选择一名玩家统计其危险值，在认为某个玩家非常危险的时候相当于根据他的牌河单防他。只会打他打过的现物。

来看看日志：

![](Example\bad3m.png)

日志里面没有3m 5p，认为这都是危险牌/高价值牌，尽可能不要打出去。

太能兜了我天哪，有这个定力做什么都会成功的（

### 非常高牌效的切牌

![](Example\45779-45579.png)

一个简单的例子：45779->45579

确实牌效高，确实如果自己打就会顺手打5m，甚至为了碰牌多一点会打9m，如果那么打后面很不舒服了

![](Example\ron.png)

当然这把奶奶发牌也没有什么影响（

## 一些特殊役种的危险系数很高

比如说大四喜，小四喜，大三元，清一色，混一色，字一色

![](Example\dangerousMeld.png)

上家保底混一色自风场风四番满贯，不能点，放铳的输分期望太高了

兜了好久好久的西风北风，这时候AI已经弃胡了，最后没有点炮也算胜利。

### AI打了4天麻将的结果

用AI收集数据打了4天麻将

![](Example\result2.png)

![](Example\result1.png)

四麻段位从雀杰1星200分到三星1361分，感觉再挂一晚上能上雀豪啊。

事已至此，先发布吧。
