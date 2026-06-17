# GitHub Agent Orchestration Framework — README 美学风格调研

> 调研日期：2026-06-11。样本：14 个高星 agent orchestration / agent framework 仓库的实时 README
> （原文存于 `raw/`，下载的 banner / logo / 图表存于 `assets/`）。
>
> 样本：LangChain (~110k★)、Dify (~110k★)、AutoGPT (~170k★)、MetaGPT (~45k★)、
> AutoGen (~45k★)、OpenHands (~60k★)、crewAI (~35k★)、LlamaIndex (~40k★)、
> LangGraph (~15k★)、CAMEL (~13k★)、Semantic Kernel (~23k★)、Swarm (~20k★)、
> Agno (~30k★)、Pydantic AI (~12k★)。

## 一、高星 README 的通用模版结构（按出现频率排序）

几乎所有高星仓库遵循同一个"漏斗"结构：

```
1. <div align="center"> Hero 区
   ├── Logo 或 Banner（带 <picture> 暗色/亮色切换）
   ├── 一句话 tagline（<h3> 或 <p>，不超过 12 个词）
   ├── Badge 行（license / PyPI version / downloads / Discord / X）
   └── 多语言链接行（En | 中 | 日 | …）+ 导航链接行（Docs · Cloud · Blog）
2. <hr> 或空行分隔
3. 一段话定位陈述（"X is a framework for …"）
4. Quickstart（pip install + 10 行以内的最小代码示例）
5. Why use X?（3-6 个 bullet，每条加粗关键词）
6. 架构图 / 产品截图 / Demo GIF
7. Ecosystem / 与兄弟项目的关系图
8. Examples / Cookbook 链接表
9. Community（Discord / WeChat / Slack）
10. Contributors 墙（contrib.rocks）+ Star History 图
```

### 三种主流 Hero 风格

| 风格 | 代表 | 特征 |
|---|---|---|
| **A. 全宽 Banner 图** | Dify、CAMEL | 第一行就是一张 1280px 宽的品牌插画 banner，信息密度最高，视觉冲击最强 |
| **B. 居中 Logo + tagline** | LangChain、LangGraph、Agno、crewAI、OpenHands、MetaGPT | `<picture>` 双主题 SVG logo（宽 50% 或 150–600px）+ 一句话定位 + badge 行；最克制、最"工程师审美" |
| **C. 纯文本 H1** | AutoGPT、Swarm | `# Name: tagline` 直接开头，靠正文图表撑视觉；适合实验性 / 官方背书强的项目 |

### Badge 风格两派

- **flat（默认）**：LangChain、crewAI、CAMEL — 数量多（6–10 个），一行排开。
- **for-the-badge（大号）**：OpenHands — 只放 4 个但每个都大（LICENSE / SWE-Bench 跑分 / Docs / Paper），用 benchmark 分数当 badge 是差异化亮点。
- 增长类标配：Trendshift badge（camel、crewAI、dify 都挂）、star-history.com 折线图、contrib.rocks 贡献者头像墙。

## 二、图片需求清单（做一个对标 README 需要准备什么）

| 资产 | 规格建议 | 必要性 | 参考 |
|---|---|---|---|
| **Logo（暗/亮双版本 SVG）** | 横版 wordmark，`<picture>` + `prefers-color-scheme` 切换 | ★★★ 必备 | `assets/langchain_logo_{dark,light}.svg`、`assets/agno_logo_*.svg` |
| **全宽 Banner** | ~1280×400，品牌色 + 吉祥物/插画 + 标语 | ★★ 风格 A 必备 | `assets/dify_banner.png`、`assets/camel_banner.png` |
| **产品截图 / 控制台 UI** | 高分辨率（2x），带浏览器框 | ★★（有 UI 的项目） | Agno 的 demo-os、AutoGen Studio 截图 |
| **Demo GIF / 视频缩略图** | <10MB GIF 或 YouTube hqdefault 封面 | ★★ | crewAI 挂 YouTube 缩略图 |
| **吉祥物 Logo** | 方形 200px PNG | ★ 加分项 | `assets/openhands_logo.png`、`assets/metagpt_logo.png`、`assets/swarm_logo.png` |
| **生态/合作伙伴 logo 墙** | 单独 SVG，黑白双版本 | ★（成熟期） | OpenHands 的 Netflix/Apple/NVIDIA 墙 |

## 三、图表需求清单

| 图表类型 | 用途 | 参考 |
|---|---|---|
| **架构分层图（techstack）** | 一图讲清模块分层；CAMEL 用一张超大 techstack 图替代千字介绍 | `assets/camel_techstack.png` |
| **概念流程图** | 解释核心抽象（agent ↔ handoff ↔ tool）；手绘感降低认知门槛 | `assets/swarm_diagram.png` |
| **多智能体协作图** | role-playing / workforce 等编排模式各一张 | `assets/camel_role_playing_diagram.png`、`assets/camel_workforce_diagram.png` |
| **Star History 折线图** | `api.star-history.com/svg?repos=...&type=Date`，动态生成无需维护 | AutoGPT、Dify |
| **Contributors 墙** | `contrib.rocks/image?repo=...`，动态生成 | AutoGPT、CAMEL、Dify、SK |
| **Mermaid 图** | 新趋势：用 mermaid 替代静态 PNG，免维护、自动适配暗色主题 | Pydantic AI 文档风 |

## 四、可直接套用的美学结论

1. **暗色优先**：所有头部项目都为 GitHub 暗色主题准备了资产（`<picture>` 双 SVG 是 2025+ 的事实标准）。
2. **Hero 区一屏定生死**：logo → 一句话 → badges → install 命令，必须在首屏完成"是什么 + 怎么装"。
3. **Badge ≤ 1 行（flat）或 ≤ 4 个（for-the-badge）**；benchmark 分数做成 badge 是 OpenHands 式的高级差异化。
4. **代码示例在前、架构图在后**：开发者工具先证明 DX，再讲架构。
5. **动态资产外包**：star-history、contrib.rocks、trendshift、shields.io 全部用第三方动态 SVG，零维护成本。
6. **多语言链接行**放 hero 区底部（readme-i18n.com / zdoc.app 可自动翻译）。
7. **图表手绘感 > 精致感**：Swarm 的简笔流程图比精修 3D 渲染更受欢迎——传达"简单"的产品气质。

## 五、目录说明

- `raw/` — 14 个仓库 README 原文快照
- `assets/` — 19 个下载的 banner / logo / 图表（文件名 = `项目_用途.扩展名`）
