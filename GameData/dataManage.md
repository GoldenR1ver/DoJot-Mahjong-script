一、存储方式
1) 使用 localStorage 持久化保存，key:
   - alphajongGameDataHistory
2) 保存格式:
   - 数组，每个元素是一场大局的快照（结构对齐 gameDataExample.json）
3) 历史上限:
   - 最多保留 200 条，超过后丢弃最旧记录

二、保存时机（确保刷新前落盘）
1) checkForEnd() 检测到结算界面时：
   - 立即构建并保存快照（save_reason: end_screen_autorun）
   - 然后按原逻辑等待 25 秒再 goToLobby()
2) goToLobby() 前兜底：
   - 若尚未保存且处于结算界面，再次执行保存（save_reason: go_to_lobby）
3) 这样可以覆盖：
   - 正常自动刷新
   - 某些异常路径导致的提前刷新

三、局内统计挂载点
1) 听牌统计（tenpai_stats）
   - 在 discard() 中，当当前最优牌效结果 shanten==0 且本巡未记过时计入
2) 立直统计（riichi_stats）
   - 在 callRiichi() 确认立直发送前记一次
3) 弃胡统计（fold_stats）
   - 在 discardFold() 进入 full fold 分支时，按“每小局最多一次”记录
4) 和牌/放铳统计（win_stats / deal_in_stats）
   - 在新小局开始（setData() 内检测 tilesLeft 回增）或终局前，
     对比“本小局起始分”与“当前分”推断分差：
     delta>0 计为赢分，delta<0 计为失分

四、输出结构（与示例字段对齐）
1) metadata
   - game_id / timestamp / room_info / duration_seconds / ai_parameters
2) overall_statistics
   - final_scores / final_ranking / total_rounds
   - tenpai_stats / win_stats / deal_in_stats / riichi_stats / fold_stats / efficiency_stats
3) 已填充统计值
   - 频率、总数、最大最小平均、分布等
4) 当前实现中保留为空或近似的字段
   - win_yaku_details 里的 yaku_list/han/fu（暂无稳定 API 直接取役种明细）
   - deal_in_details.to_player / yaku（暂无稳定 API 精确定位）
   - efficiency_stats（预留为 null）

五、恢复与继续统计
1) 当前策略为“每大局一条完整快照”，刷新后开启下一大局统计
2) 已保存历史始终可从 localStorage 读取，不会因刷新丢失

六、已知限制说明（已在代码中做兼容）
1) 由于麻将魂前端公开对象中，结算细粒度役种信息访问在不同版本可能变化，
   本版先保证“分数与频率类核心统计”稳定可用。
2) 放铳判定采用分差近似法：delta<0 计入 deal_in_stats，
   无法 100% 区分放铳/自摸被炸的细分来源（需更底层结算事件 API 才能精确）。
