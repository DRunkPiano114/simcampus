# 中国高中班级模拟 — 项目计划

## 项目定位

用 Multi-Agent 模拟一个中国高中班级的日常生活。每个 Agent 代表一个真实的人（学生/老师），通过自然互动产生涌现剧情。纯观察式，无用户干预，文本输出。

最终目标：模拟完整的高中三年，产出可以剪辑成视频的叙事内容。

---

## 核心决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 框架 | 自建 | 场景结构化、规模有限（50人），框架的通用抽象反而是阻力 |
| 记忆系统 | 自建，JSON + Markdown | 结构化数据（profile/relationships/state）用 JSON + Pydantic；叙事内容（记忆/总结）用 Markdown |
| 交互编排 | 自建 | 场景固定（教室/食堂/宿舍），交互规则明确，不需要通用编排框架 |
| 对话生成 | 每人独立 LLM 调用（预注入基线） | 保证角色独立性；基线信息不依赖 LLM 判断；Phase 2 加入 recall 工具实现深层回忆涌现 |
| 时间模型 | 场景制（非 tick 制） | 剧情是事件驱动的，不是时间均匀分布的 |
| 存储 | 文件系统（JSON + Markdown） | 8-10 人规模完全够用，全部可读，方便 debug |
| LLM | DeepSeek V3.2 | 便宜、中文能力强，调用次数可以多，保证剧情丰富 |
| 语言 | Python | 原型快，LLM 生态好 |
| 前端 | 不做（第一阶段） | 先跑通核心模拟，视觉呈现后期再说 |

---

## 架构四层

```
┌──────────────────────────────────────┐
│  Narrative Layer                     │  每天生成可读的故事日志
├──────────────────────────────────────┤
│  Interaction Layer                   │  场景模拟：对话、事件、因果链
├──────────────────────────────────────┤
│  Agent Layer                         │  每个人的人格/记忆/关系/情绪/目标
├──────────────────────────────────────┤
│  World Layer                         │  课表、地点、事件系统、规则引擎
└──────────────────────────────────────┘
```

---

## World Layer

### 场景制时间系统

一天由一系列**场景（Scene）**组成，由课表自动生成，但分辨率不固定：

- **高密度场景**（课间、午饭、课外活动、宿舍夜聊）：多轮对话，允许事件连锁，max_rounds 按场景类型设定
- **高密度（轻量）场景**（早操/早餐等过渡场景）：max_rounds 5-8，分组更随机，以简单闲聊为主
- **低密度场景**（上课）：默认跳过，但有概率（默认 15%）触发插曲（传纸条、被点名、走神被抓），一旦触发则临时展开成高密度场景

一天的场景示例：

```
06:30  起床/宿舍        → 高密度（室友聊天、抢厕所）
07:00  早操/早餐        → 高密度（轻量）（排队时闲聊，max_rounds 5-8）
07:30  早自习           → 低密度（小概率传纸条）
08:00  第一节课         → 低密度
08:45  课间 10 分钟     → 高密度
08:55  第二节课         → 低密度
...
12:00  午饭             → 高密度（食堂社交）
12:30  午休             → 低密度
...
17:00  课外活动         → 高密度
18:00  晚饭             → 高密度
19:00  晚自习（三节）   → 低密度（小概率传纸条、交头接耳）
22:00  宿舍夜聊         → 高密度（一天中最自由的社交时间）
22:30  熄灯
```

### 事件连锁

场景之间有因果链，事件可以跨场景传播：

```
上午数学课：小明传纸条被老师抓
  → 课间：同学议论这件事
  → 午饭：当事人被嘲笑
  → 宿舍夜聊：室友深入讨论，小明表达委屈
```

事件通过 `world/event_queue.json` 管理，结构化存储：

```json
{
  "id": "evt_001",
  "source_scene": "第二节课",
  "source_day": 3,
  "text": "小明传纸条给小红被数学老师当场抓住并念出内容",
  "category": "conflict",
  "witnesses": ["小明", "小红", "数学老师", "小刚", "小强"],
  "known_by": ["小明", "小红", "数学老师", "小刚", "小强"],
  "spread_probability": 0.8,
  "active": true
}
```

- `category`：`"gossip"` | `"conflict"` | `"achievement"` | `"announcement"`
- `witnesses`：亲眼看到的人，`known_by` 初始等于 `witnesses`
- 传播机制：每组对话开始前，检查组内是否有人 known 而其他人不 known。如有，将"你知道这件事"注入 knower 的 context，由 LLM 自行决定是否提及（保留传话变形的可能性）。**不在注入时更新 known_by**——而是由 scene-end 分析输出 `events_discussed: ["evt_001", ...]`，只有实际被提及的事件才将同组其他人加入 `known_by`，避免假阳性截断传播链
- `spread_probability`：每次社交场景中实际传播的概率，gossip 高（0.8）、私人事件低（0.3）
- 过期：事件产生 3 天后 `active` 设 `false`，停止传播

### 地点系统

- 教室（固定座位，决定了谁的日常接触最多）
- 食堂（自由就座，关系好的人倾向坐一起）
- 操场（体育课、课外活动）
- 小卖部（课间高频社交场所）
- 宿舍（固定分配，夜聊的核心场景）
- 办公室（被叫去谈话）
- 校门口（放学、偶遇）

### 事件系统

周期性事件（剧情催化剂）：

- 月考 → 规则生成成绩（不用 LLM）：base_score(overall_rank) + subject_modifier(strengths/weaknesses) + effort_modifier(academic_pressure × study_attitude) + random_noise。
  随机方差与 overall_rank 相关：学霸方差小（稳定），中游方差大（发挥不稳定）。
  产出结构化排名数据（每人每科分数、班级排名、与上次排名变化）→ 写入 world/exam_results/，更新 academic_pressure 和 emotion，排名变化作为后续 3-5 天所有场景的 context
- 运动会 → 打破日常社交圈，产生新关系
- 期末考 → 高压，关系可能紧张或互助
- 换座位 → 强制改变日常接触对象
- 元旦晚会 → 表演、表白的高概率场景

随机事件：

- 新同学转来
- 被叫家长
- 停电
- 某人生病请假
- 老师发火

### 班主任（Phase 1 简化版）

班主任是外部不可控力量，对涌现剧情至关重要。Phase 1 用规则驱动 + 少量 LLM 调用，不需要完整的社交记忆系统：

- **月考后谈话**：根据成绩变化（排名大幅下滑、持续低迷），概率触发"找学生谈话"事件
- **晚自习巡视**：概率出现在晚自习场景，发现违纪行为（交头接耳、玩手机）→ 产生事件
- **座位安排**：换座位事件的决策者和执行者
- **课堂干预**：低密度场景的随机插曲触发源（点名回答问题、没收纸条）
- **对学生行为的抑制效应**：班主任在场时，学生的社交行为被压制，对话更拘谨

班主任的行为直接挂在场景生成器里作为概率事件，不跑 daily plan。

### 考试倒计时（Phase 1）

`progress.json` 中的 `next_exam_in_days` 字段记录距下次大考的天数，每天自动递减，月考事件调度时重置。注入每个场景的 context，让 LLM 感知考试压力。Phase 2 迁移到完整的 atmosphere 系统中。

### 全局氛围（Phase 2）

`world/atmosphere.json` 表示当前的全局氛围状态，注入每个场景的 system prompt。`exam_proximity_days` 从 Phase 1 的 progress.json 迁入：

```json
{
  "exam_proximity_days": 12,
  "semester_phase": "开学初期",
  "mood": "轻松",
  "modifier": "新学期刚开始，大家还比较放松"
}
```

- `exam_proximity_days`：距下次大考天数，<7 天时自动提升全局 anxiety
- `semester_phase`：学期阶段（开学初期/期中前/期中后/期末冲刺/考后放松）
- `mood`：全局情绪基调，影响 LLM 生成对话时的整体氛围
- `modifier`：自由文本补充说明

---

## Agent Layer

### 数据结构（每人统一）

```
Identity:
  姓名、性别、座位号、宿舍号
  角色（学生/班主任/任课老师）
  职务（班长/学习委员/体育委员/...，可为空）

Personality:
  多维性格特征（外向/内向、认真/随意、敏感/粗线条、幽默/严肃...）
  用简短鲜明的标签，不用长段描述

Academics:
  overall_rank: 总体水平（"top", "上游", "中上", "中游", "中下", "下游"）
  strengths: 强势科目
  weaknesses: 弱势科目
  study_attitude: 学习态度（简短标签，如"努力但效率低"、"聪明但不用功"）
  target: 目标院校层级（"985", "211", "一本", "二本", "没想过"）
  homework_habit: 作业习惯（"按时完成", "经常拖延", "抄别人的"）

Family Background:
  pressure_level: 家庭压力（"高"/"中"/"低"）
  expectation: 家长期望（如"父母期望考 985"）
  situation: 家庭状况（如"父母关系紧张"、"单亲"、"普通"）

Goals:
  长期目标（考好大学、交朋友、追某人、混日子、当班长...）
  （短期意图由 Daily Plan 每天生成，不在 profile 中维护。跨天持续性由 Daily Plan 的 LLM 看到昨天未完成意图后自行决定是否延续）

State:
  当前情绪（从情绪枚举中选）、所在地点
  energy（0-100）：精力值，影响发言欲（精力低 → 发言欲降低）和分组倾向（精力低 → 倾向独处）
    上课 -5，考试 -15，课间 +5，午休 +15，睡眠重置到 85
    clamp(0, 100)
  academic_pressure（0-100）：学业压力值，基础公式：
    base = family_pressure_modifier（高压家庭 +15，中 +5，低 +0）
    daily_delta = exam_proximity_factor（next_exam_in_days < 7: +3/天, 7-14: +1/天, >14: 0）
    exam_result_shock = rank_drop × 2（排名下降 5 名 → +10，上升则 -同等值）
    recovery = 考后第一天 pressure 直接回落到 base，之后每天自然 -2 直到 base
    clamp(0, 100)
  情绪枚举（~15 个）：happy / sad / anxious / angry / excited / calm / embarrassed /
    bored / neutral / jealous / proud / guilty / frustrated / touched / curious

Relationships:
  稀疏存储 — 只有发生过有意义交互的关系才创建
  默认状态是「知道名字的同学」，不维护数值
  有关系的存：好感度（-100~100）、信任度（-100~100）、了解程度（0~100）、最近关键互动（从 scene-end 的 key_moments 中自动提取与该关系对相关的条目）

Daily Plan（每天早上 LLM 生成）:
  intentions: [{target, goal, reason}, ...]  # 当日意图（想找谁、想做什么、想回避什么）
  mood_forecast: emotion                      # 当日情绪预测，初始化 state.emotion
```

### 关系系统

- **稀疏而非稠密**：不维护 N×N 矩阵，只在首次有意义交互时创建关系
- 初始状态下，只有室友、同桌、前后桌有预设关系
- 关系会随交互自然生长或恶化
- 小团体通过关系值自然涌现（几个人互相关系值都高 → 倾向聚在一起）

---

## Memory 系统

### 设计原则

模拟人类记忆的真实特征：
- 大部分日常被遗忘
- 情绪强烈的事件永久记住
- 记忆被当前情境触发（看到某人 → 想起相关旧事）
- 记忆会随时间压缩、模糊

### 文件结构（每人一个文件夹）

存储分两层：结构化数据用 JSON（Pydantic 序列化），叙事内容用 Markdown。

```
agents/
  xiaoming/
    profile.json            # 身份、性格、学业、家庭背景、目标（Pydantic model）
    relationships.json      # 当前关系状态（Pydantic model，交互后更新）
    state.json              # 当前情绪、精力值、学业压力、所在地点、daily plan（Pydantic model）
    key_memories.json       # 关键记忆（永久保留，结构化标签，Pydantic model）
    recent.md               # 本周每日总结（滚动窗口）
    today.md                # 今天的原始经历（每天清空）
    summaries/
      2026_semester1.md     # 学期压缩总结
      2026_semester2.md
      ...
world/
  schedule.json             # 课表（结构化）
  progress.json             # 模拟进度（checkpoint）
  atmosphere.json           # 全局氛围状态（Phase 2：考试倒计时、学期阶段、情绪基调）
  exam_results/             # 月考/期末考结构化排名数据
  events.md                 # 已发生的重大事件时间线（Phase 2：event_queue 过期后归档为人类可读叙事）
  announcements.md          # 全校/全班公告（Phase 2：班主任公告、换座位通知等，注入全员 context）
logs/
  day_001/
    daily_plan/             # 每人当日意图生成
    scene_03_课间/
      group_1/              # 每组对话的逐轮 input/output + scene-end 分析
      group_2/
    memory_compression/     # 睡前压缩调用
```

### 分层压缩

```
今天    → today.md 保留完整细节
近期    → recent.md 保留最近 4 周的每日/每周总结（滚动窗口）
本学期  → summaries/ 下的学期文件
更早    → 只剩 key_memories.json 中的关键记忆
```

压缩时机：
- **每天睡前**：LLM 总结 today.md → 追加到 recent.md（1-2 句日总结）→ 清空 today.md
- **每天睡前**：LLM 判断今天是否有值得永久记住的事 → 有则追加到 key_memories.json
- **每周末**：LLM 将 recent.md 中本周的日总结压缩为 1-2 句周总结，替换原始日总结
- **每周末**：recent.md 超过 4 周时，自动淘汰最早的一周（只剩 key_memories 保底）
- **每学期末**：LLM 从 key_memories + recent.md 生成学期总结 → 写入 summaries/

### 关键记忆（key_memories.json）

永久保留，结构化存储，用于跨时间回忆。用 Pydantic model + instructor 保证格式一致：

```json
[
  {
    "date": "2026-09-01",
    "people": ["小红", "小刚"],
    "location": "宿舍",
    "emotion": "embarrassed",
    "importance": 8,
    "topics": ["军训"],
    "text": "军训第一天分到同一个宿舍，小红帮我打水，小刚嘲笑我不会叠被子。"
  },
  {
    "date": "2026-10-15",
    "people": ["班主任"],
    "location": "教室",
    "emotion": "sad",
    "importance": 9,
    "topics": ["考试"],
    "text": "月考数学考了 58 分，班主任当全班面念我的名字。"
  },
  {
    "date": "2026-12-31",
    "people": ["小红"],
    "location": "教室",
    "emotion": "excited",
    "importance": 7,
    "topics": ["跨年"],
    "text": "元旦晚会小红唱了一首歌，唱完看了我一眼。"
  }
]
```

`importance` 字段（1-10 整数）由 scene-end 分析调用打分，不需要额外 LLM 调用。`prepare_context` 按 `importance` 降序取 top-K。

判断是否「关键」的标准：
- 情绪强度高（大喜、大悲、大怒、大尴尬）
- 关系发生质变（陌生→朋友、朋友→冷战、表白、背叛）
- 「第一次」（第一次考第一、第一次被罚站、第一次跟某人说话）
- 涉及重大事件（运动会、期末考、转学生）

预计每人每年 30-60 条关键记忆，几 KB 文本。

### 记忆触发（预注入）

场景开始时自动注入基线 context，不依赖 LLM 判断：
- Agent profile 摘要
- 与当前在场人物的关系
- today.md 全部内容（今天经历的所有事，保证同一天内不遗忘）
- recent.md 最近 2-3 天的日总结（保证近期记忆连贯）
- 按标签匹配的 top-K 条 key_memories（基于在场人物、地点、近期事件）
- daily plan 中未完成的意图

```python
def prepare_context(agent, scene):
    context = []
    context.append(agent.profile_summary())
    context.append(agent.relationships_with(scene.people))
    context.append(agent.today_md)                          # 今天的完整经历
    context.append(agent.recent_md_last_n_days(3))          # 最近 2-3 天日总结
    # key_memories 按相关性筛选
    triggers = extract_triggers(scene)  # people, topics, locations
    relevant = []
    for memory in agent.key_memories:
        if overlap((memory.people, memory.location, memory.topics), triggers):
            relevant.append(memory)
    context.append(sorted(relevant, key=lambda m: m.importance, reverse=True)[:K])
    context.append(agent.pending_intentions())              # 未完成的意图
    return context
```

Phase 2 加入 `recall(query)` 工具，允许 Agent 在对话中主动搜索更深层记忆（见 Phase 2 路线）。

---

## Interaction Layer

### 每天开始：Daily Plan 生成

每天第一个场景之前，为每人生成当日意图（LLM 调用，每人 1 次）。

Daily Plan LLM 输入：
- profile 摘要
- current state（emotion, energy, academic_pressure）
- recent.md 最近 2-3 天（知道最近发生了什么）
- 昨天未完成的意图（决定是否延续）
- 当前关系状态（知道在乎谁、回避谁）
- next_exam_in_days（感知考试压力）

输出（意图不超过 3 个，大部分人大部分天只有 1-2 个）：

```json
{
  "intentions": [
    {"target": "小红", "goal": "找机会搭话", "reason": "昨天她帮我打水"},
    {"goal": "回避班主任", "reason": "作业没写完"}
  ],
  "mood_forecast": "anxious"
}
```

写入 state.json，`mood_forecast` 初始化当天 emotion。

意图注入策略：
- **全部注入**：所有未完成的意图在每个场景都注入，不做条件过滤。即使 target 不在场，LLM 也可能在对话中自然提及（如跟室友聊"今天想找小红说个事"），保留间接涌现的可能性
- **弱化指令感**：注入时措辞为"你今天隐约想着的事（不一定要做，看情况自然发展）"，避免 LLM 把意图当任务执行
- **闭环标记**：scene-end 分析输出 `fulfilled_intentions` 列表，写回 state.json 标记为 done，后续场景跳过已完成的意图

### 每个场景的流程

```
1. 场景生成（规则）
   → 根据课表确定当前时间段、地点
   → 确定哪些人在这个地点

2. 构建场景引导（规则）
   → 组装 scene prompt：时间、地点、在场人物、刚发生的事、事件队列中的相关事件
   → 为每人调用 prepare_context 拉取完整 context（见 Memory 系统 - 记忆触发）

3. 自然分组（规则 + 概率）
   → 同一地点的人按关系亲密度 + 性格 + 物理位置（座位/宿舍）+ 性别 + 随机性 形成交互组
   → 性别因子按场景类型加权：宿舍硬性同性别；课间/食堂软性偏同性别；课外活动/运动会几乎不区分
   → 跨性别小组需要更强的关系基础才会自然形成
   → 每组 2-5 人
   → 有些人可能独处（性格内向、没有亲近的人、情绪低落）

4. 对话模拟（LLM，组内串行逐人调用 — 创作阶段）
   → Orchestrator 决定谁先开口（外向度 + daily plan 有意图 + 随机性）
   → 后续轮次动态选人：每轮为所有在场者计算"发言欲"分数，选最高者发言
     发言欲因子：被 directed_to 点名（大幅加分）+ 外向度（基础分）+ 有相关意图（加分）+ 连续多轮未发言（缓慢加分）+ 当前情绪（angry/excited 加分，sad/exhausted 减分）+ 精力值（低精力减分）
   → 不是每人每轮都必须说话——发言欲低的人自动旁听，自然产生"几个人在聊、其他人在听"的真实感
   → prompt 中不施加戏剧性压力，允许产出平淡的日常对话——大部分课间就是聊作业、吐槽老师、发呆，不需要每次都有冲突或转折
   → 同一场景的多个对话组可以并行调用 LLM（asyncio），组内必须串行（保证对话逻辑连贯）
   → 每轮一人一次 LLM 调用（高 temperature，保持多样性）
   → LLM 只专注生成：发言 + 内心想法 + 当前情绪 + 是否继续 + directed_to（可为空）
   → want_to_continue: false 的人离开对话组，剩余人数 < 2 则对话结束
   → 场景时长限制：每个场景有 max_rounds 参数（课间 8-12 轮、午饭 15-20 轮、宿舍夜聊 30-40 轮），
     到达 max_rounds 时强制结束，模拟外部打断（上课铃响、熄灯等）
   → 对话历史管理：超过 15 轮后，用 LLM 将前面内容摘要为一段总结，保留最近 8 轮完整内容；
     若继续膨胀，再次摘要（旧摘要+新内容 → 新摘要），保证单次调用不超 token 预算
     注意：摘要只用于创作调用的 context 窗口；原始完整对话始终写入 logs/，scene-end 分析从 logs/ 读取完整记录
   → 安全阀：单组对话超过 50 轮强制结束（兜底，正常情况下 max_rounds 会先触发）
   → 循环直到对话自然结束或被外部打断

5. Scene-end 分析（LLM，每个对话组 1 次 — 分析阶段）
   → 输入：从 logs/ 读取的完整对话日志（非摘要版本）
   → 低 temperature，保证准确性
   → 超长对话时，prompt 要求模型先列出"关键转折点"再做判断（chain-of-thought）
   → 输出：关系变化（双向）+ 值得记录的记忆 + 已完成的意图 + 实际讨论的事件 + 各人最终情绪状态
   → 关系 delta 尺度参照（写入 prompt）：
     ±1 = 一次普通闲聊的微弱影响
     ±3-5 = 有实质内容的互动（主动帮忙、小争吵、分享秘密）
     ±10+ = 关系质变（背叛、表白、重大冲突）
     单次对话通常不超过 ±5，除非发生极端事件
   → 写入 today.md、更新 relationships.json、更新 state.json（含意图闭环）

6. 独处者内心活动（LLM，每人 1 次轻量调用）
   → 分组阶段被判定为独处的人，做一次轻量 LLM 调用
   → 输入：prepare_context 同其他人，但不含对话历史
   → 输出：inner_thought + emotion（发呆、看书、偷看某人、想心事...）
   → 写入 today.md，保证内向角色的叙事线不至于空白
   → 不做 scene-end 分析，不产出关系变化或事件

7. 未参与者状态更新（规则）
   → 精力恢复、情绪自然回落

7. 事件连锁检查
   → scene-end 分析输出 new_events（可为空），将对话中涌现的值得全局传播的事件加入 event_queue
   → 同时检查规则系统是否产生需要传播的事件（班主任干预等）
   → 新事件写入 world/event_queue.json，后续场景中相关人会得知

8. Checkpoint（per-group 粒度，幂等写入）
   → scene-end 分析结果先写入临时文件 group_N_result.json
   → 确认写入成功后，一次性 apply 到各文件（today.md、relationships.json、state.json、event_queue known_by）并标记该组完成
   → 幂等保证：relationships.json 写入绝对值而非叠加 delta（scene-end 输出 delta，apply 时读取当前值计算最终值后覆盖写入）
   → 崩溃恢复：重启时若发现 group_N_result.json 存在但未标记完成，直接 apply 而不重跑 LLM
   → 更新 world/progress.json（current_day, current_scene_index, completed_groups[]）
   → progress.json 示例：{"current_day": 3, "current_scene_index": 2, "completed_groups": [0, 1], "phase": "interaction", "next_exam_in_days": 12}
```

### 对话格式

**Per-turn 输出（创作调用，每人每轮）：**

```json
{
  "speech": "你数学考多少分啊？",
  "directed_to": "小红",
  "inner_thought": "我其实想知道他是不是比我高",
  "action": null,
  "emotion": "anxious",
  "want_to_continue": true
}
```

`action` 为自由文本叙事字段（"递纸条"、"拍桌子"、"起身离开"），不驱动状态变化，用于丰富 scene-end 分析和 today.md 的物理行为描述。

LLM 只专注创作，不做关系分析。`emotion` 从情绪枚举中选，注入下一轮 context 让情绪在对话中自然演变。

**Scene-end 分析输出（分析调用，每组 1 次）：**

```json
{
  "key_moments": ["小明问分数时小红明显不想回答", "小刚主动岔开话题缓解尴尬"],
  "relationship_changes": [
    {"from": "小明", "to": "小红", "favorability": -1, "trust": 0, "understanding": 1},
    {"from": "小红", "to": "小明", "favorability": 0, "trust": -1, "understanding": 0},
    {"from": "小刚", "to": "小明", "favorability": 1, "trust": 0, "understanding": 1}
  ],
  "fulfilled_intentions": ["小明:找小红搭话"],
  "events_discussed": ["evt_001"],
  "memories": [
    {"agent": "小明", "text": "问了小红分数，她不太想说，气氛有点尴尬", "emotion": "embarrassed", "people": ["小红"], "location": "教室", "topics": ["考试"]},
    {"agent": "小刚", "text": "帮小明解围了一次", "emotion": "proud", "people": ["小明", "小红"], "location": "教室", "topics": ["考试"]}
  ],
  "new_events": [
    {
      "text": "小明当面问小红成绩被拒，气氛尴尬",
      "category": "gossip",
      "witnesses": ["小明", "小红", "小刚"],
      "spread_probability": 0.5
    }
  ],
  "final_emotions": {"小明": "embarrassed", "小红": "frustrated", "小刚": "calm"}
}
```

### 信息传播

A 告诉 B 的事进入 B 的记忆 → B 之后和 C 聊天时可能自然传播并变形（传话效应）。
这不需要特殊机制，只要 B 的记忆里有这件事，LLM 在生成 B 的对话时会自然提及。

---

## Narrative Layer

每天模拟结束后，生成一份可读的故事日志：

- **每日总结**：一次 LLM 调用，从当天所有场景中挑选最有趣的事件，写成叙事段落
- **角色聚焦**：可选，从某个角色视角写当天日记
- **周报/月报**：更宏观的叙事弧线总结

输出格式：Markdown 文件，按日期组织，适合后期剪辑成视频旁白。

---

## 技术栈

```
Python 3.12+
LLM: DeepSeek V3.2
存储: 文件系统（JSON + Markdown）
包管理: uv
```

### 核心依赖

| 包 | 用途 | 引入阶段 |
|---|---|---|
| LiteLLM | 统一 LLM 调用接口，支持多 provider 切换，内置 retry/fallback/rate limiting/cost tracking | Phase 1 |
| instructor | 包装 LLM 调用，用 Pydantic model 保证结构化输出，自动校验+重试 | Phase 1 |
| Pydantic | 数据建模（Agent、Relationship、Memory、Scene 等），自带序列化/反序列化 | Phase 1（instructor 依赖） |
| Jinja2 | Prompt 模板引擎，处理条件加载记忆、动态拼关系、场景描述等复杂 prompt | Phase 1 |
| asyncio（标准库） | 同一场景多个对话组并行 LLM 调用，减少延迟 | Phase 1 |
| loguru | 结构化日志，按 agent/场景过滤，asyncio 下需用 enqueue=True | Phase 1 |

---

## 实施路线

### Phase 1: 最小原型（8-10 人）

目标：跑通核心循环，验证对话质量和涌现性

- [ ] 设计 8-10 个角色（1 个宿舍 6 人 + 同桌/前后桌 2-4 人），包含 academics、family_background、职务（2-3 人有班干部身份）
- [ ] 实现简化版班主任 agent（规则驱动 + 少量 LLM 调用：月考后谈话、晚自习巡视、座位安排）
- [ ] 实现 World Layer：场景生成器（只做 3-4 个高密度场景：课间、午饭、宿舍夜聊）
- [ ] 实现 Agent Layer：profile.json（含 academics + family_background）+ state.json（含 academic_pressure）+ relationships.json + today.md + key_memories.json
- [ ] 实现 Daily Plan：每天早上为每人生成当日意图
- [ ] 实现 Interaction Layer：场景引导 → 分组（含性别因子）→ 逐人创作调用 → scene-end 分析调用 → 状态更新
- [ ] 实现月考事件：产出结构化排名数据，驱动 academic_pressure 和 emotion 更新，排名变化注入后续场景 context
- [ ] 实现基础 Memory：today.md 写入 + 睡前压缩 + key_memories.json
- [ ] 实现 Checkpoint：progress.json + 场景原子性 + 崩溃恢复
- [ ] 实现 Logging：每次 LLM 调用的 input/output/tokens 存入 logs/ 目录
- [ ] 跑 1 周（7 天），人工检查对话质量和角色一致性
- [ ] 调优 prompt 直到满意

### Phase 2: 完善系统

- [ ] 加入低密度场景（上课时的随机事件）
- [ ] 加入事件系统（运动会、换座位、元旦晚会等）
- [ ] 加入事件连锁机制
- [ ] 加入全局氛围系统（world/atmosphere.json：exam_proximity_days、semester_phase、mood）
- [ ] 加入角色成长机制：月考成绩生成时，根据最近一个月 academic_pressure 趋势微调 overall_rank（持续高压努力 → 可能升一档，长期摆烂 → 可能降）
- [ ] 加入 recall 工具（Agent 在对话中主动搜索深层记忆，需验证 DeepSeek V3.2 的 tool use 可靠性）
- [ ] 加入 Narrative Layer（每日总结）
- [ ] 跑 1 个月，验证长期记忆和关系演变

### Phase 3: 扩规模

- [ ] 扩展到 50 人全班
- [ ] 优化 context 组装（只加载相关人的关系）
- [ ] 加入更多地点和场景类型
- [ ] 升级班主任为完整 LLM agent + 加入任课老师角色
- [ ] event_queue 写入加锁或串行化（多组并行写入时防止并发覆盖）
- [ ] 长期运行测试（一学期）

### Phase 4: 内容产出

- [ ] 叙事输出优化（视频脚本格式）
- [ ] 视觉呈现方案（待定）
- [ ] 精彩片段自动标记

---

## 设计参考（借鉴思路，不直接使用代码）

| 来源 | 借鉴什么 |
|------|---------|
| Concordia (DeepMind) | GM 模式：orchestrator 管环境和裁决，agent 只管表达意图 |
| Sotopia (CMU) | 人格建模：Big Five、关系分级、信息不对称 |
| Stanford Generative Agents | 记忆三层架构：观察 → 重要性打分 → 定期反思 |
| GenerativeAgentsCN | 中文 prompt 模板参考 |
