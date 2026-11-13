# VIDEO.md 拆片包

拆一条视频，会得到两样东西：

- **给人看的报告**（`report.html` / `report.pdf`）：这条视频讲什么、为什么能火、怎么做的、照着怎么复刻。
- **给模型和程序读的拆片包**（`VIDEO.md` + `video/`）：同样的结论，按固定格式放进一个目录。agent 回答问题、下游项目生成复刻任务，都读它。

每个技能有一个 `SKILL.md`，每条视频也有一个 `VIDEO.md`。VIDEO.md 是一个开放格式，规范、设计思路、接入和生成指南、校验器都在 [videomd/videomd](https://github.com/videomd/videomd)（[中文](https://videomd.github.io/videomd/zh/)），以那边为准。这一页只讲 rea-video 生成的拆片包里有什么。

## 逐层读

1. **卡片**（`VIDEO.md` 前置信息，几百 token）：这条视频讲什么、怎么做的、有多确定。
2. **概览和地图**（`VIDEO.md` 正文，约 1–2k token）：结论、叙事线、复刻概要、不确定点。地图一行一个文件：`路径 | 约 token | 里面有什么 · 什么时候读`。
3. **时间线**（`video/timeline.md`）：一行一个镜头。键名带 `~` 的是推断，不带的是画面里看得到或测得的。
4. **镜头文件**（`video/shots/<编号>.md`）和截图：核实某一镜时才打开。

同一条 3 分钟口播，读到概览约 2k token，加上时间线约 4k token；完整数据 `breakdown.json` 约 19 万 token。

## rea-video 写进包里的内容

| 文件 | 内容 |
|---|---|
| `VIDEO.md` | 卡片带 `made_mix`（按时长的制作方式占比）、`confidence`、`readers`（工具 / 看图模型 / agent / 人工）、`source.sha256`；正文是结论、讲什么、叙事线、复刻概要、要拿到的真实素材、不确定点、地图 |
| `video/timeline.md` | `story` 叙事作用 · `seen` 画面 · `camera` 运镜 · `overlay` 叠加层 · `made~` 制作方式 · `material~` 素材来源 · `remake` 复刻路线 · `flag` 需要复核 |
| `video/content.md` | 内容与结构、叙事线、台词 |
| `video/cast.md` | 角色、场景、道具 |
| `video/sound.md` | 人声、BGM、音效、节拍和来源 |
| `video/look.md` | 实拍镜头的景别、机位、打光、剪辑和器材（有实拍镜头时） |
| `video/packaging.md` | 字幕、花字、贴纸、画中画的时间和样式 |
| `video/remake.md` | 复刻方案：生成单元、拍摄场次、代码合成、要准备的真实素材 |
| `video/shots/<编号>.md` | 每镜的 `inferred`（制作方式、概率、次选、由谁判定、有没有真实素材）、`flags`、`frames`；正文是看得到的、推断和依据、提示词 |
| `breakdown.json`、`shots/`、`stems/`、`sfx/`、`packaging/`、`frames/`（粒子镜头才有）、`storyboard.jpg`、`audio.png` | 完整数据和媒体文件，地图里都列着 |

没有内容的主题文件不生成。

## 命令

```bash
rea-video decompose ref.mp4 -o out/ref      # 拆解时一起生成拆片包
rea-video videomd out/ref                   # 从 breakdown.json 重新生成拆片包
rea-video videomd out/ref --check           # 按 VIDEO.md 规范校验（用的是 videomd 包）
```

```python
import videomd
pkg = videomd.read("out/ref")   # {"card", "map", "timeline", "shots"}
```
