"""How the people in a shot act: the main emotion, how strong it is, what the face and body do, how the voice sounds,
and how it changes inside the shot.

A remake that keeps the picture and the words but not the acting comes out flat. Video models handle emotion words
poorly: "sad" or "very angry" tends to give a mask face, a forced smile or glowing eyes. What works is the visible
part: eyes, brows, mouth, head and hands, at a modest strength, written as a change over time. So the emotion
word is kept for the reader, and the prompt gets the visible cues.

Nothing here is measured. It comes from a reader looking at the frames: the agent's review (`review_answers.json`,
per shot `performance`) or the per-shot VLM pass. The agent's answer wins where both exist.
"""
from __future__ import annotations

from .i18n import LangDict, T, semi

INTENSITY = ("low", "mid", "high")
INTENSITY_ZH = LangDict({"low": "轻", "mid": "中", "high": "强"}, en={"low": "light", "mid": "medium", "high": "strong"})
_INTENSITY_ALIASES = {"轻": "low", "弱": "low", "小": "low", "1": "low", "2": "low", "中": "mid", "适中": "mid", "medium": "mid", "3": "mid",
                      "强": "high", "大": "high", "strong": "high", "4": "high", "5": "high"}

# labels whose picture can hold a performance; screens, code graphics and stills cannot
ACTING_LABELS = ("live_action", "ai_video", "avatar", "cg_3d", "anim_2d", "stop_motion", "film_footage")

# shared by the VLM prompt and the review instructions so both readers answer the same question
GUIDE = """画面里有人物、动物、卡通角色或数字人在表演（脸或肢体看得清）时填 performance，否则写 null（空镜、商品特写、只有手、远景看不清脸）：
- who：谁在演（和角色表里的编号或称呼一致）
- emotion：一个主情绪词（平静 / 开心 / 期待 / 好奇 / 惊讶 / 委屈 / 生气 / 紧张 / 得意 / 无奈 …）；一个镜头只写一个主情绪
- intensity：low|mid|high，按看到的幅度写；多数口播、带货是 low 或 mid
- face：看得见的面部动作，不写情绪词：眼睛（睁大、眯起、看镜头、眼神躲开、眨眼）、眉（上扬、皱起、眉心收紧）、嘴（嘴角上扬或下压、抿嘴、张嘴）、脸颊和下巴
- body：头、肩、手、姿态、呼吸（点头、歪头、耸肩、手捂嘴、身体前倾、深吸一口气）
- arc：镜头里情绪有变化时按秒写，t 是相对镜头开头的秒：[{"t": 0.0, "state": "这一刻看得见的表情和动作"}]；没变化写 []
- voice：画面里的角色在这一镜开口（说话、笑、叹气）时写语气、语速、音量、停顿（"压低声音，语速慢，句尾带笑"）；画外旁白或没人开口留空
- key：true = 表演是这一镜的看点（反应镜头、情绪爆发、反转时的表情），复刻时要专门保证
- en：把 face、body、arc 合成一句英文，只写看得见的动作，不写情绪词（"eyes slightly red, corners of the mouth pressed down; at 1.5s she looks up"），给英文提示词用；上面几项已经是英文时留空"""


def intensity_code(v) -> str:
    s = str(v or "").strip().lower()
    if s in INTENSITY:
        return s
    return _INTENSITY_ALIASES.get(s, "")


def _txt(v, n: int = 160) -> str:
    return " ".join(str(v or "").split())[:n] if isinstance(v, (str, int, float)) else ""


def clean(v) -> dict | None:
    """One answer to stored form; None when it says nothing about acting."""
    if not isinstance(v, dict):
        return None
    arc = []
    for a in v.get("arc") or [] if isinstance(v.get("arc"), list) else []:
        if isinstance(a, dict) and _txt(a.get("state")):
            try:
                t = round(max(0.0, float(a.get("t", 0) or 0)), 2)
            except (TypeError, ValueError):
                t = 0.0
            arc.append({"t": t, "state": _txt(a.get("state"), 80)})
    out = {"who": _txt(v.get("who"), 30), "emotion": _txt(v.get("emotion"), 20), "intensity": intensity_code(v.get("intensity")),
           "face": _txt(v.get("face")), "body": _txt(v.get("body")), "arc": sorted(arc, key=lambda a: a["t"])[:6],
           "voice": _txt(v.get("voice"), 100), "key": v.get("key") is True or str(v.get("key")).lower() == "true",
           "en": _txt(v.get("en"), 240) if _txt(v.get("en"), 240).isascii() else ""}
    if not any(out[k] for k in ("emotion", "face", "body", "arc", "voice")):
        return None
    return out


def of(rec: dict) -> dict | None:
    """The shot's performance: the agent's review wins over the VLM (it is the later, checked pass)."""
    for src in ("review", "vlm"):
        got = clean((rec.get(src) or {}).get("performance"))
        if got:
            return got
    return None


def _strength() -> dict[str, str]:
    # "open it to about a third": full-strength words give mask faces and forced smiles
    return {"low": T("幅度很小，几乎看不出", "very subtle, barely visible"),
            "mid": T("幅度适中，不夸张", "moderate, not exaggerated"),
            "high": T("情绪外放，但五官不变形", "openly expressed, features stay natural")}


STRENGTH_EN = {"low": "very subtle, barely visible", "mid": "moderate, not exaggerated", "high": "openly expressed, features stay natural"}


def prompt_line_en(p: dict | None) -> str:
    """The acting for the English prompt: the reader's English sentence, or the fields themselves when they are
    already English. Chinese cues are never mixed into an English prompt."""
    if not p:
        return ""
    body = p.get("en") or ""
    if not body:
        bits = [x for x in (p.get("face"), p.get("body")) if x]
        bits += [f"at the start {a['state']}" if a["t"] < 0.05 else f"at {a['t']:.1f}s {a['state']}" for a in p.get("arc") or []]
        body = "; ".join(bits)
        if not body.isascii():
            return ""
    if not body:
        return ""
    return "Acting" + (f" ({STRENGTH_EN[p['intensity']]})" if p.get("intensity") else "") + ": " + body


def prompt_line(p: dict | None) -> str:
    """The acting as prompt words: visible cues, strength and the change over time; no bare emotion word."""
    if not p:
        return ""
    bits = [x for x in (p.get("face"), p.get("body")) if x]
    if p.get("arc"):
        bits.append(T("，", ", ").join(T("开头{s}", "at the start {s}", s=a["state"]) if a["t"] < 0.05 else
                                         T("{t:.1f} 秒时{s}", "at {t:.1f}s {s}", t=a["t"], s=a["state"]) for a in p["arc"]))
    if not bits:
        return ""
    head = T("表演", "Acting") + (T("（{s}）", " ({s})", s=_strength()[p["intensity"]]) if p.get("intensity") else "")
    return head + T("：", ": ") + T("；", "; ").join(bits)


def image_line(p: dict | None) -> str:
    """The expression for a first-frame image: the face at the start of the shot."""
    if not p:
        return ""
    face = p["arc"][0]["state"] if p.get("arc") and p["arc"][0]["t"] < 0.3 else p.get("face")
    return T("表情：{f}", "Expression: {f}", f=face) if face else ""


FILMED = ("live_action", "stop_motion", "film_footage")  # acted in front of a camera: the cues direct the actor
ROUTE_ZH = LangDict({"voice": "先配音再驱动", "transfer": "首帧 + 表演迁移", "first_frame": "首帧定表情", "shoot": "演员照着演"},
                    en={"voice": "voice first, then drive", "transfer": "first frame + performance transfer",
                        "first_frame": "expression in the first frame", "shoot": "actor plays it"})


def route_kind(p: dict | None, label: str = "") -> str:
    """How this acting is best reproduced: by a real actor, from the voice, from the first frame, or by transferring
    a real performance when the emotion itself is the point."""
    if not p:
        return ""
    if label in FILMED:
        return "shoot"
    if p.get("voice"):
        return "voice"
    if p.get("key") and p.get("intensity") == "high":
        return "transfer"
    return "first_frame"


def route_text(kind: str) -> str:
    return {
        "voice": T("有台词：先按语气做配音（TTS 只在情绪转折处加语气标签，或真人录），再用音频驱动的模型出口型和表情"
                   "（Kling Avatar、OmniHuman）；用能直接出声的视频模型时，把台词和语气一起写进提示词",
                   "Speaking: make the voice with its delivery first (TTS with tone tags only where the emotion turns, or a real recording), "
                   "then drive mouth and face from that audio (Kling Avatar, OmniHuman); with a video model that makes sound itself, "
                   "put the line and its delivery in the prompt together"),
        "transfer": T("情绪是这一镜的看点：首帧图先把表情做到位；还不够就真人对着镜头演一遍，用表演迁移到角色上（Runway Act-Two、Kling 动作控制、Wan Animate）",
                      "The emotion is the point of the shot: get the expression right in the first frame; if that is not enough, act it once "
                      "on camera and transfer the performance to the character (Runway Act-Two, Kling Motion Control, Wan Animate)"),
        "first_frame": T("首帧图里先把表情做到位，提示词只写动作和变化", "Get the expression right in the first frame; the prompt only describes the motion and the change"),
        "shoot": T("实拍：把表情、动作、语气当表演提示给演员，对着原片先练一遍停顿和语气",
                   "Filmed: hand the face, movement and delivery to the actor as direction, and rehearse the pauses and tone against the original once"),
    }.get(kind, "")


def summary(p: dict) -> str:
    """One short reader line: "开心（轻）· 眼睛眯起，嘴角上扬"."""
    head = p.get("emotion") or ""
    if p.get("intensity"):
        head += T("（{i}）", " ({i})", i=INTENSITY_ZH[p["intensity"]])
    return " · ".join(x for x in (head, p.get("face") or p.get("body")) if x)


def delivery_at(b: dict, start, end) -> str:
    """The voice of the shot under a line, for the script's delivery column when no reader gave one per line."""
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return ""
    mid = (start + end) / 2
    for r in b.get("shots", []):
        if r["start"] <= mid < r["end"]:
            return (of(r) or {}).get("voice") or ""
    return ""


def table(b: dict) -> tuple[list[list], list[str]]:
    """Report rows (shot, who, emotion, face, movement, delivery, how) and the routes used, in first-seen order."""
    rows, kinds = [], []
    for r in b.get("shots", []):
        p = of(r)
        if not p:
            continue
        emo = (p.get("emotion") or "—") + (T("（{i}）", " ({i})", i=INTENSITY_ZH[p["intensity"]]) if p.get("intensity") else "")
        if p.get("key"):
            emo += T(" ★看点", " ★key")
        moves = semi().join(x for x in [p.get("body") or ""] + [f"{a['t']:.1f}s {a['state']}" for a in p.get("arc") or []] if x)
        kind = route_kind(p, (r.get("base") or {}).get("label", ""))
        if kind not in kinds:
            kinds.append(kind)
        rows.append([f"#{r['index']}", p.get("who") or "—", emo, p.get("face") or "—", moves or "—", p.get("voice") or "—", ROUTE_ZH[kind]])
    return rows, kinds
