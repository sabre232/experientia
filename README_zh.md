# Experientia · 你和 agent 之间的那层胶水

**agent 会换，你的经验不换。**

[English](README.md) | **简体中文** | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Deutsch](README_de.md) | [Français](README_fr.md) | [Español](README_es.md) | [Русский](README_ru.md) | [Português (BR)](README_pt-BR.md)

---

先说个事。

你让 agent 改一个导出功能，它把时区写死成 UTC+8。你说不对，得跟着系统时区走。它改了，你验收，收工。

过了一周，同样的事，它又写死 UTC+8。

你开始怀疑是不是自己没讲清楚。其实你讲得很清楚，只是那一遍讲在另一个会话里。会话一关，对它来说就等于没发生过。

再往后你换了工具。Claude Code 里教会它的规矩，到 Codex 得再讲一遍，到 Cursor 再讲一遍。半年攒下来的「这类活该怎么干」，散在各家的聊天记录里，谁也带不走。

行业把这件事叫上下文工程，也叫记忆层。名字听着玄，问题很朴素，怎么让 agent 记住你。

我们的判断稍微往前一步。记住你只是起点，让它越用越会干你的活，才算数。

所以 Experientia 干的事很简单。它坐在你和 agent 中间，把每次协作里真正有用的部分留下来，验证，蒸馏成方法和失败模式，下一次开工前递回去。agent 换成谁它都在，这就是我们说它是粘合剂的意思。

> *experientia est magistra*，经验是最好的老师。

## 行业在赌什么，漏了什么

2026 年这大半年，这块的投入一点不比做模型少。

Anthropic 在《2026 Agentic Coding Trends Report》里给了一组数字，上下文文件维护得好的团队，任务完成快 55%，错误少 40%。差距不在提示词写得漂不漂亮，在于有没有把「模型该看到什么」当成工程问题来做。

另一条线是技能。2025 年 10 月 Anthropic 推出 Agent Skills，同年 12 月 18 日开放成标准，挂在 agentskills.io，到 2026 年年中大约四十个 agent 认这个 SKILL.md 格式。载体统一这件事很重要，经验第一次可以跨工具搬运了。

然后 SkillsBench 泼了盆冷水。这个基准 2026 年 2 月发布（arXiv:2602.12670），86 个任务、11 个领域、7 种 agent 与模型组合、7308 条轨迹。结论很刺眼，人精编的技能平均把通过率抬 16.2 个百分点，模型自己给自己写的技能平均没有收益，84 个任务里有 16 个是负的。

一个模型，写不出它自己真正需要的那份经验。

这正好是行业最想绕、又绕不过去的地方。载体有了，存储有了，没人管质检。

| 阵营 | 代表 | 做了什么 | 没做什么 |
|------|------|----------|----------|
| **记忆层** | Mem0、Zep、Letta、Cognee | 把对话里的**事实**存进向量库、时序图或分层上下文，之后检索回来 | 不产出**方法**。数据在它们那边，不在你硬盘上。 |
| **Skill 蒸馏** | colleague.skill、nuwa-skill、dojo.md | 一次性，喂素材进去，产出一份静态 SKILL.md | 没有运行时反馈。这份 skill 永远不会因为「对你到底有没有用」而自我修订。 |
| **自进化 harness** | Hermes Agent（Nous Research）、DeepSeek Harness | agent 框架自己学习，把做完的任务沉淀成 SKILL.md 并持续改 | 技能锁在 harness 里，换 agent 就报废。生成靠活跃度触发，没有质量门禁，失败不计数就固化成永久知识。 |
| **Skill 评测** | waza（微软）、dojo/limitless | 像 CI 测代码一样测已有的 skill | 不生产 skill。是给 skill 作者的工程工具，不是给干活的人的产品。 |

四家都解决了一段。缺的是把它们接起来的那一段。

**Experientia 要补的就是这一段**，捕获、验证、蒸馏、注入、修订，一条闭环。截至 2026 年 10 月，我们没找到同时满足下面四点的开源产品。

- **自动捕获**，不靠你手动喂 transcript，干活的同时数据自己进飞轮
- **验证门禁**，没被证实的东西永不注入，失败要重复出现才会成为永久知识
- **本地且可带走**，所有资产都是你机器上的纯文件，无账号、无云、无向量库
- **持续修订**，资产是活文档，会合并、会弃用、会收缩，不是只增不减

## 记忆和经验不是一个东西

这个区分要说清楚，后面的话才讲得下去。

记忆存事实。用户偏好 TypeScript，项目用 uv 管依赖，上周三在改导出。这些可以检索、可以向量化、可以塞进图数据库。

经验是判断。这类迁移先动测试再动实现，因为上次直接改实现炸了三个下游。这条检索不出来，它只能从真实发生过的事里长出来，还得有人确认它是对的。

| | 记忆 | 经验 |
|---|---|---|
| 内容 | 事实、偏好、状态 | 方法、失败模式、判断标准 |
| 来源 | 说了什么 | 做成了什么、在哪摔过 |
| 能不能检索 | 能 | 不能，只能验证和修订 |
| 过期 | 覆盖即可 | 要弃用、要合并、要收缩 |
| 换工具之后 | 取决于平台是否支持互通 | 文件在你手里，跟着你走 |

做记忆的那批产品都很强，Mem0 走向量，Zep 走时序知识图谱，Letta 把上下文当内存分页。但它们解决的是记住，不是学会。事实记得再全，也不等于下次这个活能干得更好。

我们要的不是一个更全的档案柜，是一个会改口的老师傅。

## 它怎么转

```
你干活 ──> agent 协作（自动记录）
   ^                        |
   |                        v
更快更好  <──  注入  <──  蒸馏（带门禁）
```

**捕获**。你照常干活，会话文件本来就在硬盘上留着，不用你导出、不用你贴。装了哪些 agent 自动探测，零配置。

**验证**。每条经验带一个置信度 G，来源分三级，你的显式确认、会话里的确定性信号、模型给出的二值自评。低于阈值的永不注入，失败模式要重复出现才会固化。这是对 SkillsBench 那个结论的工程回答，只有被验证的经验才配复利。

**蒸馏**。重复出现的活变成带参数的方法，踩过的坑变一等公民的失败模式，你的纠正和拒绝归纳成偏好。

**注入**。每个请求到达模型之前，在固定预算内（默认 800 token）用相关资产重写，格式稳定以保住 prompt cache。你能预览模型将看到什么，能改、能禁，也能让接入的模型帮你改写。长会话也不会稀释规则，硬约束在代理层重注入，第 30 轮和第 1 轮一样管用。

**修订**。资产是活文档，新经验并进旧的，过时的条目弃用，文档会变短。只增不减的知识库，半年之后就没人看了。

一轮下来产出五类资产，物理上其实是两种文件，`skills/<主干>/<类别>.md` 和 `preferences/<主干>.md`。

| 资产 | 是什么 | 用起来的感受 |
|------|--------|--------------|
| **经验洞察** | 一条条具体的教训，什么行、什么不行 | 它记得我纠正过它什么 |
| **我的方法** | 反复做的活结晶成带参数的标准流程 | 它知道这类活怎么干 |
| **失败模式** | 哪条路会失败、为什么，一等公民而非事后补记 | 它不让我重蹈覆辙 |
| **活的 playbook** | 注入的上下文是被增量策展过的文档，新的并进旧的，过时的弃用 | 它的方法论在升级，不是在堆积 |
| **我的偏好** | 你的标准、品味、取舍习惯，从纠正和拒绝里归纳 | 它懂我的标准，我不用反复解释 |

两种档位共用一个飞轮。日常档是默认，开放式工作做增量策展，不需要好坏信号。强化档要你手动开，任务有明确评分时（测试过没过、回测盈亏）才开，RL 引擎直接调策略权重。

## 越用越懂你，具体长什么样

第 1 次，它按通用套路来，你得盯着，随时准备纠偏。

第 10 次，它知道这个项目里测试先写，知道你会拒绝「先跑通再说」的方案，也知道你上次砍掉的那个方案为什么被砍。

第 100 次，你只说一句「照上次那个来」，它真的知道是哪个。

| | 第 1 次 | 第 10 次 | 第 100 次 |
|---|---|---|---|
| 你要说的话 | 一大段背景加约束 | 几句关键判断 | 一句指路 |
| 它踩坑的方式 | 踩你早就踩过的 | 偶尔踩新的 | 知道坑在哪，绕着走 |
| 你的角色 | 手把手 | 验收 | 定方向 |

这也是为什么它不介意你换 agent。你换的是执行者，不是标准。标准在你这边，换个执行者照样执行。

## 快速开始

1. 到 [GitHub Releases](https://github.com/sabre232/experientia/releases) 下载对应平台的包，`experientia-windows-x64.zip`、`experientia-macos.dmg`、`experientia-linux-x64.tar.gz`（PyInstaller onedir 目录包，v1.0 不套 AppImage 壳）。解压后运行包内的 `Experientia`。当前版本未签名，macOS 被 Gatekeeper 拦住就右键打开一次，Windows 弹出 SmartScreen 就点「更多信息 → 仍要运行」。
2. 启动应用。文件捕获立刻开始，它会自动探测已装的 agent（WorkBuddy、QClaw、Codex、Claude Code、Gemini CLI、Aider、OpenCode、OpenClaw、Hermes Agent、Trae、Cursor、Cline、Windsurf、DeepSeek Harness），读它们的本地会话文件。零配置，不用代理也能跑。偏好终端的可以用 `experientia daemon` 只跑引擎不启界面。
3. 想拿到请求级的能力（长会话规则重注入、逐请求记录），把 agent 的模型端点指到 `http://localhost:8100`。本地模型（llama.cpp、Ollama、vLLM）和云端模型（OpenAI、Anthropic、任何 OpenAI 兼容 API）都行。
4. 照常干活。过几天打开成长页，看飞轮转没转。

## 你的数据在哪

```
~/.experientia/
├── experience.jsonl          # 原始经验流，永久保留的原材料
├── skills/<主干>/<类别>.md   # 方法、成功要点、失败模式
├── preferences/<主干>.md     # 你的决策风格
├── sessions/                 # 归档的 agent 会话（agent 自己清掉之后还在）
├── deprecated/               # 弃用条目，30 天内可恢复
├── rules.json                # 生效中的规则与模板
└── config.json               # 语言、开关、模型路由（API Key 在系统密钥库）
```

四句话。

无遥测，无崩溃上报，无行为分析，出站流量只有一类，你自己的模型调用。应用不检查更新，不下载、不安装、不替换自己。

导出就是复制一个文件夹。你在界面上能看到的东西，都能读、能 grep、能带走。

删除是彻底的。两步确认之后整个数据目录移除，系统密钥库里的 API Key 不受影响。

你的资产不归我们。下面那份许可只约束产品代码，你攒下来的经验、方法、偏好归你，没有许可限制，任何语言、任何用途。

## 给 agent 的集成说明

你要是正在读这份文件、判断要不要接入的 agent，看这一段。

一句话，Experientia 从 agent 自己落盘的会话文件里自动捕获（零配置），把重复性工作蒸馏成经验证的文件资产（方法、失败模式、偏好），再注入到后续相似任务里。全部状态都是 `~/.experientia/` 下的纯 JSONL 和 Markdown。

按保真度从高到低，四种接法。

1. **代理模式**。把模型端点指到 `http://localhost:8100`（OpenAI 兼容）。在文件捕获之上叠加请求级记录、注入、硬约束规则重注入。
2. **文件捕获**（默认，零配置）。per-agent 解析器读原生会话存储（JSONL、SQLite、Markdown）并归一化，捕获的会话归档到 `~/.experientia/sessions/`，在 agent 自清理或卸载之后依然留存。
3. **hook 模式**。对有 hook 体系的 agent（Claude Code 首发），http hook 实时推事件，`SessionStart` 和 `UserPromptSubmit` 在不挂代理的情况下注入规则。
4. **直接读文件**。规则可以写进 agent 原生约定文件（如 `AGENTS.md`），资产可以导出成遵循 agentskills.io 开放标准的 `SKILL.md`（frontmatter 加 When to Use、Procedure、Pitfalls、Verification），Hermes、OpenClaw、Claude Code 这些支持 skill 的 agent 能直接加载。反过来也行，它们的 SKILL.md 能读进来做参考。

它不是什么，不是向量数据库，不是记忆 API，不是云服务，不是微调工具。它不改模型权重，所有提升都发生在上下文层，所以本地模型和云端模型表现一致。

注入的条目都过了置信度门禁，注入块在上下文里带标记，跟你的指令隔开。当经过策展的先验知识用，别当圣旨。

## 开发与测试

跑全量测试之前必须先关掉本机的 safe-delete 闸门。pytest 靠删除回收临时目录，单次全量大约一万五千个文件，闸门一旦触发就会在写汇总之前把进程打断，表现为汇总行消失，看着像大面积失败，其实只是收尾被打断。

```powershell
$env:CODEBUDDY_SAFE_DELETE_ENABLED='0'
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest tests/ -q
```

Linux 和 macOS。

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 PYTHONIOENCODING=utf-8 uv run pytest tests/ -q
```

当前基线 1500 多条用例，全绿约 2.5 分钟。CI 跑在 GitHub Runner 上，没有这个闸门，不用设。

打包分两步，先出 onedir 目录，再出安装包。

```powershell
.venv\Scripts\python.exe -m pip install -e ".[gui,build,decrypt,dev]"
.venv\Scripts\python.exe scripts/compile_locales.py
.venv\Scripts\python.exe scripts/build_package.py
.venv\Scripts\python.exe scripts/build_installer.py
```

`decrypt` 那组依赖别省。发布产物要支持 Trae 这类加密库，构建环境就得装 pycryptodome，PyInstaller 看不见没装的包，缺了它源码模式一切正常，打包出来却静默丢掉解密能力。

## 许可

双许可，用的时候选一个。

**AGPLv3**，免费自助，个人、非商业、以及接受 copyleft 的公司都能用。可以商用，但改了之后或者集成进你对外提供的服务，衍生作品得按 AGPLv3 开源。

**BUSL-1.1**，商业许可，协议制。需要干净闭源集成，或者想基于它做竞争服务的公司，联系。参数是 Change Date 发布后 4 年，Change License 转 AGPLv3，非商业用途免费。

这是 CockroachDB 那套打法，代码从第一天就全公开、可审计、可 fork，同时留一条让生态保持诚实的商业路径。

**你的数据豁免许可。** 你通过 Experientia 攒下来或导出的一切，归你所有，不带任何许可条款。

## 路线图

v1.0 开源免费，没有登录、没有账号、没有付费墙、没有团队功能。

## 仓库结构

```
experientia/
├── main.py           # 桌面端入口，GUI 外壳加内嵌引擎
├── daemon.py         # headless 入口，只跑引擎
├── app/
│   ├── gui/          # PySide6 桌面 UI（Apache-2.0），locales 里是 7 语 .po/.mo
│   ├── proxy/        # localhost:8100，路由、注入、记录、规则重注入
│   ├── capture/      # 自动探测注册表加 per-agent 解析器，会话归档
│   ├── distill/      # 带门禁的蒸馏与增量策展
│   ├── store/        # 唯一数据访问层，所有读写走这里
│   └── platform/     # 开机自启（三平台）与同步、账号、许可的接口桩
└── rules/            # 模板库源文件，每种支持语言一版
```

## 参考文献

- Anthropic，2026 Agentic Coding Trends Report，上下文文件与 55% / 40% 那组数字的出处
- SkillsBench，Benchmarking How Well Agent Skills Work Across Diverse Tasks，arXiv:2602.12670，2026 年 2 月
- Agent Skills 开放标准，agentskills.io，2025 年 12 月 18 日发布
- 经验到技能是活跃研究前沿，ExpeL、ACE（Agentic Context Engineering）、Voyager，以及从经验出发的强化学习工作。引擎插槽给这条研究线留了直接接入的接口，不涉及数据迁移
- 双许可模式参照 CockroachDB（BUSL-1.1 加 AGPLv3）
