"""Acting and emotion: what readers report per shot, and how it reaches the remake prompts, the script and the report."""
import json

from rea_video import performance
from rea_video.i18n import set_lang
from rea_video.plan import with_acting
from rea_video.production import production_plan
from rea_video.review import _clean
from rea_video.vlm import SHOT_PROMPT, normalize_shot_result

from tests.test_production import KITCHEN, _b, _shot

ACT = {"who": "A", "emotion": "委屈", "intensity": "low", "face": "眼眶微红，嘴角轻轻下压", "body": "低头，手指绞着衣角",
       "arc": [{"t": 1.5, "state": "抬眼看镜头，下巴微微发抖"}, {"t": "bad", "state": "停顿"}], "voice": "", "key": True}


def test_clean_keeps_visible_cues_and_drops_empty_answers():
    p = performance.clean(ACT)
    assert p["intensity"] == "low" and p["key"] is True
    assert [a["t"] for a in p["arc"]] == [0.0, 1.5]  # a bad time is kept at 0, the list stays in order
    assert performance.clean({"who": "A", "emotion": "", "face": "", "arc": []}) is None
    assert performance.clean("开心") is None
    assert performance.clean({"emotion": "开心", "intensity": "强"})["intensity"] == "high"


def test_prompt_line_writes_the_face_not_the_emotion_word():
    set_lang("zh")
    line = performance.prompt_line(performance.clean(ACT))
    assert "眼眶微红" in line and "开头停顿，1.5 秒时抬眼看镜头" in line and "幅度很小" in line
    assert "委屈" not in line  # the emotion word stays in the report, not in the prompt
    assert performance.image_line(performance.clean(ACT)) == "表情：停顿"  # the face at frame one when the arc starts there


def test_with_acting_adds_once():
    act = performance.clean(ACT)
    assert with_acting("她站在窗边。", act).startswith("她站在窗边。表演")
    assert with_acting("她眼眶微红，嘴角轻轻下压，站在窗边", act) == "她眼眶微红，嘴角轻轻下压，站在窗边"
    assert with_acting("", act) == "" and with_acting("她站在窗边", None) == "她站在窗边"


def test_route_by_what_carries_the_acting():
    act = performance.clean(ACT)
    assert performance.route_kind(act, "live_action") == "shoot"
    assert performance.route_kind(act, "ai_video") == "first_frame"
    assert performance.route_kind(dict(act, voice="压低声音，句尾带哭腔"), "ai_video") == "voice"
    assert performance.route_kind(dict(act, intensity="high"), "ai_video") == "transfer"


def test_review_answer_and_vlm_answer_carry_performance():
    assert '"performance"' in SHOT_PROMPT
    SHOT_PROMPT.format(hints="")  # the guide's braces are escaped for str.format
    clean, err = _clean({"label_probs": {"ai_video": 1}, "performance": ACT})
    assert not err and clean["performance"]["face"] == ACT["face"]
    assert normalize_shot_result({"label_probs": {"ai_video": 1}, "performance": "开心"})["performance"] is None


def test_generation_unit_prompt_and_report_use_the_acting(tmp_path):
    set_lang("zh")
    shots = [_shot(1, 0.0, 2.0, "ai_video", KITCHEN, tmp_path), _shot(2, 2.0, 2.0, "ai_video", KITCHEN, tmp_path)]
    shots[1]["review"] = {"performance": performance.clean(dict(ACT, voice="压低声音，句尾带哭腔"))}
    b = _b(shots)
    plan = production_plan(b, tmp_path)
    u = plan["units"][0]
    assert "镜头2（2.0–4.0s）：镜头 2 的动作。表演（幅度很小，几乎看不出）：眼眶微红" in u["prompt"]
    assert u["acting"][0]["shot"] == 2 and u["acting"][0]["how"] == "先配音再驱动"
    b["production_plan"] = plan
    rows, kinds = performance.table(b)
    assert rows[0][0] == "#2" and "委屈（轻） ★看点" == rows[0][2] and kinds == ["voice"]
    from rea_video.entities import script

    b["whole_video_vlm"] = {"narration": {"lines": [{"start": 2.2, "end": 3.5, "speaker": "A", "text": "我没有"},
                                                    {"start": 0.2, "end": 1.0, "speaker": "A", "text": "你听我说", "delivery": "急促"}]}}
    assert [ln.get("delivery") for ln in script(b)] == ["压低声音，句尾带哭腔", "急促"]
    json.dumps(plan, ensure_ascii=False)
