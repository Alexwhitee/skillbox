# 视频任务选型

以下是用户偏好与已核对的本地入口，作为候选优先级，不是互斥的绝对边界。实际 API、硬件和许可每次准备使用时重新核对。本表不证明工具已装好或已成功渲染。

## 本地优先候选

根目录：`/Users/xi/dev2/agent-skills/zimeiti/`。

| 需求 | 优先检查 | 本地操作资料 | 关键判断 |
| --- | --- | --- | --- |
| B 站项目介绍、软件教程、知识讲解；后续反复修改 | OpenFilm，`openfilm/` | `README.md`、`skills/openfilm/SKILL.md`、`packages/openfilm/manual/` | 适合 HTML 镜头、录屏、图解、字幕和声音的时间线，保留可编辑工程；当前本地 manifest 的 Node 要求与 README 可能不同，按实际运行版本检查 |
| SaaS/网页/App 发布片，突出真实界面与品牌 | video-shotcraft，`video-shotcraft/` | 根 `SKILL.md`，按需读 `references/pipeline.md` 或 `template/TEMPLATE.md` | 真实页面采集、镜头卡、Remotion；用户授权自主创作时选自主模式，点名模板则用模板；不把不明任务硬塞模板 |
| 水墨、绘本、像素、蓝图、复古等风格动画 | Lemo-Opuscar，`lemo-opuscar/` | `AGENTS.md`、`styles/README.md`、`DIRECTOR.md`、`TECHNIQUE.md` | 先检索风格、按主题导演；也有纪实与资料驱动风格，不仅限生成动画；复用本地库，不因 setup 默认目录另 clone 一份 |
| 已有歌曲，按音乐结构与节奏做 MV | Mondo Music Video，`mondo-music-video/` | `skills/mondo-music-video/SKILL.md`、`docs/INSTALL_WITH_AGENT.md`、`docs/AGENT_SETUP.md` | 检查服务、模型、当前 API/MCP 和生成后端；Mac 不等于可跑 CUDA 路线；保留预览/费用与素材权限边界 |

对应官方仓库：
- [OpenFilm](https://github.com/openfilm/openfilm)
- [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft)
- [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar)
- [Mondo Music Video](https://github.com/hodgemann/mondo-music-video)

已有可参考的真实交付工程：`films/gearbox-bilibili/README.md`。该片用 OpenFilm，包含工程、声音分轨、字幕、封面与 QA；它自己的 `build.sh` 用于渲染已有剪辑，`prepare.py` 会重建镜头和时间线，不能为改几个字直接运行后者覆盖手工编辑。仅复用制作方法，不复制 Gearbox 文案到其它项目。

## 缺口对应的联网候选

这些不是默认已安装，也不是要求全部下载。只有当前任务需要且本地不足时才查询官方版本、许可、依赖与硬件要求。

| 需求 | 候选及官方源 | 采用前核对 |
| --- | --- | --- |
| 主题到文案、素材、配音、字幕的批量短视频 | [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 素材来源与商用权、服务/API、批量成本与实际中文质量 |
| 已有电影/纪录片，理解素材后配解说并剪辑 | [NarratoAI](https://github.com/linyqh/NarratoAI) | 输入视频权利、理解模型与配音后端、时间戳和剪辑结果 |
| 从课程/访谈/直播中按文字或说话人抽取片段 | [FunClip](https://github.com/modelscope/FunClip) | 识别语言与模型、说话人/时间戳准确性，不把重新生成画面当剪辑 |
| 新的写实、幻想或电影感镜头 | [ComfyUI](https://github.com/Comfy-Org/ComfyUI)；硬件匹配时 [LTX Desktop](https://github.com/Lightricks/LTX-Desktop) | GPU/内存/磁盘、模型和节点许可；模型生成镜头还需要剪辑，不自动等于完整成片 |
| 已有成片的字幕翻译与换语言配音 | [VideoLingo](https://github.com/Huanshere/VideoLingo) | 目标语言、配音权利、翻译对齐、TTS/API；保留原始视频与字幕 |

用户过去的比较文档在 `zimeiti/视频制作项目对比与开源方案推荐.md`，可作为历史线索。其硬件结论、Beta 状态和许可证不是永久事实，重新检查本机与官方文档，不能照抄为当前结论。

## 成片验收

在实际制作前明确时长、比例、字幕和声音要求。最小 smoke 可渲染一个代表性镜头和一段声音；正式片检查整体播放、开头/中间/结尾、转场、字幕遮挡/可读性、音画同步与音量。用可用的 FFprobe/播放器检查实际视频/音频流、时长、分辨率；看截图或抽帧，听声音，不能只检查文件非空。

交付 MP4 等要求的成片、可编辑源工程和重渲染入口；字幕、封面、声音分轨按任务需要保留。附素材/音乐/模型来源和实际 QA 边界。未要求投稿或发布时只交本地作品，不自行上传平台。
