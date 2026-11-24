"""rea-video command line."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .util import ASR_LANGS, LOG, OCR_LANGS, load_env_files, read_json, setup_logging, read_image, write_json
from .i18n import LANGS, T, U, set_lang, set_ui_lang
from .classify import LABELS
from .vlm import vlm_note



def _env(args) -> None:
    from .memory import pref

    # 不读当前目录的 .env：在别人的仓库里运行时，它可以改 VLM 地址或 CAPSULE_CINEMA_PYTHON
    files = [Path(__file__).resolve().parent.parent / ".env"]
    explicit = getattr(args, "env_file", None)
    env_file = explicit or pref("env_file")
    if env_file:
        if not Path(env_file).expanduser().is_file():
            # silently skipping it made people think the VLM was configured
            msg = U("找不到配置文件 {p}", "env file not found: {p}", p=env_file)
            if explicit:
                raise SystemExit(f"rea-video: {msg}")
            LOG.warning("%s%s", msg, U("（来自 prefs env_file）", " (from prefs env_file)"))
        files.insert(0, Path(env_file).expanduser())
    loaded = load_env_files(files)
    if loaded:
        LOG.debug("env loaded from %s", loaded)


def _ocr_lang(args) -> None:
    """--ocr-lang (or prefs ocr_lang) -> $REA_OCR_LANG, which overlay.get_ocr reads."""
    from .memory import pref

    lang = getattr(args, "ocr_lang", None) or pref("ocr_lang")
    if lang:
        if lang not in OCR_LANGS:
            raise SystemExit(U(f"错误：不支持的 OCR 语言 {lang}（可选：{', '.join(OCR_LANGS)}）", f"error: unsupported OCR language {lang} (choose from: {', '.join(OCR_LANGS)})"))
        os.environ["REA_OCR_LANG"] = lang


def _asr_lang(args) -> None:
    """--asr-lang (or prefs asr_lang) -> $REA_ASR_LANG, which speech.transcribe reads."""
    from .memory import pref

    lang = getattr(args, "asr_lang", None) or pref("asr_lang")
    if lang:
        if lang not in ASR_LANGS:
            raise SystemExit(U(f"错误：不支持的语音识别语言 {lang}（可选：{', '.join(ASR_LANGS)}）", f"error: unsupported speech language {lang} (choose from: {', '.join(ASR_LANGS)})"))
        os.environ["REA_ASR_LANG"] = lang


def _check_vlm_config() -> None:
    """Fail fast on a misconfigured VLM: a typo in REA_VLM_MEDIA must not silently run text-only."""
    from .vlm import VLMConfig

    try:
        VLMConfig.from_env()
    except ValueError as exc:
        raise SystemExit(f"rea-video: {exc}")


def _vlm_client(out: Path):
    from .vlm import make_client

    client = make_client(out / "vlm_cache")
    if client is None:
        raise SystemExit(U("rea-video: --vlm 需要 GEMINI_API_KEY，或 REA_VLM_BASE_URL / REA_VLM_API_KEY / REA_VLM_MODEL",
                           "rea-video: --vlm needs GEMINI_API_KEY, or REA_VLM_BASE_URL / REA_VLM_API_KEY / REA_VLM_MODEL"))
    return client


def cmd_decompose(args) -> int:
    from .pipeline import decompose

    _ocr_lang(args)
    _asr_lang(args)

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    from .memory import pref

    meta = None
    if args.meta:
        s_meta = args.meta.strip()
        try:
            meta = json.loads(s_meta) if s_meta.startswith("{") else read_json(Path(s_meta))
        except (ValueError, OSError) as exc:
            raise SystemExit(U(f"rea-video: --meta 解析失败：{exc}", f"rea-video: invalid --meta: {exc}"))
    use_vlm = args.vlm or (pref("vlm") == "on" and not args.no_vlm)
    if use_vlm:
        _check_vlm_config()
    stems = not args.no_stems and pref("stems", "on") == "on"
    lang = args.lang or pref("lang", "zh")
    if lang not in LANGS:
        raise SystemExit(U(f"错误：不支持的报告语言 {lang}（可选：{', '.join(LANGS)}）", f"error: unsupported report language {lang} (choose from: {', '.join(LANGS)})"))
    b = decompose(args.video, out, use_vlm=use_vlm, whole_vlm=not args.no_whole, ocr=not args.no_ocr,
                  workers=args.workers, engine=args.engine or pref("engine"), platform_meta=meta, stems=stems,
                  packaging=not args.no_packaging, lang=lang, asr=not args.no_asr, max_shots_vlm=max(1, args.max_vlm_shots),
                  speakers=not args.no_speakers, survey=not args.no_survey, moments=not args.no_moments)
    print(json.dumps({"out": str(out), "verdict": b["summary"]["verdict"], "shots": b["summary"]["shots"],
                      "confidence": b["summary"]["confidence"], "vlm": b["summary"]["vlm"],
                      "report": str(out / "report.html")}, ensure_ascii=False, indent=2))
    return 0


def cmd_survey(args) -> int:
    from .media import video_info
    from .memory import pref
    from .shots import build_track, detect_shots
    from .survey import run, vlm_asker

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    info = video_info(args.video)
    track = build_track(str(args.video), info)
    asker = None
    if args.vlm or (pref("vlm") == "on" and not args.no_vlm):
        _check_vlm_config()
        from .vlm import prompt_lang_note

        asker = vlm_asker(_vlm_client(out), prompt_lang_note())
    res = run(Path(args.video).expanduser().resolve(), out.expanduser().resolve(), track, detect_shots(track), info,
              asker=asker, workers=args.workers, detail=not args.no_detail)
    if res["status"] == "waiting":
        res["next"] = U("看 images 里的图，按 tasks 里的问题把答案写进 waiting 里的文件（各文件互不相关，可以并发），再运行同一条命令",
                        "look at the images, answer the questions in tasks into the waiting files (independent: can run in parallel), then run the same command again")
    else:
        res["next"] = U("运行 rea-video decompose（同一个 -o），镜头按这次的切点切分，关键帧和节奏写进报告",
                        "run rea-video decompose (same -o): shots follow these cuts, key frames and rhythm go into the report")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_moments(args) -> int:
    """Special moments, coarse to fine: the stretches from the words and an overview, then the key frames of each."""
    import shutil

    from . import moments as mo
    from .memory import pref
    from .pipeline import finalize

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", "zh"))
    if args.redo and (out / "moments").is_dir():
        shutil.rmtree(out / "moments")
        b.get("moments", {}).pop("items", None)
        if "moments" in b:
            b["moments"]["status"] = "pending"
    m = b.setdefault("moments", {})
    track = None
    if ("hints" not in m or "measured" not in m) and Path(b["source"]["path"]).is_file():
        from .media import video_info
        from .shots import build_track

        track = build_track(b["source"]["path"], video_info(b["source"]["path"]))
    if "hints" not in m:
        voc = out / "stems" / "vocals.wav"
        m.update(genre=mo.genre(b), status="pending",
                 hints=mo.hints((b.get("speech") or {}).get("lines") or [], voc if voc.is_file() else None, track, b["source"]["duration"]))
    if "measured" not in m and track is not None:  # a breakdown from before the frame measurements
        fps = float(b["source"].get("fps") or track.fps or 30.0)
        skips = [(int(round(s["transition"]["start"] * fps)), int(round(s["transition"]["end"] * fps)))
                 for s in (b.get("shots") or [])[1:] if s.get("transition")]
        m["measured"] = mo.measured(track, [s["start_frame"] for s in (b.get("shots") or [])[1:]], skip=skips)
    asker = None
    if args.vlm or (pref("vlm") == "on" and not args.no_vlm):
        _check_vlm_config()
        from .vlm import prompt_lang_note

        asker = mo.vlm_asker(_vlm_client(out), prompt_lang_note())
    res = mo.run(b, out, asker=asker)
    if res["status"] == "waiting":
        res["next"] = T("看 images 里的图，按 tasks 里的说明把答案写进 waiting 里的文件（filled 改成 true），再运行同一条命令",
                        "look at the images, answer as the task says into the waiting file (set filled to true), then run the same command again")
        write_json(out / "breakdown.json", b, compact=True)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    finalize(b, out)
    from .moments import summary_line

    print(summary_line(b) or T("没有找到特殊时刻", "No special moments found"))
    for it in b["moments"].get("items") or []:
        f = it.get("files") or {}
        print(f"  {it['id']}: " + " ".join(f[k] for k in ("strip", "slow", "reveal", "clip") if f.get(k)))
    print(T("报告「特殊时刻」一节和 video/moments.md 已更新", "The report's “Special moments” section and video/moments.md are updated"))
    return 0


def cmd_review(args) -> int:
    """Write review_tasks.json + review_answers.json so a multimodal agent can act as the VLM."""
    from .review import build_tasks

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", "zh"))
    tasks, answers = build_tasks(b, str(out))
    from .util import dumps_rows

    (out / "review_tasks.json").write_text(dumps_rows(tasks), encoding="utf-8")
    ans_path = out / "review_answers.json"
    if args.force or not ans_path.is_file():
        ans_path.write_text(dumps_rows(answers), encoding="utf-8")
    high = [s for s in tasks["shots"] if s["priority"] == "high"]
    print(U(f"{len(tasks['shots'])} 个镜头待看图复核，其中 {len(high)} 个优先：", f"{len(tasks['shots'])} shots to review by eye, {len(high)} first: ") + ", ".join(f"{s['id']}({'; '.join(s['why'])})" for s in high))
    print(U("说明和图片路径：", "Instructions and image paths: ") + str(out / 'review_tasks.json'))
    print(U("把答案填进：", "Write answers to: ") + str(ans_path))
    print(U(f"然后运行：rea-video apply-review {out} --by <你的名字>", f"Then run: rea-video apply-review {out} --by <your name>"))
    return 0


def cmd_apply_review(args) -> int:
    from .pipeline import finalize
    from .review import apply_answers

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    if args.lang:
        b["lang"] = args.lang
    set_lang(b.get("lang", "zh"))
    answers = read_json(Path(args.answers) if args.answers else out / "review_answers.json")
    from .memory import pref

    log = apply_answers(b, answers, by=args.by or pref("reviewer"))
    b = finalize(b, out)
    for p in log["problems"]:
        print(U(f"跳过 {p}", f"skipped {p}"))
    if log.get("unanswered"):
        print(U(f"没作答、已跳过 {len(log['unanswered'])} 个镜头", f"skipped {len(log['unanswered'])} unanswered shots"))
    changed = [(r["id"], log["before"][r["id"]], r["base"]["label"]) for r in b["shots"]
               if r["id"] in log["before"] and log["before"][r["id"]] != r["base"]["label"]]
    print(U(f"已并入 {len(log['applied'])}/{len(b['shots'])} 个镜头；改判 {len(changed)} 个", f"merged {len(log['applied'])}/{len(b['shots'])} shots, {len(changed)} changed") +
          (U("：", ": ") + ", ".join(f"{i} {a}→{c}" for i, a, c in changed) if changed else ""))
    print(U("结论: ", "Verdict: ") + b['summary']['verdict'])
    print(f"VLM: {b['summary']['vlm']}")
    if log.get("packaging"):
        print(U("已并入包装复核：", "Merged packaging review: ") + ", ".join(f"{k} {n}" for k, n in log["packaging"].items()))
    if not log["applied"] and not log.get("packaging") and not log["problems"]:
        print(U("答案文件里没有可并入的镜头（先按 review_tasks.json 填 review_answers.json）", "no shots to merge in the answers file (fill review_answers.json following review_tasks.json first)"))
    return 0 if log["applied"] or log.get("packaging") else 1


def cmd_stems(args) -> int:
    from .stems import extract_stems

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    print(json.dumps(extract_stems(args.video, out), ensure_ascii=False, indent=2))
    return 0


def cmd_probe(args) -> int:
    from .media import require_tools, video_info
    from .probe import provenance

    require_tools(("ffprobe",))
    info = video_info(args.video)
    p = provenance(info)
    p.pop("tags", None) if not args.tags else None
    print(json.dumps({"width": info.width, "height": info.height, "fps": info.fps, "duration": info.duration,
                      "vcodec": info.vcodec, "aspect_ratio": info.aspect_ratio, "provenance": p}, ensure_ascii=False, indent=2))
    return 0


def cmd_eval(args) -> int:
    from .evaluate import evaluate

    _ocr_lang(args)

    if args.vlm:
        _check_vlm_config()
    res = evaluate(Path(args.labels), Path(args.out), use_vlm=args.vlm, ocr=not args.no_ocr, reuse=not args.fresh,
                   only=set(args.only.split(",")) if args.only else None, stems=args.stems)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=2))
    gone = res["summary"].get("missing")
    if gone:
        print("rea-video: " + U("只评了 {n}/{m} 个样本，其余找不到文件：{ids}", "scored {n} of {m} videos, files missing for: {ids}",
                                  n=res["summary"]["videos"], m=res["summary"]["videos_listed"], ids=", ".join(gone)), file=sys.stderr)
    return 0


def cmd_videomd(args) -> int:
    from .videomd import write

    root = Path(args.out_dir)
    if args.check:
        from .videomd import check

        errs = check(root)
        print("\n".join(errs) if errs else T("符合 VIDEO.md 规范", "conforms to the VIDEO.md spec"))
        return 1 if errs else 0
    b = read_json(root / "breakdown.json")
    set_lang(b.get("lang", "zh"))
    print(write(b, root))
    return 0


def cmd_clean_paths(args) -> int:
    from .clean_paths import clean_paths

    rows = clean_paths(Path(args.dir), apply=args.apply)
    changed = [r for r in rows if r["cleaned"]]
    kept = [r for r in rows if r["kept"]]
    for r in changed:
        print(f"{'cleaned' if args.apply else 'would clean'} {r['package']}: {', '.join(r['cleaned'])}")
    for r in kept:
        print(f"still has local paths {r['package']}: {', '.join(r['kept'])}")
    for r in rows:
        if r["error"]:
            print(f"failed {r['package']}: {r['error']}", file=sys.stderr)
    print(T("{n} 个包，{c} 个{v}，{k} 个仍含运行时要用的本机路径（分享前别带上这些文件）",
            "{n} packages, {c} {v}, {k} still hold local paths a later step needs (leave those files out when sharing)",
            n=len(rows), c=len(changed), v=T("已清理", "cleaned") if args.apply else T("待清理（加 --apply 执行）", "to clean (add --apply)"), k=len(kept)))
    return 1 if any(r["error"] for r in rows) else 0


def cmd_pdf(args) -> int:
    from .pdf import write_pdf

    try:
        print(write_pdf(Path(args.out_dir)))
    except RuntimeError as e:
        print(f"rea-video: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_capsule(args) -> int:
    from .integrations.capsule_cinema import export_capsule_analysis

    b = read_json(Path(args.breakdown))
    out = export_capsule_analysis(b, Path(args.out) if args.out else Path(args.breakdown).with_name("capsule_analysis.json"))
    print(out)
    return 0


def _capsule_root(args, check: bool = True) -> Path:
    from .memory import capsule_root

    root = capsule_root(args.capsule_root)
    if check and not root.is_dir():
        raise SystemExit(U(f"找不到 capsule-cinema 仓库：{root}。用 --capsule-root 指定，或 rea-video prefs capsule_root <路径> 设成默认",
                           f"capsule-cinema repo not found: {root}. Pass --capsule-root, or set it once with: rea-video prefs capsule_root <path>"))
    return root


def cmd_remake_plan(args) -> int:
    from .integrations.capsule_cinema import build_remake_jobs

    bdir = Path(args.breakdown).parent
    root = _capsule_root(args)
    try:  # the jobs are the remake plan's units as they stand: change the model or the swaps with `rea-video plan`
        jobs = build_remake_jobs(read_json(Path(args.breakdown)), bdir, capsule_root=root)
    except ValueError as exc:
        print(f"rea-video: {exc}", file=sys.stderr)
        return 2
    print(jobs)
    return 0


def _capsule_python(explicit: str | None, capsule_root: Path) -> str:
    """capsule-cinema 的解释器：--python > $CAPSULE_CINEMA_PYTHON > <capsule-root>/.venv/bin/python > 当前解释器。"""
    if explicit or os.getenv("CAPSULE_CINEMA_PYTHON"):
        return explicit or os.environ["CAPSULE_CINEMA_PYTHON"]
    venv = capsule_root.expanduser() / ".venv/bin/python"
    return str(venv) if venv.is_file() else sys.executable


def _run_integration(script: str, python: str, argv: list[str]) -> int:
    import subprocess

    path = Path(__file__).resolve().parent / "integrations" / script
    return subprocess.call([python, str(path), *argv])


def _capsule_command(args, argv: list[str]) -> int:
    """Generation, assembly and checks belong to Capsule Cinema: run its command in its own environment."""
    import subprocess

    from .memory import capsule_root

    # capsule-root 只认命令行和用户配置（jobs.json 可能是别人给的，不能让它决定跑哪个解释器、import 哪里的代码）
    root = capsule_root(getattr(args, "capsule_root", None))
    script = root / "scripts" / "remake_reference.py"
    if not script.is_file():
        raise SystemExit(U("生成、拼接和验收由 Capsule Cinema 负责，但没找到它：{r}。安装 https://github.com/JuneYaooo/capsule-cinema ，"
                           "再用 --capsule-root 指定，或运行 rea-video prefs capsule_root <路径>",
                           "Capsule Cinema does the generation, assembly and checks, but it was not found at {r}. Install "
                           "https://github.com/JuneYaooo/capsule-cinema , then pass --capsule-root or run: rea-video prefs capsule_root <path>", r=root))
    return subprocess.call([_capsule_python(getattr(args, "python", None), root), str(script), *argv], cwd=root)


def cmd_remake_run(args) -> int:
    jobs = Path(args.jobs).expanduser().resolve()
    return _capsule_command(args, ["run", str(jobs)] + (["--only", args.only] if args.only else []) + (["--dry-run"] if args.dry_run else []))


def cmd_capsule_draft(args) -> int:
    root = _capsule_root(args)
    argv = ["--breakdown", str(Path(args.breakdown).expanduser().resolve()), "--capsule-root", str(root)]
    argv += ["--capsule-name", args.capsule_name] if args.capsule_name else []
    argv += ["--capsule-display-name", args.capsule_display_name] if args.capsule_display_name else []
    argv += ["--write-capsule"] if args.write_capsule else []
    argv += ["--overwrite-capsule"] if args.overwrite_capsule else []
    argv += ["--keep-source-text"] if args.keep_source_text else []
    return _run_integration("to_capsule.py", _capsule_python(args.python, root), argv)


def cmd_assemble(args) -> int:
    pkg = Path(args.breakdown).expanduser().resolve().parent
    argv = ["assemble", str(pkg), "--results", str(Path(args.results).expanduser().resolve())]
    argv += ["-o", str(Path(args.out).expanduser().resolve())] if args.out else []
    return _capsule_command(args, argv + ([] if args.overlays else ["--no-overlays"]))


def cmd_tiles(args) -> int:
    """Time-labelled frame grid for close inspection of a passage."""
    import cv2
    import numpy as np

    from .media import extract_frame, video_info
    from .visual import shot_sheet

    # bad numbers used to die deep inside numpy / PIL with a traceback, or silently print an empty result
    if args.every <= 0:
        raise SystemExit(U("rea-video: --every 必须大于 0（两次抽帧的间隔秒数）", "rea-video: --every must be greater than 0 (seconds between frames)"))
    if Path(args.video).is_dir() and (Path(args.video) / "breakdown.json").is_file():
        args.video = read_json(Path(args.video) / "breakdown.json")["source"]["path"]  # a package: its source video
    if args.start < 0:
        raise SystemExit(U("rea-video: --start 不能小于 0", "rea-video: --start cannot be negative"))
    if args.cols < 1:
        raise SystemExit(U("rea-video: --cols 至少为 1", "rea-video: --cols must be at least 1"))
    if args.max < 1:
        raise SystemExit(U("rea-video: --max 至少为 1", "rea-video: --max must be at least 1"))
    if args.cell < 1:
        raise SystemExit(U("rea-video: --cell 至少为 1", "rea-video: --cell must be at least 1"))
    info = video_info(args.video)
    end = args.end if args.end is not None else info.duration
    if args.start >= end:
        raise SystemExit(U(f"rea-video: --end 必须大于 --start（视频时长 {info.duration:.2f} 秒）", f"rea-video: --end must be after --start (video is {info.duration:.2f} s)"))
    times = list(np.arange(args.start, end, args.every))[: args.max]
    import tempfile

    focus_box = None
    if getattr(args, "focus", None):
        try:
            vals = [float(v) for v in str(args.focus).replace("，", ",").split(",")]
        except ValueError:
            vals = []
        if len(vals) != 4 or not (0.0 <= vals[0] < vals[2] <= 1.0 and 0.0 <= vals[1] < vals[3] <= 1.0):
            raise SystemExit(U("rea-video: --focus 必须是 0–1 之间的 x0,y0,x1,y1（且 x0<x1, y0<y1）",
                               "rea-video: --focus must be x0,y0,x1,y1 in 0..1 with x0<x1 and y0<y1"))
        focus_box = vals
    frames, kept_times = [], []
    with tempfile.TemporaryDirectory() as tmpd:
        for i, t in enumerate(times):
            if focus_box:  # a region of the frame, enlarged to the cell width (x0,y0,x1,y1 in 0-1)
                x0, y0, x1, y1 = focus_box
                p = extract_frame(args.video, float(t), Path(tmpd) / f"tile_{i:03d}.jpg")
                img = read_image(p)
                if img is not None:
                    h, w = img.shape[:2]
                    img = img[int(y0 * h):max(int(y0 * h) + 2, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 2, int(x1 * w))]
                    img = cv2.resize(img, (args.cell, max(2, int(args.cell * img.shape[0] / max(1, img.shape[1])))), interpolation=cv2.INTER_CUBIC)
            else:
                p = extract_frame(args.video, float(t), Path(tmpd) / f"tile_{i:03d}.jpg", width=args.cell)
                img = read_image(p)
            if img is not None:
                if getattr(args, "grid", False):  # tenths of the whole frame, for placing a point (x, y in 0-1, top left 0,0)
                    h, w = img.shape[:2]
                    for k in range(1, 10):
                        x, y = int(w * k / 10), int(h * k / 10)
                        cv2.line(img, (x, 0), (x, h), (0, 255, 255), 1)
                        cv2.line(img, (0, y), (w, y), (0, 255, 255), 1)
                        cv2.putText(img, f".{k}", (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
                        cv2.putText(img, f".{k}", (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
                frames.append(img)
                kept_times.append(float(t))
    rows = [frames[i:i + args.cols] for i in range(0, len(frames), args.cols)]
    paths = []
    for r, row in enumerate(rows):
        out = Path(args.out) if len(rows) == 1 else Path(args.out).with_name(f"{Path(args.out).stem}_{r + 1}{Path(args.out).suffix}")
        shot_sheet(row, kept_times[r * args.cols:(r + 1) * args.cols], out, n=len(row), cell_w=args.cell)
        paths.append(str(out))
    print(json.dumps({"tiles": paths, "times": [round(float(t), 3) for t in kept_times]}, ensure_ascii=False))
    return 0


def cmd_frames(args) -> int:
    from .layers import scene_frames

    if args.every <= 0:
        raise SystemExit(U("rea-video: --every 必须大于 0", "rea-video: --every must be greater than 0"))
    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(U(f"rea-video: {out} 下没有 breakdown.json，先运行 decompose", f"rea-video: no breakdown.json in {out}, run decompose first"))
    res = scene_frames(out, every=args.every, n_points=args.points, all_shots=args.all)
    if not res["scenes"]:
        print(T("没有代码渲染镜头（加 --all 对所有镜头取帧）", "no code-rendered shots (add --all to cover every shot)"))
        return 0
    print(json.dumps({"scenes": len(res["scenes"]), "file": str(out / "frames" / "scenes.json"),
                      "cuts": [s["start"] for s in res["scenes"]]}, ensure_ascii=False))
    return 0


def cmd_compare(args) -> int:
    from .layers import compare

    if args.every <= 0:
        raise SystemExit(U("rea-video: --every 必须大于 0", "rea-video: --every must be greater than 0"))
    for p in (args.ref, args.remake):
        if not Path(p).is_file():
            raise SystemExit(U(f"rea-video: 找不到 {p}", f"rea-video: not found: {p}"))
    res = compare(args.ref, args.remake, every=args.every, out=Path(args.out) if args.out else None,
                  scenes=Path(args.scenes) if args.scenes else None, worst=args.worst)
    brief = {k: res[k] for k in ("score", "place", "shape", "offset", "advice", "worst") if k in res}
    if res.get("scenes"):
        brief["lowest_scenes"] = res["scenes"][:5]
    if res.get("sheet"):
        brief["sheet"] = res["sheet"]
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


def cmd_remake(args) -> int:
    """The plan is rea-video's; Capsule Cinema takes it from there (stills, clips in, assembly, status, check)."""
    out = Path(args.out_dir).expanduser().resolve()
    if not (out / "breakdown.json").is_file():
        raise SystemExit(U(f"rea-video: {out} 下没有 breakdown.json，先运行 decompose", f"rea-video: no breakdown.json in {out}, run decompose first"))
    if args.code:
        from .code_remake import code_remake

        b = read_json(out / "breakdown.json")
        if any(sh["base"]["label"] == "code_render" for sh in b["shots"]) and not (out / "code" / "remake.mp4").is_file():
            try:
                code_remake(out)
            except (ValueError, OSError, RuntimeError) as exc:
                print(f"rea-video: code-remake: {exc}", file=sys.stderr)
    args.breakdown = str(out / "breakdown.json")
    args.capsule_root = getattr(args, "capsule_root", None)
    root = _capsule_root(args)
    args.capsule_root = str(root)
    rc = cmd_remake_plan(args)
    if rc:
        return rc
    return _capsule_command(args, ["assemble", str(out)] + (["--no-overlays"] if args.no_overlays else []))


def cmd_code_remake(args) -> int:
    from .code_remake import code_remake

    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(U(f"rea-video: {out} 下没有 breakdown.json，先运行 decompose", f"rea-video: no breakdown.json in {out}, run decompose first"))
    try:
        res = code_remake(out, reset=args.reset, render=not args.no_render, score=not args.no_compare)
    except ValueError as e:
        raise SystemExit(f"rea-video: {e}")
    res.pop("matched", None)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_drive(args) -> int:
    from .drive import drive, join

    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(U(f"rea-video: {out} 下没有 breakdown.json，先运行 decompose", f"rea-video: no breakdown.json in {out}, run decompose first"))
    try:
        if args.join is not None:
            res = join(out, Path(args.join) if args.join else None)
        else:
            shots = None
            if args.shots:
                shots = []
                for part in args.shots.split(","):
                    a, _, z = part.strip().partition("-")
                    shots += list(range(int(a), int(z or a) + 1))
            res = drive(out, shots=shots, depth=args.depth, clean=not args.no_clean, prefer=args.prefer, max_s=args.max)
            res = {k: v for k, v in res.items() if k != "segments"} | {"segments": [
                {k: s[k] for k in ("id", "start", "end", "duration", "cut_in", "cuts_inside")} for s in res["segments"]],
                "readme": str(out / "drive" / "README.md")}
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(f"rea-video: {e}")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_summary(args) -> int:
    """Compact, agent-friendly view of a breakdown (instead of reading the whole JSON)."""
    from .i18n import T, join

    b = read_json(Path(args.breakdown))
    set_lang(b.get("lang", "zh"))
    s = b["summary"]
    lines = [f"{b['source']['filename']} | {b['source']['duration']}s {b['source']['width']}x{b['source']['height']} {b['source']['fps']}fps",
             f"{T('结论', 'Verdict')}: {s['verdict']}", f"{T('置信度', 'Confidence')}: {s['confidence']}", f"VLM: {s.get('vlm') or vlm_note(b['analysis']['vlm'])}", ""]
    from . import narrative

    steps = narrative.beats(b)
    if steps:
        lines[-1:-1] = [T("叙事线", "Narrative") + ": " + " → ".join(
            f"#{s['shots'][0]}" + (f"-{s['shots'][-1]}" if len(s['shots']) > 1 else "") + f" {s['role_zh'] or (s['points'] or ['?'])[0][:16]}" for s in steps)]
    vc = b.get("video_context") or {}
    if vc.get("transcoded"):
        lines.append(T("平台转码: {p}（噪声类证据失效；原生 30fps 无重复帧: {n}）", "Platform transcode: {p} (noise evidence unusable; native 30fps without duplicate frames: {n})",
                       p=join(vc.get("platform", [])), n=vc.get("native30")))
    prov = b.get("provenance", {})
    if prov.get("aigc") or prov.get("hints"):
        lines.append(f"{T('元数据', 'Metadata')}: aigc={prov.get('aigc')} hints={prov.get('hints')}")
    from .aspects import shot_text
    from .memory import hint_for, patterns

    pats = patterns()
    low_n = sum(r["base"]["confidence"] < 0.6 for r in b["shots"])
    mark_low = low_n <= len(b["shots"]) / 2  # when most shots are low, one line says so instead of a tag on every row
    if not mark_low:
        sure = [str(r["index"]) for r in b["shots"] if r["base"]["confidence"] >= 0.6]
        lines.append(T("低置信: {n}/{m} 镜置信度 <0.6，都要复核", "Low confidence: {n}/{m} shots below 0.6, review them all", n=low_n, m=len(b["shots"]))
                     + (T("（只有 #{s} 不用）", " (all but #{s})", s=",".join(sure)) if sure else ""))
    notes: list[str] = []  # the same "待确认" sentence repeats across shots: number it, print each once below the table

    def note_ref(text: str) -> str:
        if text not in notes:
            notes.append(text)
        return T("待确认{i}", "open question {i}", i="①②③④⑤⑥⑦⑧⑨⑩"[notes.index(text)] if notes.index(text) < 10 else f"({notes.index(text) + 1})")

    for r in b["shots"]:
        base = r["base"]
        alt = next((kv for kv in sorted(base["probs"].items(), key=lambda kv: -kv[1]) if kv[0] != base["label"]), ("-", 0.0))
        det = r["deterministic"]["probs"]
        past = None if base["decided_by"] == "user" or r.get("review") else hint_for(max(det, key=det.get), pats)  # looked at: settled
        mat = (r.get("material") or {}).get("origin_zh", "")
        second = T("(用户纠正)", "(user correction)") if base["decided_by"] == "user" else T("(次选 {l} {p:.2f})", "(runner-up {l} {p:.2f})", l=alt[0], p=alt[1])
        lines.append(f"#{r['index']:>2} {r['start']:7.2f}-{r['end']:7.2f} {base['label']:<14} {base['confidence']:.2f} {second} "
                     f"| {T('素材', 'material')}:{mat} | {T('叠加', 'overlays')}:{','.join(sorted({l['kind'] for l in r.get('layers', [])})) or '-'} | {r['features'].get('camera')}"
                     + (T("  ← 低置信，需要复核", "  ← low confidence, review it") if mark_low and base["confidence"] < 0.6 else "")
                     + (f"  ← {note_ref(base['uncertain'])}" if base.get("uncertain") else "")
                     + (T("  ← 有分歧：{d}", "  ← disputed: {d}", d=base["disputed"]) if base.get("disputed") else "")
                     + (T("  ← 用户纠正过素材来源", "  ← material origin corrected by the user") if (r.get("material") or {}).get("user_corrected") else "")
                     + (f"  ← {past}" if past else "")
                     + (f" | {shot_text(r, brief=True)}" if r["base"]["label"] in ("live_action", "avatar") and shot_text(r, brief=True) else "")
                     + (T(" | 动效 {n} 个，元素截图 {f}", " | {n} motion events, element crops {f}", n=len(r["motion"].get("events", [])),
                          f=r["motion"]["elements_sheet"]) if r["base"]["label"] in ("code_render", "screen_capture")
                        and (r.get("motion") or {}).get("elements_sheet") else ""))
    if notes:
        lines += [f"{note_ref(n)}: {n}" for n in notes]
    if s.get("aspects"):
        lines += [""] + s["aspects"]
    from .entities import cast

    c = cast(b)
    if c["characters"] or c["scenes"]:
        lines.append("")
        for ch in c["characters"]:
            lines.append(f"{T('角色', 'Character')} {ch['id']} {ch['name']} | {ch['look']} | {T('镜头', 'shots')} {','.join(str(i) for i in ch['shots']) or '-'}")
        for sc in c["scenes"]:
            lines.append(f"{T('场景', 'Scene')} {sc['id']} {sc['where']} {sc['when']} | {sc['look']} | {T('镜头', 'shots')} {','.join(str(i) for i in sc['shots']) or '-'}")
    a = b.get("audio", {})
    if a.get("has_audio"):
        mu = a.get("music", {})
        lines += ["", f"{T('人声', 'Voice')}: {a.get('voice', {}).get('present')} ({a.get('voice', {}).get('ratio')}) | {T('音乐', 'Music')}: {mu.get('present')} "
                      f"{(T('无明显节拍', 'no beat') if mu.get('no_beat') else (str(mu['tempo_bpm']) + 'BPM' if mu.get('tempo_bpm') is not None else ''))} {(mu.get('key') or {}).get('tonic', '')}{(mu.get('key') or {}).get('mode', '')} | "
                      f"{T('音效', 'SFX')}: {_sfx_count(b)} | {T('卡点', 'beat-synced')}: {a.get('beat_synced_edit')}"]
        if (b.get("sound_sources") or {}).get("summary_zh"):
            lines.append(f"{T('声音来源', 'Sound sources')}: " + b["sound_sources"]["summary_zh"])
        if (b.get("stems") or {}).get("ok"):
            lines.append(T("音轨: stems/original.wav（原声） stems/vocals.wav（人声） stems/music.wav（配乐）",
                           "Stems: stems/original.wav (original) stems/vocals.wav (voice) stems/music.wav (music)"))
    pk = b.get("packaging")
    if pk:
        tag = T("包装", "Packaging")
        lines += [""] + [f"{tag}: {x}" for x in (pk.get("summary_zh") or [T("没有检出后期叠加的文字或贴纸", "no overlaid text or stickers detected")])]
        low = [st for st in pk.get("stickers", []) if not st.get("in_picture") and st.get("confidence") in ("low", "vlm")]
        if low:
            lines.append(f"{tag}: " + T("需要看图确认的贴纸 ", "stickers to confirm by eye ") + join(f"{st['id']} {st['t0']:.1f}-{st['t1']:.1f}s" for st in low)
                         + T("（截图在 packaging/）", " (crops under packaging/)"))
        if pk.get("files"):
            lines.append(f"{T('包装文件', 'Packaging files')}: " + " ".join(pk["files"].values()))
    from .moments import summary_line

    ml = summary_line(b)
    if ml:
        lines += ["", ml, T("（关键帧和片段在 moments/，说明见 video/moments.md）", "(key frames and clips under moments/, see video/moments.md)")]
    elif (b.get("moments") or {}).get("status") == "pending" and b["moments"].get("genre") in ("magic", "drama"):
        lines += ["", T("特殊时刻: 还没找（`rea-video moments <目录>`）", "Special moments: not looked for yet (`rea-video moments <dir>`)")
                  + (T("；这是魔术视频，建议找", "; a magic video: worth doing") if b["moments"].get("genre") == "magic" else "")]
    print("\n".join(lines))
    return 0


def _sfx_count(b: dict) -> str:
    sfx = (b.get("audio_plan") or {}).get("sfx_merged", [])
    maybe = sum(1 for e in sfx if e.get("confidence") == "low")
    sure = len(sfx) - maybe
    return f"{sure}" + (T(" + 可能 {m}（待确认）", " + {m} possible (unconfirmed)", m=maybe) if maybe else "")


def cmd_correct(args) -> int:
    """The user says a shot is wrong: fix this breakdown and remember the correction."""
    from .memory import correct
    from .pipeline import finalize

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", "zh"))
    real = None if args.real is None else args.real == "yes"
    try:
        logged = correct(b, label=args.label, real=real, shots=args.shots, start=args.start, end=args.end, note=args.note or "")
    except ValueError as e:
        print(U(f"错误：{e}", f"error: {e}"), file=sys.stderr)
        return 2
    b = finalize(b, out)
    changed = [f"{c['shot']} {c['before']}→{c['label']}" for c in logged if c.get("label") and c["before"] != c["label"]]
    print(U(f"已纠正 {len(logged)} 个镜头", f"corrected {len(logged)} shots") + ((U("：", ": ") + ", ".join(changed)) if changed else "") + U("，并记入记忆", " and saved to memory"))
    print(U("结论: ", "Verdict: ") + b['summary']['verdict'])
    return 0


def cmd_plan(args) -> int:
    """The remake part of the report, from the remake intent (remake/intent.yaml: model, generate all or only the AI
    shots, what is swapped for what). The breakdown itself is not touched."""
    from .generation import load_intent, save_intent
    from .integrations.capsule_cinema import ref_clips
    from .pipeline import finalize
    from .plan import CAP, Planner, user_capabilities
    from .production import _norm, pick_model

    out = Path(args.out_dir)
    intent = load_intent(out)
    if args.model:
        intent["model"] = args.model
    if args.generate:
        intent["generate"] = args.generate
    if not intent.get("model"):
        from .generation import DEFAULT_MODEL
        from .memory import pref

        intent["model"] = pref("engine") or DEFAULT_MODEL
    pl = Planner()
    live = {k: x for k, x in pl.models.items() if x.get("status") not in ("shutdown", "deprecated")}
    m = next((x for x in live.values() if _norm(x["id"]) == _norm(intent["model"]) or _norm(x.get("name", "")) == _norm(intent["model"])), None)
    if m and not (m.get("category") == "video" and {"video.t2v", "video.i2v_first_frame"} & set(m.get("primitives", []))):
        print(U(f"rea-video: {m['id']} 不是视频生成模型（需要支持文生视频或首帧生视频）。可选生视频模型：rea-video models",
                f"rea-video: {m['id']} is not a video generation model (needs text-to-video or first-frame image-to-video). Available models: rea-video models"), file=sys.stderr)
        return 2
    if not m:
        target = user_capabilities() / 'models' / (re.sub(r'[^a-z0-9.-]+', '-', intent['model'].lower()) + '.yaml')
        print(U(f"rea-video: 能力地图里没有 {intent['model']}。先查这个模型的官方文档（单次时长、能不能吃参考视频 / 参考图和各几个、"
                f"能不能一次出多镜头、首尾帧、原生音频、提示词写法），按 {CAP / 'models' / 'video.yaml'} 的格式写进 {target}，再跑一次。"
                "已有的模型：rea-video models",
                f"rea-video: {intent['model']} is not in the capability map. Check its official docs (clip length, reference videos / images and how many, "
                f"multi-shot, first and last frame, native audio, prompt style), add it to {target} in the format of {CAP / 'models' / 'video.yaml'}, "
                "and run again. Known models: rea-video models"), file=sys.stderr)
        return 2
    intent["model"] = m["id"]
    save_intent(out, intent)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", "zh"))
    b = finalize(b, out, engine=m["id"])
    plan = b.get("production_plan") or {}
    n = sum(len(ref_clips(b, out, u)) for u in plan.get("units") or [])
    v = m.get("verified") or {}
    print(T("复刻方案已按 {m} 重出（报告第二部分）：{p}", "Remake plan redone for {m} (part two of the report): {p}",
            m=m["id"], p=b["summary"].get("production", "")))
    if n:
        print(T("原片参考 {n} 个（已擦掉字幕）：{d}", "{n} source references (subtitles erased): {d}", n=n, d=out / "remake" / "refs"))
    print(T("模型资料：{src}，核实于 {d}", "Model facts: {src}, checked {d}", src=T("本地补充", "local addition") if m.get("local") else T("能力地图", "capability map"), d=v.get("date") or "?"))
    from .generation import check_lines

    cs = plan.get("checks") or []
    if cs:
        print(T("方案检查：", "Plan checks:"))
        print("\n".join(check_lines(cs)))
    return 1 if any(c["level"] == "error" for c in cs) else 0


def cmd_models(args) -> int:
    """List the generation models the capability map knows, or print how to write prompts for one of them."""
    from .plan import Planner
    from .production import _norm, prompting_md

    pl = Planner()
    live = {k: m for k, m in pl.models.items() if m.get("status") not in ("shutdown", "deprecated")}
    if not args.model:
        for cat, title in (("video", U("视频", "Video")), ("image", U("图像（出首帧 / 关键帧）", "Image (first / key frames)")), ("character", U("人物驱动", "Character driving"))):
            print(f"{title}:")
            for mid, m in live.items():
                if m["category"] == cat:
                    lim = (m.get("limits") or {}).get("duration_s") or {}
                    extra = [f"≤{lim['max']:g}s" if lim.get("max") else "", U("一次多镜头", "multi-shot") if "video.multi_shot" in m["primitives"] else "",
                             U("有提示词写法", "prompt guide") if mid in pl.prompting else ""]
                    print(f"  {mid:22s} {m['name']}" + ("  · " + " · ".join(x for x in extra if x) if any(extra) else ""))
        print(U("\n看某个模型的提示词写法：rea-video models <id>；关键帧通用做法：rea-video models keyframes", "\nPrompt guide for a model: rea-video models <id>; general key-frame guide: rea-video models keyframes"))
        return 0
    if args.model == "keyframes":
        print(U("关键帧通用做法：\n", "General key-frame guide:\n") + "\n".join(f"- {x}" for x in pl.keyframe_notes))
        return 0
    m = next((x for x in live.values() if _norm(x["id"]) == _norm(args.model)), None)
    if not m:
        print(U(f"rea-video: 能力地图里没有 {args.model}；rea-video models 列出全部", f"rea-video: {args.model} is not in the capability map; rea-video models lists all"), file=sys.stderr)
        return 2
    lim = m.get("limits") or {}
    d = lim.get("duration_s") or {}
    facts = [U(f"单次 {d.get('min', 0):g}–{d['max']:g}s", f"{d.get('min', 0):g}–{d['max']:g}s per clip") if d.get("max") else "", U("可一次多镜头", "multi-shot") if "video.multi_shot" in m["primitives"] else "",
             U("首帧", "first frame") if "video.i2v_first_frame" in m["primitives"] else "", U("首尾帧", "first + last frame") if "video.i2v_first_last" in m["primitives"] else "",
             U("多参考", "multi-reference") if "video.multi_reference" in m["primitives"] else "", U("参考视频", "reference video") if "video.reference_video" in m["primitives"] else "",
             U("原生音频", "native audio") if (m.get("audio") or {}).get("native") else ""]
    print(f"{m['id']} · {m['name']}" + (" · " + " · ".join(x for x in facts if x) if any(facts) else ""))
    notes = pl.prompting.get(m["id"])
    if not notes:
        print(U("这个模型还没有记录提示词写法，按通用规则写。", "No prompt guide recorded for this model yet; follow the general rules."))
        return 0
    print("\n".join(prompting_md(notes, full=True)))
    if m["category"] == "video":
        print(U("\n关键帧通用做法：rea-video models keyframes", "\nGeneral key-frame guide: rea-video models keyframes"))
    return 0


def cmd_prefs(args) -> int:
    from .i18n import ui_lang
    from .memory import PREF_KEYS, PREF_KEYS_EN, add_note, load_prefs, remove_note, set_pref

    if args.key and args.value is None and "=" in args.key:  # also accept `prefs key=value`
        args.key, args.value = args.key.split("=", 1)
    if args.key and args.key not in PREF_KEYS:
        print(U(f"错误：未知偏好 {args.key}（可选：{', '.join(PREF_KEYS)}；用法 rea-video prefs <key> <value>）",
                f"error: unknown preference {args.key} (choose from: {', '.join(PREF_KEYS)}; usage: rea-video prefs <key> <value>)"), file=sys.stderr)
        return 2
    try:
        if args.note:
            add_note(args.note)
        elif args.remove_note:
            remove_note(args.remove_note)
        elif args.key and args.unset:
            set_pref(args.key, None)
        elif args.key and args.value is not None:
            set_pref(args.key, args.value)
        elif args.key:
            print(load_prefs().get(args.key, ""))
            return 0
    except ValueError as e:
        print(U(f"错误：{e}", f"error: {e}"), file=sys.stderr)
        return 2
    prefs = load_prefs()
    set_ui_lang(prefs.get("lang") if args.key == "lang" else ui_lang())  # `prefs lang en` answers in English right away
    for k, desc in (PREF_KEYS_EN if ui_lang() == "en" else PREF_KEYS).items():
        print(f"{k:<9} = {prefs.get(k, U('（未设置）', '(not set)'))}    # {desc}")
    for i, n in enumerate(prefs.get("notes", []), 1):
        print(U(f"说明 {i}: {n}", f"Note {i}: {n}"))
    return 0


def cmd_memory(args) -> int:
    from .memory import export_labels, summary_lines

    if args.export_labels:
        n = export_labels(Path(args.export_labels))
        print(U(f"已导出 {n} 条视频的纠正到 {args.export_labels}（先把 path 填好，再用 rea-video eval 评测）", f"exported corrections for {n} videos to {args.export_labels} (fill in path, then score with rea-video eval)"))
        return 0
    print("\n".join(summary_lines()))
    return 0


def _cli_lang(argv: list[str] | None) -> str | None:
    """CLI language: an explicit --lang, then $REA_VIDEO_LANG, then prefs lang."""
    from .memory import pref

    argv = sys.argv[1:] if argv is None else argv
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return os.environ.get("REA_VIDEO_LANG") or pref("lang")


def main(argv: list[str] | None = None) -> int:
    set_ui_lang(_cli_lang(argv))
    ap = argparse.ArgumentParser(prog="rea-video", description="逆向拆解视频：逐镜头判断实拍 / AI 生成 / 代码渲染 / 混合，并生成复刻方案")
    ap.add_argument("-v", "--verbose", action="store_true", help="输出调试日志与完整异常堆栈")
    ap.add_argument("--env-file", help="额外的 .env（例如 capsule-cinema/.env，用于 VLM 配置）")
    ap.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help="界面与输出语言：zh（默认）/ en")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decompose", help="拆解一条视频")
    d.add_argument("video")
    d.add_argument("-o", "--out")
    d.add_argument("--vlm", action="store_true", help="启用多模态大模型（VLM）看画面逐镜判断；建议开，不开也能跑，只是实拍/AI/3D 的区分更弱")
    d.add_argument("--no-vlm", action="store_true", help="本次不开 VLM（覆盖 prefs 里的 vlm=on）")
    d.add_argument("--no-whole", action="store_true", help="跳过整片结构/文案 VLM 分析")
    d.add_argument("--no-ocr", action="store_true", help="不做 OCR（字幕/花字时间轴也会跳过，只剩贴纸检测）")
    d.add_argument("--ocr-lang", choices=OCR_LANGS, help="字幕/花字的语言：zh 中英（默认）、en 纯英文、ja 日文、ko 韩文（后三种首次使用自动下载识别模型）；也可用 prefs ocr_lang 设成默认")
    d.add_argument("--no-packaging", action="store_true", help="跳过剪辑包装层（整片字幕时间轴、花字、贴纸/动图、音效卡点）；省掉约每分钟 30–50 秒")
    d.add_argument("--lang", choices=LANGS, help="报告、结论和 VLM 描述的语言：zh（默认）/ en；按用户提问的语言选，也可用 prefs lang 设成默认")
    d.add_argument("--workers", type=int, default=3)
    d.add_argument("--max-vlm-shots", type=int, default=60, help="最多发给 VLM 的调用数（默认 60；镜头更多时优先看最拿不准的，其余只靠确定性取证）")
    d.add_argument("--engine", help="复刻方案按哪个视频模型规划（rea-video models 列出的 id；默认 prefs 里的 engine，否则 minimax-h3）")
    d.add_argument("--meta", help='平台元数据 JSON，例如 {"music": {"title": "xx", "author": "yy", "is_original": false, "popular": true}}')
    d.add_argument("--no-asr", action="store_true", help="不做本地语音识别（装了 rea-video[asr] 才会做：在人声干声上识别台词和时间，首次使用下载约 160 MB 模型）")
    d.add_argument("--asr-lang", choices=ASR_LANGS, help="台词的语言：auto（默认，SenseVoice 自动识别中/英/日/韩/粤）、bn 孟加拉语（换用孟加拉语识别模型，首次使用自动下载约 90 MB）；也可用 prefs asr_lang 设成默认")
    d.add_argument("--no-speakers", action="store_true", help="不区分说话人（装了 rea-video[asr] 才会做：在人声干声上分出谁在什么时候说话，多人时每人输出一条 stems/voice_S1.wav；首次使用下载约 35 MB 模型）")
    d.add_argument("--no-survey", action="store_true", help="开 VLM 时也不做总览 + 局部细看（只用切镜检测器的切点）")
    d.add_argument("--no-stems", action="store_true", help="不做人声/配乐分离（默认会输出 stems/original.wav、vocals.wav、music.wav）")
    d.add_argument("--no-moments", action="store_true", help="不找特殊时刻（魔术揭秘、反转、高潮、穿帮）；开 VLM 时默认会找，约多 3–5 次调用")
    d.set_defaults(func=cmd_decompose)

    st = sub.add_parser("stems", help="只把声音剥离成 原声 / 人声 / 配乐 三条轨")
    st.add_argument("video")
    st.add_argument("-o", "--out")
    st.set_defaults(func=cmd_stems)

    p = sub.add_parser("probe", help="只看容器元数据/来源线索")
    p.add_argument("video")
    p.add_argument("--tags", action="store_true")
    p.set_defaults(func=cmd_probe)

    e = sub.add_parser("eval", help="在带标注的样本集上评测拆解准确率")
    e.add_argument("labels", help="labels.yaml")
    e.add_argument("-o", "--out", default="out/eval")
    e.add_argument("--vlm", action="store_true")
    e.add_argument("--no-ocr", action="store_true")
    e.add_argument("--ocr-lang", choices=OCR_LANGS, help="同 decompose --ocr-lang")
    e.add_argument("--fresh", action="store_true", help="不复用已有拆解结果")
    e.add_argument("--only", default="", help="只重新拆解这些 id（逗号分隔），其余复用缓存并重新分类")
    e.add_argument("--stems", action="store_true", help="对带音频真值的样本做人声分离，并在干声上重测唱/说")
    e.set_defaults(func=cmd_eval)

    c = sub.add_parser("capsule", help="导出 capsule-cinema 的视频分析 JSON（供生成胶囊草稿）")
    c.add_argument("breakdown")
    c.add_argument("-o", "--out")
    c.set_defaults(func=cmd_capsule)

    r = sub.add_parser("remake-plan", help="把复刻方案的生成单元写成 capsule-cinema 任务（模型和要换的东西在 rea-video plan 里定）")
    r.add_argument("breakdown")
    r.add_argument("--capsule-root", help="capsule-cinema 仓库；默认 $CAPSULE_CINEMA_ROOT、prefs capsule_root，再退到 ~/code/github/capsule-cinema")
    r.set_defaults(func=cmd_remake_plan)

    rr = sub.add_parser("remake-run", help="交给 Capsule Cinema 执行 remake-plan 生成的任务（会计费，先 --dry-run）")
    rr.add_argument("jobs", help="remake-plan 输出的 jobs.json")
    rr.add_argument("--capsule-root", help="须与 remake-plan 时一致；默认同 remake-plan")
    rr.add_argument("--dry-run", action="store_true", help="只列出任务和参数，不调用模型")
    rr.add_argument("--only", default="", help="只跑这些镜头（逗号分隔）")
    rr.add_argument("--python", help="capsule-cinema 的 Python；默认 $CAPSULE_CINEMA_PYTHON 或 <capsule-root>/.venv/bin/python")
    rr.set_defaults(func=cmd_remake_run)

    cd = sub.add_parser("capsule-draft", help="用拆解结果生成 capsule-cinema 胶囊草稿")
    cd.add_argument("breakdown")
    cd.add_argument("--capsule-root", help="capsule-cinema 仓库；默认 $CAPSULE_CINEMA_ROOT、prefs capsule_root，再退到 ~/code/github/capsule-cinema")
    cd.add_argument("--capsule-name", default="")
    cd.add_argument("--capsule-display-name", default="")
    cd.add_argument("--write-capsule", action="store_true", help="落盘到 capsule-cinema 的 capsules/")
    cd.add_argument("--overwrite-capsule", action="store_true")
    cd.add_argument("--python", help="capsule-cinema 的 Python；默认同 remake-run")
    cd.add_argument("--keep-source-text", action="store_true", help="保留原片台词、画面文字和镜头描述（只用于你有权使用的视频）")
    cd.set_defaults(func=cmd_capsule_draft)

    a = sub.add_parser("assemble", help="交给 Capsule Cinema：把复刻结果按原时间线拼回，并输出对比视频")
    a.add_argument("breakdown")
    a.add_argument("results", help="remake-run 输出的 results.json（或自己写的同格式文件）")
    a.add_argument("-o", "--out")
    a.add_argument("--capsule-root", help="capsule-cinema 仓库；默认 $CAPSULE_CINEMA_ROOT、prefs capsule_root，再退到 ~/code/github/capsule-cinema")
    a.add_argument("--overlays", action="store_true",
                   help="把测得的字幕 / 花字 / 标题按原样式叠回换掉的镜头（保留原片的镜头本来就有）；贴纸只列出来，要自己找素材")
    a.set_defaults(func=cmd_assemble)

    t = sub.add_parser("tiles", help="按时间抽帧拼图，近距离检查某一段（agent 复核用）")
    t.add_argument("video")
    t.add_argument("--start", type=float, default=0.0)
    t.add_argument("--end", type=float)
    t.add_argument("--every", type=float, default=0.5)
    t.add_argument("--cols", type=int, default=6)
    t.add_argument("--cell", type=int, default=320)
    t.add_argument("--max", type=int, default=48)
    t.add_argument("--focus", help="只看画面的一块并放大到 --cell 宽：x0,y0,x1,y1（0-1，整幅画面坐标）；和 --grid 一起用时网格是这一块里的坐标")
    t.add_argument("--grid", action="store_true", help="每格画 0.1 一条的网格（整幅画面坐标，左上角 0,0），定位用")
    t.add_argument("-o", "--out", default="out/tiles.jpg")
    t.set_defaults(func=cmd_tiles)

    fr = sub.add_parser("frames", help="代码渲染镜头按场景切分，取原尺寸帧、画上去的那一层（抠图 + 采样点）和底色 / 背景光 / 前景颜色（decompose 会自动跑）")
    fr.add_argument("out_dir", help="decompose 的输出目录")
    fr.add_argument("--every", type=float, default=0.25, help="采样间隔秒数（默认 0.25）")
    fr.add_argument("--points", type=int, default=4000, help="每个场景取多少个采样点（默认 4000）")
    fr.add_argument("--all", action="store_true", help="所有镜头都做，不只是代码渲染镜头")
    fr.set_defaults(func=cmd_frames)

    cp = sub.add_parser("compare", help="逐帧比较复刻和原片画上去的那一层（落在哪、形状重合度、多少），列出最差的时刻并拼对比图")
    cp.add_argument("ref", help="原片")
    cp.add_argument("remake", help="复刻成片")
    cp.add_argument("--every", type=float, default=0.5, help="采样间隔秒数（默认 0.5）")
    cp.add_argument("--scenes", help="frames/scenes.json：按场景汇总分数")
    cp.add_argument("--worst", type=int, default=8, help="对比图里放几个最差时刻（默认 8）")
    cp.add_argument("-o", "--out", help="输出目录：compare.json 和 compare_worst.jpg")
    cp.set_defaults(func=cmd_compare)

    rm = sub.add_parser("remake", help="交给 Capsule Cinema 出复刻：静图按运动重建（代码渲染镜头默认原片占位，加 --code 出快速草稿）、已生成 / 你给的镜头剪进去，其余原片占位；输出成片、对比视频和逐镜进度（remake/status.md）")
    rm.add_argument("out_dir", help="decompose 的输出目录")
    rm.add_argument("--code", action="store_true", help="用 code-remake 给代码渲染镜头出快速草稿（粒子 / 数据可视化类画面接近原片；插画动画建议交给 HyperFrames 等 HTML 视频框架）")
    rm.add_argument("--no-overlays", action="store_true", help="换掉的镜头上不叠回字幕 / 花字")
    rm.add_argument("--capsule-root", help="capsule-cinema 仓库；默认 $CAPSULE_CINEMA_ROOT、prefs capsule_root，再退到 ~/code/github/capsule-cinema")
    rm.set_defaults(func=cmd_remake)

    cr = sub.add_parser("code-remake", help="代码渲染镜头的第一版复刻：按场景的采样点 / 抠图、运动和背景光写出可改的工程（code/spec.json + render.py），对齐原片后渲染并打分")
    cr.add_argument("out_dir", help="decompose 的输出目录")
    cr.add_argument("--reset", action="store_true", help="重新生成 spec.json（默认保留改过的）")
    cr.add_argument("--no-render", action="store_true", help="只写工程，不渲染")
    cr.add_argument("--no-compare", action="store_true", help="渲染后不打分")
    cr.set_defaults(func=cmd_code_remake)

    dv = sub.add_parser("drive", help="舞蹈 / 动作镜头的驱动视频：擦掉字幕贴纸、在动作停顿处切段（drive/seg_XX.mp4），喂动作迁移或参考视频模型；--join 把生成好的段拼回原时间线")
    dv.add_argument("out_dir", help="decompose 的输出目录")
    dv.add_argument("--shots", help="只做这些镜头，如 3-7,9（默认用复刻方案里的动作驱动单元）")
    dv.add_argument("--depth", action="store_true", help="同时出深度视频（需要 transformers + torch；没有时 README 里给 Video Depth Anything 命令）")
    dv.add_argument("--no-clean", action="store_true", help="不擦字幕和贴纸")
    dv.add_argument("--prefer", type=float, help="每段的理想长度（秒），默认 10")
    dv.add_argument("--max", type=float, help="每段最长（秒），默认 15；Kling 最长 30")
    dv.add_argument("--join", nargs="?", const="", default=None, metavar="RESULTS", help="把生成好的段（默认 drive/results.json）拼回去，写进 remake/mine.json")
    dv.set_defaults(func=cmd_drive)

    sm = sub.add_parser("summary", help="紧凑打印拆解结果（低置信镜头会被标出来）")
    sm.add_argument("breakdown")
    sm.set_defaults(func=cmd_summary)

    rl = sub.add_parser("videomd", help="从 breakdown.json 重新生成给模型读的拆片包（VIDEO.md + video/）；decompose 和 apply-review 会自动生成")
    rl.add_argument("out_dir")
    rl.add_argument("--check", action="store_true", help="只校验目录是否符合 VIDEO.md 规范（https://github.com/videomd/videomd），不重写")
    rl.set_defaults(func=cmd_videomd)

    cl = sub.add_parser("clean-paths", help="清掉旧拆解包里的本机路径，方便分享；默认只报告，加 --apply 才改")
    cl.add_argument("dir", help="拆解包目录，或包含多个包的上级目录")
    cl.add_argument("--apply", action="store_true", help="真正改写文件")
    cl.set_defaults(func=cmd_clean_paths)

    pd = sub.add_parser("pdf", help="把 report.html 打印成 report.pdf（用本机的 Chrome / Chromium / Edge，折叠内容全部展开）")
    pd.add_argument("out_dir")
    pd.set_defaults(func=cmd_pdf)

    sv = sub.add_parser("survey", help="先看全片总览再局部细看：定切点、转场和每镜关键帧（JEV 格式问答）；decompose 会按结果切镜")
    sv.add_argument("video")
    sv.add_argument("-o", "--out")
    sv.add_argument("--vlm", action="store_true", help="用配置的 VLM 自动回答每一轮（同一轮的任务并发）")
    sv.add_argument("--no-vlm", action="store_true", help="本次不用 VLM（覆盖 prefs 里的 vlm=on）：输出任务，由能看图的 agent 回答")
    sv.add_argument("--no-detail", action="store_true", help="只定切点，不逐镜挑关键帧")
    sv.add_argument("--workers", type=int, default=4, help="VLM 并发数")
    sv.set_defaults(func=cmd_survey)

    mm = sub.add_parser("moments", help="找特殊时刻（魔术揭秘、反转、高潮、穿帮）：先通读台词和总览定段落，再逐段放大定关键帧，导出片段和关键帧")
    mm.add_argument("out_dir", help="decompose 的输出目录")
    mm.add_argument("--vlm", action="store_true", help="用配置的 VLM 自动回答（约 3–5 次调用）")
    mm.add_argument("--no-vlm", action="store_true", help="本次不用 VLM（覆盖 prefs 里的 vlm=on）：输出任务，由能看图的 agent 回答")
    mm.add_argument("--redo", action="store_true", help="丢掉上次的答案重新找")
    mm.set_defaults(func=cmd_moments)

    rv = sub.add_parser("review", help="能看图的 agent 当 VLM：生成逐镜看图任务和答案模板")
    rv.add_argument("out_dir", help="decompose 的输出目录")
    rv.add_argument("--force", action="store_true", help="覆盖已有的 review_answers.json")
    rv.set_defaults(func=cmd_review)

    ar = sub.add_parser("apply-review", help="把 agent 看图的答案并入结论，重写 breakdown.json 和报告")
    ar.add_argument("out_dir")
    ar.add_argument("answers", nargs="?", help="答案文件（默认 <out_dir>/review_answers.json）")
    ar.add_argument("--by", help="复核者名字（写进报告）")
    ar.add_argument("--lang", choices=LANGS, help="在这一步换报告语言：结论、证据和报告文字重新生成，VLM 已写好的描述和提示词保持原语言")
    ar.set_defaults(func=cmd_apply_review)

    co = sub.add_parser("correct", help="用户指出判错：改正这条视频的结论，并记入记忆（以后同类镜头会提示复核）")
    co.add_argument("out_dir", help="decompose 的输出目录")
    co.add_argument("--shots", help="镜头编号，逗号分隔（如 3,5 或 shot_003），all 表示整条；也可用 --start/--end 指定时间段")
    co.add_argument("--start", type=float)
    co.add_argument("--end", type=float)
    co.add_argument("--label", help="正确的底层类别：" + "、".join(LABELS))
    co.add_argument("--real", choices=["yes", "no"], help="是否用了用户真实素材")
    co.add_argument("--note", help="用户的原话或理由，例如「这是定格动画，不是 AI」")
    co.set_defaults(func=cmd_correct)

    pl_ = sub.add_parser("plan", help="按用户要用的视频模型出复刻方案（报告第二部分）；拆解结果不变")
    pl_.add_argument("out_dir", help="拆解目录")
    pl_.add_argument("--model", help="模型 id 或名称，写进 remake/intent.yaml（rea-video models 列出的；没有的先查资料补进 ~/.rea-video/capabilities/models/）")
    pl_.add_argument("--generate", choices=["ai", "all"], help="ai：只生成原片里 AI 做的镜头，实拍的出拍摄方案；all：整条都用模型生成（换人、换物后整条复刻）")
    pl_.set_defaults(func=cmd_plan)

    mo = sub.add_parser("models", help="列出能力地图里的生成模型；带模型 id 时打印这个模型的提示词写法和关键帧要求")
    mo.add_argument("model", nargs="?", help="模型 id（如 seedance-2.5、kling-3.0）；keyframes 打印关键帧通用做法")
    mo.set_defaults(func=cmd_models)

    pf = sub.add_parser("prefs", help="查看 / 设置用户偏好（默认引擎、是否开 VLM、VLM 配置文件、复核者、自由文字说明）")
    pf.add_argument("key", nargs="?")
    pf.add_argument("value", nargs="?")
    pf.add_argument("--unset", action="store_true")
    pf.add_argument("--note", help="追加一条给 agent 看的偏好说明，例如「报告尽量短」")
    pf.add_argument("--remove-note", type=int, metavar="N")
    pf.set_defaults(func=cmd_prefs)

    me = sub.add_parser("memory", help="看记住了什么：偏好、常见纠正类型；可导出为评测样本")
    me.add_argument("--export-labels", metavar="YAML")
    me.set_defaults(func=cmd_memory)

    for sp in sub.choices.values():  # also accept `rea-video decompose x.mp4 --env-file ...` and `<cmd> --lang en`
        sp.add_argument("--env-file", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if not any("--lang" in a.option_strings for a in sp._actions):
            sp.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    from .cli_en import localize

    localize(ap, ", ".join(LABELS))
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    _env(args)
    from .media import MediaError

    try:
        return args.func(args)
    except MediaError as exc:  # missing ffmpeg / unreadable video: one line, not a traceback
        hint = ""
        if "not found on PATH" in str(exc):
            hint = U("\n安装 ffmpeg：macOS `brew install ffmpeg`，Ubuntu/Debian `sudo apt install ffmpeg`，Windows `winget install Gyan.FFmpeg`",
                     "\ninstall ffmpeg: macOS `brew install ffmpeg`, Ubuntu/Debian `sudo apt install ffmpeg`, Windows `winget install Gyan.FFmpeg`")
        print(f"rea-video: {exc}{hint}", file=sys.stderr)
        if args.verbose:
            raise
        return 2
    except FileNotFoundError as exc:  # wrong path to a video / breakdown.json / answers file
        if args.verbose:
            raise
        print("rea-video: " + U(f"找不到文件：{exc.filename}", f"file not found: {exc.filename}"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
