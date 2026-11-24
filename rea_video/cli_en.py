"""English text for `rea-video --help`, keyed by command and argument dest ("decompose", "decompose.vlm")."""
from __future__ import annotations

import argparse

from .i18n import ui_lang

_CAPSULE_ROOT = "capsule-cinema repo; defaults to $CAPSULE_CINEMA_ROOT, prefs capsule_root, then ~/code/github/capsule-cinema"
_OUT_DIR = "decompose output directory"
_NO_VLM_AGENT = "no VLM this run (overrides vlm=on in prefs): write tasks for an agent that can read images"

HELP = {
    "": "Reverse-engineer a video shot by shot: live action / AI-generated / code-rendered / mixed, with a remake plan",
    "verbose": "print debug logs and full tracebacks on error",
    "env_file": "extra .env file (for example capsule-cinema/.env, for VLM settings)",
    "lang": "CLI and output language: zh (default) / en",

    "decompose": "break down a video",
    "decompose.video": "input video file",
    "decompose.out": "output directory (default: out/<video-stem>)",
    "decompose.workers": "parallel VLM workers (default 3)",
    "decompose.vlm": "use a vision model (VLM) to judge each shot; recommended. Without it, live action / AI / 3D are harder to tell apart",
    "decompose.no_vlm": "no VLM this run (overrides vlm=on in prefs)",
    "decompose.no_whole": "skip the whole-video structure and copy analysis",
    "decompose.no_ocr": "skip OCR (also skips the caption and text timelines, leaving sticker detection only)",
    "decompose.ocr_lang": "caption language: zh Chinese and English (default), en English only, ja Japanese, ko Korean (the last three download a model on first use); set a default with prefs ocr_lang",
    "decompose.no_packaging": "skip the edit packaging layer (caption timeline, styled text, stickers / GIFs, sound-effect sync); saves about 30-50 s per minute of video",
    "decompose.lang": "language of the report, verdict and VLM descriptions: zh (default) / en; follow the language of the request, or set a default with prefs lang",
    "decompose.max_vlm_shots": "maximum VLM calls (default 60); with more shots, the least certain go first and the rest use measured evidence only",
    "decompose.engine": "video model to plan the remake for (an id from rea-video models); defaults to prefs engine, then minimax-h3",
    "decompose.meta": 'platform metadata JSON, for example {"music": {"title": "xx", "author": "yy", "is_original": false, "popular": true}}',
    "decompose.no_asr": "skip local speech recognition (runs only with rea-video[asr]: transcribes lines and timing from the vocal stem; downloads about 160 MB on first use)",
    "decompose.asr_lang": "speech language: auto (default, SenseVoice detects Chinese / English / Japanese / Korean / Cantonese), bn Bengali (downloads about 90 MB on first use); set a default with prefs asr_lang",
    "decompose.no_speakers": "skip speaker separation (runs only with rea-video[asr]: finds who speaks when and writes stems/voice_S1.wav per speaker; downloads about 35 MB on first use)",
    "decompose.no_survey": "with VLM, skip the overview and close-up pass (use only the cut detector's cuts)",
    "decompose.no_stems": "skip voice / music separation (by default writes stems/original.wav, vocals.wav, music.wav)",
    "decompose.no_moments": "skip special moments (magic reveals, twists, climaxes, mistakes); with VLM they are searched by default, about 3-5 extra calls",

    "stems": "only split the audio into original / vocals / music tracks",
    "stems.video": "input video or audio file",
    "stems.out": "output directory (default: out/<video-stem>)",
    "probe": "only show container metadata and source clues",
    "probe.video": "input video file",
    "probe.tags": "include raw container and stream tags",

    "eval": "measure breakdown accuracy on a labeled sample set",
    "eval.labels": "labels.yaml",
    "eval.out": "evaluation output directory (default: out/eval)",
    "eval.vlm": "enable VLM during evaluation",
    "eval.no_ocr": "skip OCR during evaluation",
    "eval.ocr_lang": "same as decompose --ocr-lang",
    "eval.fresh": "do not reuse existing breakdowns",
    "eval.only": "re-decompose only these ids (comma-separated); the rest reuse the cache and are reclassified",
    "eval.stems": "separate vocals on samples with audio labels and re-measure singing / speech on the clean stem",

    "capsule": "export capsule-cinema video analysis JSON (for drafting a capsule)",
    "remake-plan": "write the remake plan's generation units as capsule-cinema jobs (choose the model and swaps in rea-video plan)",
    "remake-plan.capsule_root": _CAPSULE_ROOT,
    "remake-run": "run remake-plan jobs through Capsule Cinema (billed; use --dry-run first)",
    "remake-run.jobs": "jobs.json from remake-plan",
    "remake-run.capsule_root": "must match remake-plan; same default as remake-plan",
    "remake-run.dry_run": "list jobs and parameters without calling a model",
    "remake-run.only": "run only these shots (comma-separated)",
    "remake-run.python": "capsule-cinema Python; defaults to $CAPSULE_CINEMA_PYTHON or <capsule-root>/.venv/bin/python",
    "capsule-draft": "draft a capsule-cinema capsule from a breakdown",
    "capsule-draft.capsule_root": _CAPSULE_ROOT,
    "capsule-draft.write_capsule": "write it to capsules/ in capsule-cinema",
    "capsule-draft.keep_source_text": "keep the source's spoken lines, on-screen text and shot descriptions (only for videos you have the rights to)",
    "capsule-draft.python": "capsule-cinema Python; same default as remake-run",
    "assemble": "through Capsule Cinema: put remade shots back on the original timeline and output a comparison video",
    "assemble.results": "results.json from remake-run (or your own file in the same format)",
    "assemble.capsule_root": _CAPSULE_ROOT,
    "assemble.overlays": "put measured captions / styled text / titles back on replaced shots in their original style (kept shots already have them); stickers are only listed, so source them yourself",

    "tiles": "tile frames over time to inspect a section closely (for agent review)",
    "tiles.focus": "zoom into part of the frame at --cell width: x0,y0,x1,y1 (0-1, full-frame coordinates); with --grid, the grid uses this region's coordinates",
    "tiles.grid": "draw a 0.1-step grid on each tile (full-frame coordinates, top-left is 0,0) for locating things",

    "frames": "split code-rendered shots into scenes and extract full-size frames, the drawn layer (matte + sample points) and base / glow / foreground colors (decompose runs this automatically)",
    "frames.out_dir": _OUT_DIR,
    "frames.every": "sampling interval in seconds (default 0.25)",
    "frames.points": "sample points per scene (default 4000)",
    "frames.all": "process all shots, not only code-rendered ones",

    "compare": "compare the drawn layer of a remake and the original frame by frame (position, shape overlap, amount), list the worst moments and tile them",
    "compare.ref": "original video",
    "compare.remake": "remade video",
    "compare.every": "sampling interval in seconds (default 0.5)",
    "compare.scenes": "frames/scenes.json: summarize scores per scene",
    "compare.worst": "worst moments to show in the comparison image (default 8)",
    "compare.out": "output directory for compare.json and compare_worst.jpg",

    "remake": "remake through Capsule Cinema: rebuild stills from their motion (code-rendered shots keep the original unless --code), cut in generated or supplied shots, keep the original elsewhere; writes the video, a comparison and per-shot progress (remake/status.md)",
    "remake.out_dir": _OUT_DIR,
    "remake.code": "draft code-rendered shots with code-remake (close for particles / data visuals; for illustrated animation use an HTML video framework such as HyperFrames)",
    "remake.no_overlays": "do not put captions / styled text back on replaced shots",
    "remake.capsule_root": _CAPSULE_ROOT,

    "code-remake": "first remake of code-rendered shots: write an editable project (code/spec.json + render.py) from each scene's sample points / matte, motion and glow, align to the original, render and score",
    "code-remake.out_dir": _OUT_DIR,
    "code-remake.reset": "regenerate spec.json (edits are kept by default)",
    "code-remake.no_render": "write the project without rendering",
    "code-remake.no_compare": "do not score after rendering",

    "drive": "driving video for dance / action shots: erase captions and stickers, cut at motion pauses (drive/seg_XX.mp4) for motion transfer or reference-video models; --join puts generated segments back on the timeline",
    "drive.out_dir": _OUT_DIR,
    "drive.shots": "only these shots, such as 3-7,9 (default: the motion-driven units in the remake plan)",
    "drive.depth": "also output a depth video (needs transformers + torch; otherwise the README gives a Video Depth Anything command)",
    "drive.no_clean": "do not erase captions and stickers",
    "drive.prefer": "ideal segment length in seconds, default 10",
    "drive.max": "maximum segment length in seconds, default 15; Kling allows up to 30",
    "drive.join": "put generated segments (default drive/results.json) back and write remake/mine.json",

    "summary": "print a compact breakdown (low-confidence shots are flagged)",
    "videomd": "regenerate the model-readable package (VIDEO.md + video/) from breakdown.json; decompose and apply-review do this automatically",
    "videomd.check": "only validate the directory against the VIDEO.md spec (https://github.com/videomd/videomd), without rewriting",
    "clean-paths": "remove local paths from older packages so they can be shared; reports only unless --apply is given",
    "clean-paths.dir": "package directory, or a parent directory with several packages",
    "clean-paths.apply": "rewrite the files",
    "pdf": "print report.html to report.pdf (with local Chrome / Chromium / Edge, all folded sections expanded)",

    "survey": "overview first, then close-ups: find cuts, transitions and key frames per shot (JEV-format Q&A); decompose cuts shots from the result",
    "survey.vlm": "answer each round with the configured VLM (tasks in a round run concurrently)",
    "survey.no_vlm": _NO_VLM_AGENT,
    "survey.no_detail": "only find cuts, without picking key frames per shot",
    "survey.workers": "VLM concurrency",

    "moments": "find special moments (magic reveals, twists, climaxes, mistakes): read the lines and overview, zoom into each section for key frames, export clips and frames",
    "moments.out_dir": _OUT_DIR,
    "moments.vlm": "answer with the configured VLM (about 3-5 calls)",
    "moments.no_vlm": _NO_VLM_AGENT,
    "moments.redo": "discard earlier answers and search again",

    "review": "let an agent that can read images act as the VLM: write per-shot review tasks and an answer template",
    "review.out_dir": _OUT_DIR,
    "review.force": "overwrite an existing review_answers.json",
    "apply-review": "merge an agent's review answers into the verdict and rewrite breakdown.json and the report",
    "apply-review.answers": "answers file (default <out_dir>/review_answers.json)",
    "apply-review.by": "reviewer name (shown in the report)",
    "apply-review.lang": "switch the report language here: verdict, evidence and report text are regenerated; descriptions and prompts already written by the VLM stay in their language",

    "correct": "record a user's correction: update this video's verdict and remember it (similar shots get a review hint later)",
    "correct.out_dir": _OUT_DIR,
    "correct.shots": "shot numbers, comma-separated (such as 3,5 or shot_003), or all for the whole video; or use --start/--end for a time range",
    "correct.start": "start time in seconds when selecting shots by range",
    "correct.end": "end time in seconds when selecting shots by range",
    "correct.label": "correct base label: {labels}",
    "correct.real": "whether the user's real material was used",
    "correct.note": 'the user\'s words or reason, for example "this is stop motion, not AI"',

    "plan": "write the remake plan for the video model the user wants (part two of the report); the breakdown does not change",
    "plan.out_dir": "breakdown directory",
    "plan.model": "model id or name, saved to remake/intent.yaml (from rea-video models; for others, look it up and add it under ~/.rea-video/capabilities/models/)",
    "plan.generate": "ai: generate only the shots that were AI in the original and write a shooting plan for live action; all: generate the whole video (full remake after swapping people or objects)",

    "models": "list generation models in the capability map; with a model id, print its prompt guide and key-frame requirements",
    "models.model": "model id (such as seedance-2.5, kling-3.0); keyframes prints the general key-frame guide",
    "prefs": "show / set preferences (default engine, VLM on or off, VLM env file, reviewer, free-text notes)",
    "prefs.key": "preference key (or key=value)",
    "prefs.value": "new value for the preference key",
    "prefs.unset": "reset the given preference key to default",
    "prefs.note": 'add a preference note for agents, for example "keep reports short"',
    "prefs.remove_note": "remove preference note #N (1-based)",
    "memory": "show what is remembered: preferences and common corrections; can export them as eval samples",
    "memory.export_labels": "export remembered corrections to a labels YAML file for rea-video eval",
}


def localize(parser: argparse.ArgumentParser, labels: str = "") -> None:
    """Swap the parser's help text for English when the CLI language is English."""
    if ui_lang() != "en":
        return
    parser.description = HELP[""]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for row in action._choices_actions:
                row.help = HELP.get(row.dest, row.help)
            for name, sub in action.choices.items():
                for arg in sub._actions:
                    text = HELP.get(f"{name}.{arg.dest}")
                    if text and arg.help != argparse.SUPPRESS:
                        arg.help = text.replace("{labels}", labels)
        elif action.dest in HELP and action.help != argparse.SUPPRESS:
            action.help = HELP[action.dest]
