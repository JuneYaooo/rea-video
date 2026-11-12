# 扩充评测集

先装开发依赖：`pip install -e ".[ocr,dev]"`。

1. 在 `eval/labels.yaml`（或新建一个 yaml）里加条目：
   - `label`：可以是列表，表示可接受的多个标签
   - `segments`：分段真值
   - `real_material`：是否用了真实素材
   - `cuts` / `cut_tolerance`：切点真值
   - `audio`：`{voice, music, sfx, bpm, key}`
2. 真值要有出处，写在 `source` 字段：生产记录（timeline.json、manifest、cues.py）> 平台 AIGC 标识 > 人工目测（目测的要写"存疑"）。
3. 跑 `rea-video eval eval/xxx.yaml -o out/eval_xxx`。只改分类规则时不用重新解码：评测会用缓存特征重新分类；改了测量视频的代码（解码、切镜、特征、声音、包装）会自动重新解码，不会拿旧特征给新代码打分（`--fresh` 全部重来，`--only id` 只重解指定视频）。清单里的路径找不到时会用 `eval/media/<id>.<扩展名>` 里的备份，仍然缺的会在摘要的 `missing` 里列出。摘要里的 `by_resolution` / `by_camera` 按分辨率档和运镜拆开准确率和误判方向，改规则前后对比看错误是不是集中在某类画面上。
4. 调规则要防止过拟合：至少保留一组**改规则之后才第一次跑**的留出集，结果写进 `eval/RESULTS.md`。

## 转场和说话人的基准

这两项没有现成的带标注视频，用已知答案的合成样本测：

```bash
# 转场：从给定视频里取画面平稳的镜头，两两拼上 47 种转场（ffmpeg xfade 加自己合成的甩镜 / 旋转 / 缩放 / 故障 / 抖动 / 模糊），
# 每种 0.3 / 0.6 / 1.0 秒。找到 = 只报一处边界且落在转场内；类型对 = 报的类型属于该转场所在的族
python3 scripts/bench_transitions.py a.mp4 b.mp4 c.mp4 --out out/bench_transitions --pairs 5

# 说话人：每条输入是一个人在说话的视频，干声切成 2–7 秒的片段轮流拼成对话，可叠配乐（--music）和抢话（--overlap）
python3 scripts/bench_speakers.py a.mp4 b.mp4 c.mp4 --out out/bench_speakers --music bgm.mp4
```

改了 `shots.py` / `transitions.py` 后两头都要看：合成基准看类型，`eval/film.yaml`、`koubo.yaml`、`daihuo.yaml` 的切点真值看真实视频上有没有多报少报。
评测算切点时，标注的切点落在某个转场的起止区间内就算找到（标注的人和检测器可能各取了半秒划像里的不同一帧）。

