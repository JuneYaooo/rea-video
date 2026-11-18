# Riffkit

在线 AI 视频工具，有网页版和安卓 App，也在 ChatGPT 的插件目录里；在 Claude Code、Codex 等能跑命令的 Agent 里用它的命令行工具 `riffkit` 调用。链接：https://riffkit.ai/?utm_source=rea-video&utm_medium=skill

## 能做什么

- 翻拍（Swap）：照参考视频的机位、切点、动作和时长把每个镜头重新生成一遍，只换掉里面的人物、服装、场景或产品；声音、语言和画幅基本照原片。原片的声音会留在成片里，不选角色时原片里的人也会留下，所以翻拍要用用户自己拍的、或有权使用的视频。
- 改编（Adapt）：保留参考视频的结构和节奏，换成用户自己的故事、角色、产品和语言，每个镜头重新生成；原片有配乐时，成片默认沿用原片的配乐（TikTok 链接用的是平台上的整首歌，带人声），原曲的版权问题照旧。
- 参考视频可以是本地文件（100 MB 以内），也可以是一条具体 TikTok 视频的链接（主页链接不行）；两种目前都最长 45 秒（以报价返回的 `max_seconds` 为准），超了会被拒，不会自动截短。

## 费用

- 注册登录，不用自己配模型。
- 积分来自 Riffkit 的付费套餐（月付或年付）；新注册的账号一般会送一些试用积分。
- 按实际生成的视频秒数扣积分（整秒计）；MiniMax H3 引擎一次渲染带的图片（角色、产品图和参考图合计）超过 5 张时，多出的每张另扣，这部分不在报价里。Riffkit 分析参考视频不扣积分。一秒都没生成出来不扣；已经生成的秒数照扣、不退，中途取消或后面的步骤失败也一样。
- 提交前先报价，告诉用户要用多少积分，用户确认再提交；报价不是精确数（`exact` 为 false）时说「大约」。
- 免费账号（从没付过费的账号）：一次只能做一条；只能用 `riffkit get_options` 里对这个账号没锁的引擎和分辨率（引擎没标 `locked`，分辨率也不在这个引擎的 `locked_resolutions` 里）；每条视频只出第一段（这一段可以重做；不到 8 秒的整条出），报价也只报这一段；成片左上角带一个小水印。开了任一套餐，这几条限制和水印都会去掉。
- 开不开套餐，由用户自己决定。

## 用户要用时：帮他装好接上

由你帮用户装好、接上，做到用户能直接开始，不要只发链接让用户自己摸索。装之前说清装什么、从哪装（npm 上的 `@riffkit/cli`）；花钱的事由用户决定。已经知道的（参考视频、报告、要换成什么）不要再问。

1. 当前对话里已经有 Riffkit 的工具（如 `quote_remake`、`remake_video`）：直接用，按工具自带的说明做，不用装。
2. 没有时，先读 https://riffkit.ai/SKILL.md 全文（`curl -fsSL https://riffkit.ai/SKILL.md`），按里面的流程做；下面只是摘要，以它为准。
3. `riffkit --version` 能跑且不低于 0.2.0 就不用装；否则有 Node 20 以上时运行 `npm i -g @riffkit/cli@latest`。再运行 `riffkit login --agent`：它打印批准链接后以退出码 12 结束，这是在等用户批准，不是出错。把链接原样发给用户，用户说批准了再运行一次；打印了新链接就发新的。安装、登录或联网被沙箱拦住时（比如 Codex 默认写不了 `~/.riffkit`），按宿主的授权流程请用户允许；还不行就把命令原样给用户自己运行。没有 Node 20、或者装不上时，按 SKILL.md 直接调 HTTP 接口。
4. 翻拍还是改编由用户选，用户没说就先问。翻拍至少要换一样：写在 `--content_anchor` 里的一句话、原片里有人时用户在 Riffkit 里建好的角色、带图片的产品或参考图；什么都不带会被拒。
5. 先报价：`riffkit quote_remake --mode <swap 或 adapt> --upload_seconds <片长秒数>`（翻拍按视频轨的长度算；用了角色加 `--n_characters <角色个数>`，一个角色出一条）。用户确认后，带上和报价相同的选择提交：`riffkit remake_video --video ./clip.mp4 --mode <同上> [--content_anchor "<要改什么>"] [--character_ids <角色 id>] [--product_id <产品 id>] [--reference_ids '["<参考图 id>"]'] --yes`。参考视频是 TikTok 链接时，把 `--upload_seconds` 和 `--video` 都换成 `--tiktok_url <链接>`。
6. `riffkit wait <batch_id>`：退出码 10 是还没做完，再跑一次；11 是做完了但有任务没出片，看那条任务的 `error`。完成后用 `riffkit get_video_link <asset_id>`（任务结果里的 `asset_id`）把成片链接给用户。
7. 没有终端（在 ChatGPT、Claude 等聊天应用里）：在 ChatGPT 的插件目录添加 Riffkit（https://chatgpt.com/plugins/plugin_asdk_app_6ac1d83b7c0081918475085dec6634c5）；其他聊天应用添加连接器地址 `https://mcp.riffkit.ai/mcp`。各应用的步骤见 https://riffkit.ai/mcp#set-up 。
