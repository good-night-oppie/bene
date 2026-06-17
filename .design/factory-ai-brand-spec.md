# Factory.ai · Brand Spec（蒸馏）

> 采集日期：2026-06-15
> 来源：factory.ai 首页 HTML + 2 个 CSS bundle + docs.factory.ai/welcome
> 用途：作为 BENE landing/docs 重设计的参考 DNA。**仅蒸馏 grammar，不复用 logo / 不复用文案**——避免做成 Factory 山寨。

## 🎯 核心资产（识别度根基）

### Logo（不复用，但 grammar 可学）
- 主 logo：`Factory.ai` 等宽 wordmark，灰墨黑色（无 accent 涂色）
- F-mark：**8 角 organic star-splat**——不是规整几何，每条 ray 长度、曲率都不同；像手绘星 / 油彩泼洒，**异常有辨识度**（具体路径见 `factory-fmark.svg`）
- **启示**：BENE 现在的 twin-B monogram 已经够独特，不动。可学的是「mark 该有 organic / 手绘 / 非规整感」这个原则——避免做成 emoji 或 Material icon

### Typography（直接可用）
| 角色 | 字体 | Fallback | 备注 |
|---|---|---|---|
| Display / Body | **Geist** | Geist Fallback → ui-sans-serif → system-ui | Vercel 开源，几何 modern，开源免费 |
| Mono | **Geist Mono** | Geist Mono Fallback → ui-monospace → SFMono | 同家族 mono |
| 来源 | CDN: `https://vercel.com/font/sans/Geist-*.woff2` | Google Fonts 也有 | 可直接 @font-face |

**为什么是好选择**：Geist 是开源 + 几何 + 中性 + 工程师品味。比 Inter 更有「设计师挑过」感，比 Söhne 等付费字体便宜。直接用没成本。

## 🎨 辅助资产

### 色板（按频次排，标注角色）

**主色族 · burnt orange 家族**
| 色值 | 频次 | 角色 |
|---|---|---|
| `#EF6F2E` | 9 | **Primary brand** — 主 accent / hero CTA / 强调色 |
| `#EE6018` | 3 | hover / pressed 深一档 |
| `#EE8B3A` `#E6A24D` `#FF9B4D` `#F3B15D` | 2×4 | gradient / 高光变体 |
| `#B46A35` | 2 | 文字上的橙（更深更可读） |

**底色族 · warm cream（最有辨识度）**
| 色值 | 角色 |
|---|---|
| `#F0EEE8` `#F2EEE7` | **Page background**——这是 Factory 跟所有冷灰 SaaS 的最大差异 |
| `#EDE9E4` `#ECE8DF` `#E9E7E5` | surface 略沉一档（卡片 / sidebar） |
| `#E8E4DD` `#CFCCC8` `#C8C2BA` `#BAB5AD` | divider / 分隔线 / muted UI |
| `#FAFAFA` | 反向 light-on-dark 时的浅底（少用） |

**Ink / 中性**
| 色值 | 角色 |
|---|---|
| `#020202` `#0A0908` | 深底反色用（dark mode 背景） |
| `#1F1D1C` | **Primary ink**——不是纯黑，warm tone |
| `#2E2C2B` `#3D3A39` | 次级文字 |
| `#62666D` `#858B97` | muted 灰（带冷调） |
| `#A49D9A` `#AAB0BB` | 极弱辅文 |

**Info accent**
| 色值 | 角色 |
|---|---|
| `#7DB5E8` | 链接 / info accent（罕用，冷调对暖橙） |

**macOS traffic light（说明他们做了不少 mac app 截图）**
- `#FF5F57` 红 / `#FEBC2E` 黄 / `#FF6B5F` red variant — 终端窗口三个小灯

### 圆角刻度（关键签名 · 比常规 SaaS 小一档）

| token | px | 用途 |
|---|---|---|
| `--radius-xs` | 2 | inline pill / micro chip |
| `--radius-sm` | 3 | input / checkbox |
| `--radius-md` | 4 | button / chip |
| `--radius-lg` | 6 | card |
| `--radius-xl` | 8 | feature card |
| `--radius-2xl` | 10 | hero card |
| `--radius-3xl` | 12 | **最大**——modal / large surface |

**对比常规 SaaS**：Tailwind 默认 `rounded-2xl` = 16px / `rounded-3xl` = 24px。Factory 的 3xl = 12px。**信号：crisp / editorial / 工程，不要 friendly / 玩具感**。

### 排版细节（micro-typography）
- 大量用 `text-wrap: pretty`（CSS）
- 字号在 Display 处大量上 `clamp(48px, 5vw, 96px)`——视口自适应
- letter-spacing 主要用在 uppercase utility 上（如 nav）
- H1 跨多行，**词组间用 `\n` 强制断行**，不靠浏览器自动 wrap
- 段落 `line-height: 1.55-1.7` 范围

## 🧱 Layout grammar

### Hero 节奏
- H1 占视口上 1/3
- H1 之下是**对仗式短句**（5-12 字），不是 paragraph
- CTA 双按钮：一个 primary 一个 ghost
- 下面是终端命令一行（`$ curl -fsSL https://app.factory.ai/cli`）——把 CLI 当 hero 一部分
- 整 Hero 用 `gradient-11.png` 抽象橙系大渐变作背景纹理（不是纯色）

### Section 节奏
- 暗 / 亮交替（深暖底 ↔ 奶油底）
- Section padding 慷慨（80-120px 上下）
- Max-width 1200-1400px，文本 max-width 收得更窄（600-720px）

### Chip / Badge 风格（推测）
- 极小圆角（2-4px）
- 文字加 letter-spacing
- 多数 ghost style（透明底 + 1px border）

## 📐 文档（docs.factory.ai）叙事 grammar

### IA（信息架构）
```
Welcome
├─ Start with your surface     # 入口分流
│  ├─ Droid CLI
│  ├─ Factory App
│  ├─ Droid Exec
│  └─ Enterprise
└─ Explore core capabilities    # 能力深挖
   ├─ Platform / Capabilities / Configure
   ├─ Integrations / Enterprise / Using Droid
   └─ Reference
```

**关键启示**：first-pass nav 是「surface」分流（CLI / App / Exec / Enterprise）——按**用户的入口姿势**分类，不是按功能模块。BENE 现在的 docs 是按功能分（CLI / Memory / Skills / Probes...），可借鉴这个 surface-first 的角度。

### Prose 风格（动词驱动 · 无第一人称）

| 维度 | Factory.ai 做法 | BENE 现在做法 | 应否切换 |
|---|---|---|---|
| 句长 | 短命令式 + 中描述 mix | 长 Pressfield 戏剧化 | **不切**——BENE 的 voice 是优势 |
| 主语 | 全是「you」「your」 | 有「the next agent walks in」「you reach for...」混合 | **保留 BENE 现状** |
| 第一人称 | 零「we」 | 偶尔「BENE 的活是...」 | **少用即可** |
| 动词 | Run / Use / Teach / Connect / Plan | Run / Open / Grep / Promote / Restore | 已经一致 |
| 类比 | 几乎零（直接给定义）| 03:00 oncall / 烂 prompt 上线翻车 | **保留**——BENE 的场景叙事是差异化 |

**判断**：Factory 的 prose 是「Stripe-cool clarity」，效率高但没温度。BENE 的 4-book methodology 校过的 voice 比 Factory 更有戏剧张力。**只学他们的 IA 结构（surface-first）+ 动词式 sidebar nav**，不学 prose。

### 代码块处理
- 单行命令直接放在 hero（不进 box）
- 长代码块（猜测）用 lg 圆角（6px）+ 暖灰底
- 没看到 callout/admonition——他们不用 :::tip 这类 mintlify 标准元素，而是用 Card 直接当导航

### 在线 llms.txt
- Factory **也有** `/llms.txt`（跟 BENE 同款 agent-facing 元数据）
- 说明这是 2026 agent-time 的标配

## 🎭 整体气质（3 词）
**warm-technical · crisp · editorial**

- warm-technical：暖底 + 技术内容（不是冷蓝白 SaaS）
- crisp：小圆角 + 中性 Geist 字 + 高对比 ink（不是 friendly bouncy）
- editorial：大量小标题分段、文本 max-width 收窄、像报纸专栏（不是 marketing landing）

## 🚫 我们应该避免学的（反 slop）

| Factory 现状 | 学还是不学 | 理由 |
|---|---|---|
| 大渐变 hero 背景（`gradient-11.png`）| 不学 | 渐变是 AI slop 之首；我们应该用别的方式做视觉张力 |
| 「Your software Factory powered by Droid」类口号 | 不学 | BENE 已经有更尖锐的 H1（"eval 给上一个 prompt 打了高分。它还是把线上带沟里了。"） |
| 4 卡 Surface 入口 | 学 IA 不学 layout | IA 借鉴 surface-first 分流；但 layout 不抄 4 卡 grid |
| Enterprise/SLA/BAA 单独页 | 学 | BENE 应该加 `/security`、`/oss` 这类 trust 页面 |

## 📝 给 BENE 重设计的 5 条 actionable 借鉴

1. **字体**：Inter → **Geist + Geist Mono**。免费、有签名感、跟 Factory 同源说明这是 2026 工程师审美的当代选择。
2. **底色**：现在 `--bg: 250 250 250`（FAFAFA）→ 切到 **`#F0EEE8` 暖象牙**。整页温度+5℃，跟所有冷灰 SaaS 拉开距离。
3. **圆角**：现在 BENE 偏 8/16px → 收紧到 **2/4/6/8/12 五档**。crisp / editorial 信号。
4. **Section 节奏**：现在 BENE 是大段连续滚动 → 切到 **奶油 ↔ 深暖（#1F1D1C）交替**。给 page 一种「翻页」节奏。
5. **docs IA**：现在按功能拆 → 切到 **「按入口姿势分」**（"CLI 用户进 / Python 用户进 / MCP 用户进 / Enterprise"）。Surface-first 比 feature-first 更回答「我该看哪里」。

## 🚫 不动的（BENE 的现有优势）

- **Twin-B monogram** logo——已经独特，不换
- **3am oncall + Pressfield 戏剧化 voice**——比 Factory 的「imperative + zero-emotion」有质感
- **「卡点 1/2/3/4」叙事结构**——Factory 没这种 narrative scaffolding
- **VHS gap demos**——这是 Factory 没有的资产
- **engram ladder / kill gate / SharedLog** 自创名词系统——这是 BENE 的 IP，不被 Factory grammar 稀释

---

*作为 brand-spec 的强制约束（hi-fi 阶段不允许临场发明新色 / 新字体 / 新圆角值，不在 spec 表里的色就不写进 CSS）。*
