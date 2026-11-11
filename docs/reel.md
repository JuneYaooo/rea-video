# Reel 拆片包：视频拆解的标准包

拆一条视频，会得到两样东西：

- **给人看的报告**（`report.html` / `report.pdf`）：这条视频讲什么、为什么能火、怎么做的、照着怎么复刻。
- **给模型和程序读的拆片包**（Reel）：同样的结论，按固定格式放进一个目录。agent 回答问题、下游项目（如 capsule-cinema）生成复刻任务，都读它。

这一页介绍拆片包是什么、为什么这样设计，后半部分是完整的格式规范。

## 为什么要有拆片包

完整的拆解数据（`breakdown.json`）一条 3 分钟的口播就有约 19 万 token：逐镜的测量值、证据、帧率、字幕时间轴都在里面。模型每回答一个问题都读一遍，又贵又慢，还容易在细节里迷路。

拆片包把它分成四层，像 agent skill 一样逐层展开：

1. 先读一张**卡片**（约 150 token）：这是什么视频、怎么做的、有多确定，值不值得往下读。
2. 再读一页**概览和地图**（约 1–2k token）：结论、叙事线、复刻概要、不确定点。地图写清每个文件里有什么、什么时候该读、有多大。
3. 要按镜头回答时读**时间线**：一行一个镜头。
4. 要核实某一镜时，才打开那一镜的**镜头文件**和截图。

同一条口播，读到第 2 层约 2k token，加上时间线约 4k token，就能回答「这条怎么做的、要准备什么、哪几镜要复核」。

## 三条规矩

- **看到的和推断的分开写。** 画面里看得到、能对着截图核实的，和工具推断的制作方式，放在不同的字段和小节里；时间线里推断的键名带 `~`。两者对不上时，以截图为准。
- **读之前就知道代价。** 每个文件开头都写着自己有多少 token。
- **格式固定，内容可以扩展。** 卡片、时间线、镜头文件的字段有 JSON Schema，可以程序校验；读的一方遇到不认识的字段、键、文件时忽略，不报错。

## 怎么得到、怎么检查

```bash
rea-video decompose ref.mp4 -o out/ref      # 拆解时一起生成拆片包
rea-video reel out/ref                      # 旧的输出目录，从 breakdown.json 补出拆片包
rea-video reel out/ref --check              # 检查是否符合 Reel 格式
```

```python
from rea_video import reel
pkg = reel.read("out/ref")   # 卡片、时间线、每个镜头的结构化数据
```

---

以下是格式规范。

## 目录

拆解的输出目录本身就是一个拆片包：

```
out/ref/
  REEL.md              入口。L0 卡片（前置信息）+ L1 概览和地图（正文）
  reel/
    timeline.md        L2 时间线：一行一个镜头，整个包的主干
    content.md         L2 内容与结构、叙事线、台词
    cast.md            L2 角色、场景、道具
    sound.md           L2 人声、BGM、音效、节拍、来源
    look.md            L2 拍法、打光、剪辑（有实拍镜头时）
    packaging.md       L2 字幕、花字、贴纸、画中画
    remake.md          L2 复刻方案、要准备的真实素材和参考素材
    shots/07.md        L3 单个镜头的全部细节
  breakdown.json       L4 完整原始数据
  shots/ stems/ sfx/ packaging/ storyboard.jpg audio.png   L4 帧图、分轨音频、音效片段、字幕文件
  report.html report.md                               给人看的报告
```

没有内容的主题文件不生成（比如没有实拍镜头就没有 `look.md`）。**所有路径都相对包根目录**，包括写在 `reel/` 下文件里的路径。

## 四层

| 层 | 在哪 | 大小 | 回答什么 |
|---|---|---|---|
| L0 卡片 | `REEL.md` 前置信息 | 约 150 token | 这是什么视频、怎么做的、有多确定，值不值得往下读 |
| L1 概览 | `REEL.md` 正文 | 约 1–2k token | 结论、叙事线、复刻概要、不确定点，以及地图 |
| L2 主题 | `reel/*.md` | 每个几百到几千 token | 某一方面的完整信息；`timeline.md` 一行一镜 |
| L3 镜头 | `reel/shots/<编号>.md` | 每个约 500–1000 token | 某一镜看得到什么、推断是什么、依据、提示词、帧图 |
| L4 原始 | `breakdown.json`、媒体文件 | 几十万 token | 程序用；模型一般不需要打开 |


## 每个文件的前置信息

每个 `.md` 文件开头都是 YAML 前置信息，至少有：

```yaml
reel: 1          # 格式版本
part: timeline   # 这是哪一部分：timeline / content / cast / sound / look / packaging / remake / shot
tokens: 2275     # 正文大约多少 token，读之前就知道代价
```

`REEL.md` 的前置信息就是卡片：

```yaml
reel: 1
name: ref
description: 混合制作：实拍 94% + 屏幕录制/截图 4% + AI 生成视频 2%
source: {file: ref.mp4, duration: 174.067, size: 1080x1920, fps: 30.0, aspect: '9:16'}
shots: 25
confidence: 0.771          # 按时长加权的判断置信度
made_mix: {live_action: 0.943, screen_capture: 0.039, ai_video: 0.019}   # 推断，按时长
readers: [tools, vlm, agent]   # 谁参与了判断：工具测量 / 看图模型 / agent 看图 / 用户纠正（user）
open_questions: 9
lang: zh
```

## 看到的和推断的

拆片包始终把两类信息分开：

- **看到的**：画面里看得到、能对着截图核实的东西（画面内容、运镜、叠加层、文字、破绽），以及直接测得的量。
- **推断的**：工具和看图模型对制作方式、素材来源的判断，附概率和依据。依据可能是肉眼看不出的测量（帧率、噪声、转码、元数据）。

时间线里用键名标出来：**键名后带 `~` 的是推断**，不带的是看到的或测得的。每镜文件里分成「画面里看得到的」和「工具推断的制作方式」两节。两者对不上时，以截图为准。

## 时间线语法

`reel/timeline.md` 里，镜头行放在 ```` ```reel-timeline ```` 代码块中，一行一个镜头：

```
#07 16.2-18.5 | seen 男子讲话，画面上弹出多张聊天截图 | cam 固定 | made~ 屏幕录制/截图(screen_capture) 41% · 次选 代码/模板渲染 29% | real~ 用户真实素材：录屏素材 | remake 录屏重建 · 段1 | flag 低置信
```

- 行首：`#编号 起-止`，时间单位是秒。
- 之后是用 ` | ` 分隔的字段，每个字段是 `键 值`（第一个空格前是键）。值里不会出现 `|`。
- 字段按下表顺序出现，没有的字段省略：

| 键 | 含义 | 类别 |
|---|---|---|
| `say` | 这一镜在叙事里的作用和讲的点 | 看图得出 |
| `seen` | 画面里有什么（一句话） | 看到的 |
| `cam` | 运镜（固定、手持、平滑运镜、整图推拉……） | 测得的 |
| `over` | 叠加层（字幕、花字、标题、贴纸……） | 测得的 |
| `made~` | 制作方式和置信度，括号里是类别 id；`· 次选` 后是第二可能 | 推断 |
| `real~` | 素材来源：AI 生成、用户真实素材、混合…… | 推断 |
| `remake` | 复刻路线和所属的生成单元 / 拍摄场次 / 代码工程 | 方案 |
| `flag` | 需要复核：低置信、待确认、有分歧、用户纠正 | — |

读写时遇到不认识的键要保留、不能报错，以后的版本可以加键。

## 镜头文件

`reel/shots/07.md` 的前置信息是这一镜的结构化数据，正文是给模型读的细节：

```yaml
reel: 1
part: shot
shot: 7
time: [16.2, 18.467]
camera: static
overlays: [subtitle]
inferred:
  made: screen_capture        # 类别 id，见 skills/rea-video/references/taxonomy.md
  p: 0.408
  alternatives: {code_render: 0.294, live_action: 0.209}
  decided_by: fused           # deterministic / fused / fused_agent / user
  real_material: true
flags: [low_confidence]       # uncertain / disputed / low_confidence
frames: {sheet: shots/shot_007.jpg, first: shots/shot_007_first.jpg, last: shots/shot_007_last.jpg}
tokens: 572
```

正文依次是：画面里看得到的 → 工具推断的制作方式（推断、素材来源、判断依据）→ 复刻（说明、首帧图像提示词、视频提示词）。

## 怎么读

模型：

1. 读 `REEL.md`。大多数问题（怎么做的、要准备什么、哪里不确定）到这里就能回答。
2. 要按镜头回答时读 `reel/timeline.md`，找到相关的行或带 `flag` 的行。
3. 要核实某一镜时，打开 `reel/shots/<编号>.md` 和它 `frames` 里的截图。
4. 不读 `breakdown.json`。

程序：用前置信息和时间线行，不解析正文。rea-video 带了一个参考实现：

```python
from rea_video import reel
pkg = reel.read("out/ref")      # {"card": {...}, "timeline": [{"shot": 7, "start": 16.2, "made~": ...}], "shots": {7: {...}}}
```

## 取值

| 字段 | 取值 |
|---|---|
| 制作方式 `made` / `made_mix` / `alternatives` 的键 | `live_action` 实拍、`ai_video` AI 生成视频、`avatar` 数字人、`cg_3d` 3D 渲染、`code_render` 代码/模板渲染、`screen_capture` 录屏/截图、`still_motion` 静图推拉、`static_hold` 静帧、`anim_2d` 2D 动画、`stop_motion` 定格动画、`film_footage` 影视片段 |
| `camera` | `static` 固定、`static_with_subject_motion` 固定（主体在动）、`planar_zoom_pan` 整图推拉/平移、`handheld_like` 手持晃动、`smooth_move` 平滑运镜、`unknown` |
| `overlays`（开放取值，可能增加） | `subtitle` 字幕、`title` 标题、`label` 标注、`huazi` 花字、`static_graphic` 图形贴片、`layout_template` 版式模板、`animated_sticker` 动图贴纸、`static_sticker` 静态贴纸、`pip` 画中画 |
| `decided_by` | `deterministic` 只有工具、`fused` 工具 + 看图模型、`fused_agent` 工具 + agent 看图、`user` 用户纠正 |
| `flags` | `uncertain` 待确认、`disputed` 有分歧、`low_confidence` 低置信 |
| `readers` | `tools`、`vlm`、`agent`、`user` |

时间线里的值是写给模型读的，跟着包的语言走（中文或英文）；程序要用稳定的 id，就读镜头文件的前置信息，或者取 `made~` 括号里的类别 id。

## 一致性要求

一个目录是合格的 Reel 拆片包，当且仅当：

1. 根目录有 `REEL.md`，前置信息符合 schema 里的 `card`。
2. `REEL.md` 地图里列出的每个路径都存在。
3. `reel/` 下每个 `.md` 都有前置信息，符合 `part`（镜头文件符合 `shot`）。
4. `reel/timeline.md` 有 ```` ```reel-timeline ```` 代码块；块里每一行都符合时间线语法，编号严格递增，结束时间不早于开始时间，行数等于卡片里的 `shots`。
5. 时间线每一行在 `reel/shots/` 下有同编号的镜头文件，两边的编号和时间一致（允许 0.06 秒误差），`made~` 括号里的 id 和 `inferred.made` 一致。
6. 镜头文件 `frames` 里的路径都存在。

schema 在 `rea_video/reel.schema.json`（JSON Schema 2020-12）。检查一个目录：

```bash
rea-video reel out/ref --check     # 合格时输出“符合 Reel 格式”，否则逐条列出问题，退出码 1
```

写拆片包的一方必须满足上面全部规则；读的一方遇到不认识的字段、键、主题文件时忽略，不报错。

## 版本

`reel: 1` 是当前版本。只加字段、加键、加主题文件时版本号不变，读的一方忽略不认识的内容；改了已有字段的含义或时间线语法时升版本号。
