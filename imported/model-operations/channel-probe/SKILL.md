---
name: channel-probe
description: Claude 与 Gemini 中转渠道体检、签名形态与行为核验。用于测试渠道可用性、调查 CCMax / API / Bedrock 来源线索及剥签复签、检查请求与计费一致性、排查模型故障。不能仅凭签名布局或同渠道回传证明正文生成来源。签名解码器随包安装，Gemini 核验需 node 18+。
---

# Claude + Gemini 渠道体检、上游形态判定与真伪核验

检查渠道健康、Claude 签名形态、供应来源线索、请求与计费一致性，以及 Gemini 行为指纹。**这些观察不能保证识别 CCMax 正文配真实 Bedrock 签名的混合供应；无法区分时明确报告无法判定。**

## 依赖与位置

- 本 skill 目录 = SKILL.md 所在目录（开发仓在 `jiaoben/skill/`；Codex 安装在 `$CODEX_HOME/skills/channel-probe/`，默认 `~/.codex/skills/channel-probe/`）
- 含四个可执行组件：`probe_channel.py`（流水线）、`channel_check.py`（Claude 一致性检测）、`gemini_verify.mjs`（Gemini 真伪核验）、`probe_thinking_signature.py`（签名解码核心，安装时随包捆绑；开发布局在 skill 上层目录，`probe_channel.py` 自动两处查找）
- **签名解码核心**: `probe_thinking_signature.py` — AWSB/first-party 判定的基石，**不要重写它的解码逻辑**，一律子进程调用
- `channel_check.py` 自带一套**只读** protobuf 解析器（移植自源仓库 `jiaoben/2.txt`，逐字未改）：一致性检测需要摘要字节定位（bit 翻转）、f21 签发时间、f6 模型位等 probe_thinking_signature.py 不暴露的信息，有 `--selftest` 兜底
- `gemini_verify.mjs` 移植自源仓库 `jiaoben/gemini-verify.mjs`（仅加了位置参数 BASE_URL KEY，探针逐字未改），**需 node 18+**（用内置 fetch）
- Python 部分只依赖标准库；阶段 8 需 node

## 快速开始

```bash
# 以下命令中的 skill/ 指 SKILL.md 所在目录（换成绝对路径亦可）
cd <skill目录>
# 基础: 体检 + 签名形态判定（便宜，每模型 1-2 个小请求）
python3 probe_channel.py BASE_URL API_KEY

# 指定模型子集
python3 probe_channel.py BASE_URL API_KEY --models claude-opus-4-6,claude-sonnet-5

# 深度: + 回传验签(防拼接) + 参数指纹 + 分词器对照
python3 probe_channel.py BASE_URL API_KEY --deep

# 全量: + 1M 上下文测试（烧 token，先告知用户成本）+ 撞限流（必须用户明确授权）
python3 probe_channel.py BASE_URL API_KEY --deep --big-context claude-opus-4-6 --load

# 官方一致性检测（7 项，~52-67 个请求；可单独跑也可并入流水线）
python3 channel_check.py BASE_URL API_KEY --model claude-sonnet-4-6
python3 channel_check.py BASE_URL API_KEY --json --trace-out trace.jsonl
python3 channel_check.py --selftest          # 不需要网络
python3 probe_channel.py BASE_URL API_KEY --consistency              # 阶段7 并入流水线
python3 probe_channel.py BASE_URL API_KEY --consistency claude-sonnet-4-6

# Gemini 渠道真伪核验（9 个行为探针，需 node 18+；可单独跑也可并入流水线）
node gemini_verify.mjs BASE_URL API_KEY --model=gemini-4-argon
node gemini_verify.mjs BASE_URL API_KEY --json
python3 probe_channel.py BASE_URL API_KEY --gemini              # 阶段8 并入流水线（双协议渠道一起测）
python3 probe_channel.py BASE_URL API_KEY --gemini gemini-4-argon --consistency
# 纯 Gemini 渠道（无 Claude /v1 侧）直接用 node 跑；probe_channel --gemini 遇 Claude 侧全不通也会自动降级只跑阶段8
```

## 判定原理（为什么可信）

### 第一层：thinking 签名 → AWSB vs first-party（格式观察）

官方将 `signature` 视为包含加密思考内容的不透明字段。这里的 protobuf 解码只读取格式，**不执行密码学校验**；字段和 message_id 一致也不证明其真实性。即使独立可信端点确认某个思考块有效，也不能据此断言返回的正文全部由同一个上游生成。中转可能剥块、替换签名、另行调用真实上游，或按探针分流。以下仅为经验格式判据：

| 判据 | first-party / CCMax 形态 | AWSB (Bedrock) |
|---|---|---|
| 平台位 f2 | 缺失 | = 1 |
| 身份位 f11 | 36 位 UUID（具体语义未获官方保证） | 12 位账号形态 |
| message_id 前缀 | `msg_01…` | `msg_bdrk_…`（vertex 是 `msg_vrtx_`） |

新代模型可能使用不同 compact 格式。缺少平台位或身份位时不能仅凭缺失排除 Bedrock；应记录解析能力不足，并用当前官方行为及可信端点交叉核验。
模型拒 `thinking.type=enabled` 要求 `adaptive` ≠ Bedrock 证据，只是新代换了开关方式，换 adaptive 重试即可。

### 第二层：first-party 内部 → CCMax 池 vs 官转 API（行为证据）

两者都是 api.anthropic.com 同一套服务端，签名天生相同（凭证差异在上游鉴权层，到响应体就被剥掉）。可测的差异只剩行为面：

| 测试 | 官转 API 表现 | CCMax 池表现 | 区分力（截至 2026-11） |
|---|---|---|---|
| **撞限流**（最强） | 每凭证 tier 墙（Opus 4.x: Start 2M / Build 5M / Scale 10M ITPM），撞墙文案 `rate_limit_error` / "per minute" | 多账号聚合无共享墙，撞穿后文案 5-hour window / weekly / usage limit 订阅语言 | 仅"撞墙文案"有区分力；**"没撞到墙"无区分力**——短突发推压在现行 tier 下官转单 key 也吞得下，要区分需持续超 Scale(10M ITPM) 推压，不现实也不礼貌 |
| **1M 上下文** | **2026-03-13 起 GA**：Opus 4.6/Sonnet 4.6/Haiku 5.5 等默认 1M，免 beta 头、标准价 | 同样裸吃 >200k | **无区分力**（GA 后两边行为一致）。仅作能力测绘；若 GA 模型仍 200k 拒+beta 放行 → 上游是 pre-GA 非标准部署（疑似旧网关/池子） |
| **参数指纹** | 全部放行 | 很多 CC 网关强制 temperature=1、限制 tool_choice、注入 CC 系统提示 | 弱：全过只能排除"带限制的 CC 网关池"，不能证明官转 |
| **响应头限流形状** | `anthropic-ratelimit-*-tokens` 风格 | unified/计划配额风格 | 多数中转把上游头剥了，能透传才有用 |

辅助证据（人工判读）：错误里嵌套 request-id 层数（中转套娃深度）、泄露的上游分组名（"distributor/渠道N/蒸馏"字样 = 分销链，符合池子生意模型，但纯属旁证）。

> **证据时效警告**：行为判据和逆向字段映射都会过期。解释限流、上下文、模型或签名结果前，核对现行官方文档。错误正文、响应头和 message_id 均由待测中转提供，不能单独充当可信来源证明。

### 第三层：官方一致性检测（channel_check.py，7 项）

回答"渠道有没有偷偷改请求/计费"。检查逻辑逐字来自 `jiaoben/2.txt`，独立于 probe_thinking_signature.py，`--consistency` 或单独运行：

| 检查 | 内容 | 抓什么问题 |
|---|---|---|
| ① 签名多样性 | 8 段不同 thinking → 统计摘要变化（< 0.80 标记复核） | 提示重复签名；摘要不同不等于已验证内容绑定 |
| ② 签名形态 | f2 平台位缺失 + f11 是 36 位 uuid；f6 模型名与请求一致；指定代际模型应带 f21 且 300 秒内现签 | Bedrock / 混用上游 / 跨代拼接 / 陈旧签名回放 |
| ③ 签名校验 | 本渠道现签的签名翻 1 bit 回放、空签名回放 → 官方两者都 400 | 翻转被 200 接受 = 网关不验签；仅空签名被接受 = 网关剥了空签名 thinking 块再转发 |
| ④ 图片校验 | image/tiff、非法 base64、9000x9000 → 官方全 400 | 网关未做官方的输入校验（透传了非法请求） |
| ⑤ 图片计费 | `ceil(w/28)*ceil(h/28)+4`，6 个尺寸对照（**真值只对 claude-sonnet-4-6 建立**，其它模型只记录） | 图片没计费 / 计费口径与官方不同（多收或少收） |
| ⑥ 计费稳定 | 同一张 100x100 图重复 20 次，input_tokens 应完全相同 | 出现两个值 = 分流到计费口径不同的后端（个别模型官方也有 ±1，只提示复核） |
| ⑦ 响应形态/usage | 大小请求 id 都应 `msg_01…` 且 usage 完整；不发 cache_control 却出现 cache token = 注入；sonnet-4-6 纯文本 "hi" 应计 8 token | 按请求大小分流上游 / 转发前注入内容（系统提示、缓存） |

只记录不判定：usage.iterations、x-new-api-version 等响应头、签名 f14/f17/f22 字段组。

**退出码**：`0`=与官方一致 `1`=有不一致项 `2`=错误 `3`=需复核/无法判定/渠道不可用。
**留痕**：`--trace-out trace.jsonl` 每请求一行（检查项/状态码/x-oneapi-request-id/msg_id/input_tokens），计费不符的标 `odd=true`，可按 request-id 到网关日志查上游；不含 key、不含请求体。

## Gemini 渠道真伪核验（gemini_verify.mjs，9 个行为探针）

回答"Gemini 端点接的是不是真 Google 供给"。原理：真实 Gemini 端点在**参数校验**上有一组非常稳定的特征报错（protobuf 枚举校验器、role 白名单、thinkingBudget 能力判定等），套壳/逆向代理通常只实现正常路径，遇到边界参数会静默接受或返回自造泛化错误。自动探测接口风格（v1beta AI Studio / publishers Vertex），认证三件套同发（?key= / x-goog-api-key / Bearer）：

| 探针 | 官方行为 | 抓什么问题 |
|---|---|---|
| 非法 role | banana 之类被拒（"valid role"） | 没做 role 白名单校验 |
| 空输入 | 空 parts 返回 cannot be empty | 边界校验缺失 |
| 枚举校验 ×2 | toolConfig.mode / safetySettings.threshold 填非法值 → "Invalid value at '...' + EnumType" protobuf 特征报错 | 没有 protobuf 校验器（最强指纹之一） |
| thinkingBudget | 该模型只支持 thinkingLevel，官方明确拒绝 | 参数能力判定缺失 |
| cachedContent | 假资源名 → Not found / could not parse | 不解析缓存资源名 |
| 响应信封 | 必带 modelVersion + responseId（无 createTime = Vertex 特征） | 响应是被改写/转译过的 |
| usageMetadata | 带 promptTokensDetails + candidatesTokensDetails（无 trafficType = Vertex 特征） | 同上，兼可辨 AI Studio vs Vertex |
| 不存在的模型 | 必须报错，不能编造回答 | 幻觉后端（拿别的东西冒充 Gemini） |

**判定**：0 失败且 ≥7 通过 = 行为与官方一致；0 失败且 ≥5 通过 = 主要一致（限流导致部分 SKIP，建议重跑）；≤2 失败 = 个别偏离，结合明细复核；>2 失败 = 高度疑似套壳/逆向代理。
**退出码**：`0`=全部通过 `1`=存在失败项 `2`=参数/认证/网络错误（认证失败不会误判成套壳）。
**注意**：badmodel 探针若被网关的模型/价格目录拦下（"price not configured" 等）会记 SKIP 而非 PASS——没真正触达模型，不当证据。

### 回传检查及复签调查（可选加强）

`--deep` 阶段 2 只测试原块回传能否成功；阶段 7 增加翻转签名和空签名对照。**同一个待测中转返回 200/400，无法排除其自行校验、剥块、复签或伪造错误。** 某些模型还会合法丢弃历史思考块，所以 200 不等于该块被保留、验证并使用。

调查复签时，优先考虑以下补充检查。现有脚本没有自动实现这些步骤，需要按模型能力构造小样本；它们是调查方法，不是保证识别 CCMax 的算法。

1. **工具调用中的绑定对照**：发含随机测试标记的请求，让模型产生 `thinking` 和 `tool_use`。完整保留原始 system、tools、messages 和全部 assistant content（含 redacted_thinking），回复匹配的 tool_result。先确认原样对照成功，再分别只修改可见 thinking、翻转签名、换入另一请求的签名、修改签名前的消息。不要人为重建 assistant 正文，也不要把参数错误或 429 算作绑定拒绝。遵循模型的 thinking 配置；强制 tool_choice 可能使模型不输出 thinking。
2. **绑定诊断**：对官方文档明确支持的模型（例如 Sonnet 5.5），使用 `thinking-binding-controls-2026-08-01` beta 和 adaptive thinking，读取顶层 `input_transformations`。Anthropic 协议用 `anthropic-beta` 请求头；直接调用 Bedrock InvokeModel 用请求体 `anthropic_beta`。保持控制组的前文完全一致，再对比改变前文时 `thinking.block_binding.prefix_mismatch_behavior` 的 `error` 与 `drop_block` 行为。字段缺失可能表示未透传 beta、模型不支持或响应被转换，不直接归因 CCMax。
3. **独立可信端点验证**：有用户提供的可信直连凭据时，在独立端点回放受支持模型的完整样本并读取丢弃原因。AWS 文档将 `end_user_binding_mismatch` 用于 Claude 应用来源的思考块，将 `organization_binding_mismatch` 用于其他账号/客户组；后者在正常跨账号回放中也会出现。前者可识别仍保留应用来源绑定的思考块，不能区分订阅套餐；若中转已经换成有效 AWS 块，这条线索也可能消失。来自待测中转本身的同名字段只有参考价值。
4. **生成请求对账**：为请求加入随机标记，在可信 AWS 账号的 model invocation logs 中核对该次请求的输入、输出、modelId、requestId 和 token 数。只有一次 AWS 请求、一个 AWS request-id 或签名通过，不足以证明返回正文来自该请求。日志需从可信账号直接读取；渠道导出的文本或截图仍可被修改。计时、签名长度、缓存和 SSE 顺序仅作筛查线索。

官方参考（使用时检查适用模型及版本）：[AWS 思考块绑定与丢弃原因](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-thinking-block-binding.html)、[Claude 思考块故障排查](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting)、[AWS 调用日志](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)。

**边界**：若中转替换为有效 AWS 思考块并能模拟全部外部行为，仅凭该中转的黑盒接口不一定能区分其内部生成链路。报告应分开记录签名格式、回放行为、独立验证与正文来源；不把前三者自动升级为最后一项。

## 执行流程（probe_channel.py 各阶段）

| 阶段 | 内容 | 开关 | 成本 |
|---|---|---|---|
| 0 | 模型列表 + 逐模型连通（PASS/FAIL/延迟） | 默认 | 极低 |
| 1 | 逐模型签名探测（enabled → adaptive 回退），调 probe_thinking_signature.py 出 RESULT/VERDICT | 默认 | 低 |
| 2 | 同渠道原样回传（最多 3 个模型，不证明来源） | `--deep` | 低 |
| 3 | 参数指纹 5 项 | `--deep` | 极低 |
| 4 | 同文本跨模型 token 计数对照（同代一致=分词器差异良性；每模型固定增量=疑似注入） | `--deep` | 低（~38k/模型） |
| 5 | ~210k tokens 裸发 + beta 头对照 → **上下文能力测绘**（GA 后无官转/池子区分力，仅发现 GA 模型带 beta 门槛等非标准部署时有价值） | `--big-context M` | **烧 token**（被拒的请求免费，被收的才花钱） |
| 6 | RPM 突发(3波×8并发) + TPM 推压(4×100k)，**撞到第一堵墙立即收手并打印错误原文** | `--load` | **烧 token + 给渠道加压** |
| 7 | 官方一致性 7 项（channel_check.py 子进程，模型省略时优先 claude-sonnet-4-6） | `--consistency [M]` | ~52-67 请求（thinking 请求 max_tokens≤2600，其余 max_tokens=8） |
| 8 | Gemini 真伪核验 9 项（gemini_verify.mjs 子进程；Claude 侧全不通时自动降级单独执行；限流自动重试） | `--gemini [M]` | ~12-20 个小请求，需 node 18+ |

### 使用守则

1. **--load 必须先获用户明确授权**（对渠道主动加压，烧真实配额，影响池内其他用户）。授权前只跑到 --deep
2. **--big-context 先报成本估算**（约 210k input tokens × 该模型单价）
3. **--consistency 先报请求量**（~52-67 个请求，其中 14-33 个是 max_tokens≤2600 的 thinking 请求，产生少量 output token 计费）
4. **阶段8 需先确认 node 18+ 可用**；探针含故意非法的参数与假模型名，走的是错误路径，基本不产生 token 计费，但会占用请求配额（有限流自动重试，默认 6 次）
5. 撞限流阶段**打到第一堵墙就停**，不要持续压测
6. 签名文件落在 skill 目录的 `sigs/` 下，可用 `python3 probe_thinking_signature.py --decode-file <f>` 手工复查
7. `--gemini` 混跑时 BASE_URL 是**同一个**：适合双协议中转（同一网关同时挂 Claude /v1 与 Gemini /v1beta）；纯 Gemini 渠道直接 `node gemini_verify.mjs BASE_URL KEY`

## 结果解读

脚本末尾自动输出汇总判定。人工解读要点：

- `layout=BEDROCK` → 观察到 Bedrock 签名形态；多个 layout → 格式混用。两者均不能单独判定正文生成来源。
- first-party + **订阅式限流文案**（5-hour/weekly/usage limit）→ 订阅供给线索，需可信来源核实；错误文案可被中转改写。
- first-party + **API 式限流文案**（rate_limit_error / per minute）→ API 供给线索，不能排除订阅池或混合供应。
- first-party + 限流无墙 / 1M 裸吃 → **无区分力**，不许据此下池子或官转结论（GA + 新 tier 后两边行为一致）
- first-party + GA 模型 200k 拒 + beta 头放行 → 上游非标准部署（pre-GA 旧网关/池子）
- first-party + 参数受限/系统提示被注入 → CC 网关型池子
- first-party + 分销链元数据（多层 request-id / distributor 分组名）→ 倾向池子的**弱旁证**，只能降低置信度表述，不能实锤
- 全部模型不吐 thinking → 签名证据缺失 = **无法判定**，这是"无证据"，不是"无问题"，别当洗白

一致性检测（阶段 7 / channel_check.py）结论解读：

- `pass` 仅表示所测项目符合内置参考条件，不证明来源或排除复签（非 sonnet-4-6 会注明图片公式未校验真值）。
- `signature_not_verified` 表示篡改签名被接受；剥块或转换也可能导致这一结果。`signature_pool` 表示重复摘要线索；`request_or_billing_modified` 表示与内置参考不符。结合当前官方直连对照及请求日志复核，不单独断言 CCMax。
- `stale_signature`（签名非现签）/ `missing_f21`（代际不符）→ 拼接/回放陈旧签名的伪装
- `review`（计费 ±1 漂移、按大小分流、空签名被剥）→ 有可疑但官方个别情况也有，**提示复核不下实锤**
- `inconclusive` / `unavailable` → 样本不足或渠道不可用，"无证据"≠"无问题"

Gemini 真伪核验（阶段 8 / gemini_verify.mjs）结论解读：

- 0 失败 + ≥7 通过 → 行为与官方 Google Gemini 端点一致，未发现套壳迹象
- 0 失败 + 5~6 通过 → 主要一致，SKIP 项多为限流所致，稍后重跑补齐
- ≤2 失败 → 个别偏离（可能是中转自己加的包装层），结合失败明细里的期望行为人工复核
- >2 失败 → **高度疑似套壳/逆向代理**，不建议作为官方供给使用；重点看"静默接受非法参数"与"不存在的模型编造回答"两类
- 认证失败/端点不可达 → 退出码 2，直接修 key/地址，别当套壳结论

## 诚实边界（必须告知用户的）

1. 逆向签名布局只提供格式线索，不是独立验签。CCMax、API 和 Bedrock 的混合生成/复签不能仅凭该布局或同渠道回传区分；限流文案也不是不可伪造的证据。
2. "未撞到墙"**不是**池子证据：2026 现行 tier（Opus 4.x Start 2M ITPM 起）下，常规推压官转单 key 也无感
3. 字段语义（f2=1↔Bedrock 等）是逆向经验映射；message_id 同样可被中转重写，不是独立交叉验证。格式矛盾应复核，格式一致也不能证明来源。
4. 中转替换真实签名、按探针分流或自己处理回放时，阶段 2/7 也可能全部通过；应参考上面的独立验证与请求对账方法，保留无法判定的结论。
5. **行为判据会过期**：解释限流/上下文结果前先核对现行官方文档；曾因 1M GA（2026-03-13）和新 tier 表实际翻车两次，勿重蹈
6. **一致性检测的真值边界**：图片计费公式与纯文本 "hi"=8 token 的真值只对 claude-sonnet-4-6 建立，其它模型只记录数值不判定；⑥ 稳定性在官方个别模型上也出现过 ±1，所以该项只提示复核；官方行为本身会演进（计费公式、usage 字段），报不一致且渠道方申诉时，先拿官方直连复测再下结论
7. channel_check.py 与阶段 2 的回传验签有重叠（③ 是其加强版：控制组 + bit 翻转 + 空签名三组对照）；两个都跑不冲突，结论以 ③ 为准
8. **Gemini 核验是行为指纹，不是密码学证明**（原脚本自己的定位）：探针对齐的是"当前官方端点的特征报错"，Google 改错误文案/加新参数会让指纹过期，报 FAIL 且渠道方申诉时先拿官方端点复测；thinkingBudget 探针的前提是"该模型只支持 thinkingLevel"，换默认模型或模型能力变化时该探针的期望要跟着换
9. Gemini 探针测不到的：模型是否被降智/换成小模型（回答质量层面）、计费是否被篡改（Gemini 端点一般不回计费明细）、Claude 侧的伪造签名问题——分别归阶段 0 延迟人工判读 / 渠道方对账 / 阶段 1+7 管
