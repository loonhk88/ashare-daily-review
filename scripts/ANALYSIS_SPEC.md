# 复盘分析撰写规范（analysis.json）

> 本文件是 DSH 定时任务撰写 `data/YYYY-MM-DD.analysis.json` 的权威规格。
> 目标：产出与已有 10-14 / 10-15 复盘同等质量的第 1/9/10/11 章内容。

## 工作流

```bash
cd /vol1/@appshare/dsh/dsh_home/work/ashare-review

# 1) 采集数据（若定时任务尚未跑）
python3 scripts/trading_calendar.py            # 确认交易日；非交易日直接结束
python3 scripts/collect.py                     # 采集
python3 scripts/collect_em_sector.py <date> --merge data/<date>.json

# 2) 获取分析输入（一次性打印全部关键数据）
python3 scripts/analysis_input.py <date>

# 3) 检索消息面（必须做，用于 news 字段）
#    用 web_search 搜索「<date> A股 收盘 大跌/大涨 原因」「<date> A股 收评」
#    并用 web_fetch 读取 1-2 篇财联社/东方财富的收评全文

# 4) 撰写 data/<date>.analysis.json（本规范）

# 5) 构建
python3 scripts/build.py --all

# 6) 发布 + 推送
bash run_daily.sh <date>        # 或分步执行 api_push.py + notify_feishu.py
```

## 铁律（违反即返工）

1. **绝不编造数字**。所有数值必须能在 `data/<date>.json` 或检索到的新闻中找到出处。
2. **取不到就删**。某字段无数据时，不要填占位符，删除该内容并可在第 12 章说明。
3. **区分事实与判断**。`readings` / `variant` / `playbook` 是分析判断，须明确其为观点。
4. **新闻标注来源**。`news[].source` 必填，且须为真实检索到的媒体名。
5. **连板用「几天几板」口径**（`stat_boards`），不可用 `consec_boards`（可能为 1）。
6. **涨跌停价格字段是 ×1000**（已在采集层处理，勿重复换算）。

## 字段规格

| 字段 | 类型 | 要求 |
|---|---|---|
| `one_line` | str | 一句话复盘，≤60 字，抓最核心矛盾 |
| `index_title` | str | 首页卡片标题，≤24 字 |
| `index_summary` | str | 首页卡片摘要，120-180 字，需含关键数字 |
| `mainlines` | [str] | 2-4 条主线标签 |
| `sentiment_score` | int | 0-100 情绪读数（冰点<20 / 低迷20-40 / 回暖40-60 / 活跃60-80 / 狂热>80） |
| `key_points` | [str] | 4-6 条，每条含 `<b>` 小标题 + 数据支撑 |
| `sentiment_reading` | str | 情绪打分依据，逐项量化 |
| `index_reading` | str | 指数结构 + 技术面（均线/MACD/KDJ/BOLL） |
| `zt_reading` | str | 涨停梯队结构与质量 |
| `dt_reading` | str | 跌停归因与封板质量 |
| `industry_reading` | str | 行业涨跌结构 + 资金 |
| `concept_reading` | str | 概念题材 + 资金 |
| `fund_reading` | str | 个股资金流 + 机构席位 |
| `variant` | str | 变异认知：市场普遍看法 vs 数据说明什么（**核心章节**） |
| `readings` | [{title, body, points[]}] | 3-4 节：最反常现象 / 主线可持续性 / 背离 / 技术面交叉验证 |
| `levels` | [{name, value, note}] | 5-8 个关键价位（压力/支撑） |
| `watch` | [str] | 5-8 条次日观察方向 |
| `playbook` | [str] | 3-4 条：仓位 / 结构 / 回避 / 风险提示 |
| `news` | [{type, title, detail, source}] | 8-14 条；type 为 good/bad/other |
| `caliber` | [str] | 4-8 条口径说明 |
| `sources` | [{item, source, note}] | 8-10 条数据来源 |

## 写作要点

**key_points**：用 `<b>` 起小标题，随后用数据支撑。例：
```html
"<b>普跌加剧，恐慌面显著扩大。</b>全市场 429 涨 / 5108 跌，下跌家数占比高达 91.6%…"
```

**variant（变异认知）**：这是全篇最有价值的部分。结构：
1. 先写「市场普遍看法是……」
2. 再写「但数据说明的是另一件事……」
3. 列 3 条证据
4. 最后写「结论差在哪里」

**readings**：每节 `title` 用编号开头（如「1. 当日最反常的现象：…」），
`points` 每条先给论点再给数据。

**levels**：从技术指标取（MA5/10/20/60、BOLL 上下轨、当日最高最低、整数关口）。

**news**：必须来自真实检索。至少包含：
- 当日下跌/上涨的**外部原因**（外围市场、政策、数据）
- 领涨板块的**催化事件**
- 领跌板块的**原因**
- 盘面异动（ETF 放量、重要个股）

## 校验

写完后运行：
```bash
python3 -c "import json;json.load(open('data/<date>.analysis.json'))"   # JSON 合法性
python3 scripts/build.py --all                                          # 构建成功
# 检查页面无 undefined/NaN、12 章齐全
```

## 参考样例

- `data/2026-10-14.analysis.json` — 大跌日（外围芯片利空）
- `data/2026-10-15.analysis.json` — 普跌日（全球共振杀跌）
