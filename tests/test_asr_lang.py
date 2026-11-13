"""--asr-lang bn: the Bengali streaming model is chosen, checked, unpacked and decoded; auto stays SenseVoice."""
import hashlib
import io
import os
import sys
import tarfile
import types

import numpy as np
import pytest

from rea_video import speech


@pytest.fixture
def fake_sherpa(monkeypatch, tmp_path):
    """sherpa_onnx stand-in: records which recognizer is built and what each stream is fed."""
    made, streams = [], []

    class Stream:
        def __init__(self):
            self.fed, self.finished, self.decoded = [], False, False
            self.result = types.SimpleNamespace(text="", lang="")

        def accept_waveform(self, sr, samples):
            self.fed.append(len(samples))

        def input_finished(self):
            self.finished = True

    class OnlineRecognizer:
        @classmethod
        def from_transducer(cls, **kwargs):
            made.append(("online", kwargs))
            return cls()

        def create_stream(self):
            streams.append(Stream())
            return streams[-1]

        def is_ready(self, st):
            return st.finished and not st.decoded

        def decode_stream(self, st):
            st.decoded = True

        def get_result(self, st):
            return " আমি ভাত খাই " if st.decoded else ""

    class OfflineRecognizer:
        @classmethod
        def from_sense_voice(cls, **kwargs):
            made.append(("offline", kwargs))
            return cls()

        def create_stream(self):
            streams.append(Stream())
            return streams[-1]

        def decode_stream(self, st):
            st.result = types.SimpleNamespace(text="大家好", lang="<|zh|>")

    monkeypatch.setitem(sys.modules, "sherpa_onnx", types.SimpleNamespace(OnlineRecognizer=OnlineRecognizer,
                                                                          OfflineRecognizer=OfflineRecognizer))
    monkeypatch.setattr(speech, "available", lambda: True)
    monkeypatch.setattr(speech, "extract_audio", lambda audio, sr: np.zeros(sr * 3, np.float32))
    monkeypatch.setattr(speech, "_stretches", lambda x, vad: [(0.5, np.zeros(speech.SR * 2, np.float32))])
    monkeypatch.setattr(speech, "ensure_bn_models", lambda: (tmp_path / "bn", tmp_path / "vad.onnx"))
    monkeypatch.setattr(speech, "ensure_models", lambda: (tmp_path / "sv.onnx", tmp_path / "tokens.txt", tmp_path / "vad.onnx"))
    return made, streams


def test_default_language_is_auto(monkeypatch):
    monkeypatch.delenv("REA_ASR_LANG", raising=False)
    assert speech.asr_lang() == "auto"


def test_unknown_language_is_rejected(monkeypatch):
    monkeypatch.setenv("REA_ASR_LANG", "hi")
    with pytest.raises(ValueError):
        speech.asr_lang()


def test_bn_uses_the_bengali_streaming_model(monkeypatch, tmp_path, fake_sherpa):
    made, streams = fake_sherpa
    monkeypatch.setenv("REA_ASR_LANG", "bn")
    res = speech.transcribe(tmp_path / "x.wav")
    assert res == {"ok": True, "engine": "zipformer-bn-vosk (sherpa-onnx)", "language": "bn",
                   "lines": [{"start": 0.5, "end": 2.5, "text": "আমি ভাত খাই"}]}
    kind, kwargs = made[0]
    assert kind == "online" and len(made) == 1
    assert {k: kwargs[k] for k in ("tokens", "encoder", "decoder", "joiner")} == {
        n: str(tmp_path / "bn" / f"{n}{'.txt' if n == 'tokens' else '.onnx'}") for n in ("tokens", "encoder", "decoder", "joiner")}
    # the stretch, then silence so the streaming encoder lets go of its last frames, then end of input
    assert streams[0].fed == [speech.SR * 2, int(speech.TAIL_PAD_S * speech.SR)] and streams[0].finished


def test_auto_keeps_sensevoice_and_an_explicit_language_wins(monkeypatch, tmp_path, fake_sherpa):
    made, _ = fake_sherpa
    monkeypatch.delenv("REA_ASR_LANG", raising=False)
    res = speech.transcribe(tmp_path / "x.wav")
    assert res["engine"] == "sensevoice-small-int8 (sherpa-onnx)" and res["language"] == "zh" and res["lines"][0]["text"] == "大家好"
    assert made[-1][0] == "offline" and made[-1][1]["language"] == ""
    assert speech.transcribe(tmp_path / "x.wav", language="bn")["language"] == "bn" and made[-1][0] == "online"


def _archive(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_bengali_model_is_checked_and_only_the_needed_files_are_unpacked(monkeypatch, tmp_path):
    monkeypatch.setenv("REA_VIDEO_MODELS", str(tmp_path))
    d = speech.BN_MODEL_DIR
    arc = _archive({**{f"{d}/{n}": n.encode() for n in speech.BN_MODEL_FILES},
                    f"{d}/test_wavs/0.wav": b"wav", f"{d}/bpe.model": b"bpe", "../escape.txt": b"x"})
    served = {speech.VAD_NAME: b"vad", f"{d}.tar.bz2": arc}
    monkeypatch.setattr(speech, "fetch", lambda url, dst, timeout=60: open(dst, "wb").write(served[url.rsplit("/", 1)[-1]]))
    monkeypatch.setattr(speech, "VAD_SHA256", hashlib.sha256(b"vad").hexdigest())
    with pytest.raises(OSError):  # the archive does not match the pinned checksum
        speech.ensure_bn_models()
    assert sorted(p.name for p in tmp_path.iterdir()) == [speech.VAD_NAME]
    monkeypatch.setattr(speech, "BN_ARCHIVE_SHA256", hashlib.sha256(arc).hexdigest())
    model, vad = speech.ensure_bn_models()
    assert sorted(p.name for p in model.iterdir()) == sorted(speech.BN_MODEL_FILES)
    assert (model / "encoder.onnx").read_bytes() == b"encoder.onnx" and vad.read_bytes() == b"vad"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([d, speech.VAD_NAME])  # SenseVoice is not fetched for Bengali
    assert not (tmp_path.parent / "escape.txt").exists()
    monkeypatch.setattr(speech, "fetch", lambda *a, **k: pytest.fail("should not download again"))
    speech.ensure_bn_models()


def test_flag_and_pref_set_the_language(monkeypatch, tmp_path):
    from rea_video import cli, memory

    monkeypatch.setenv("REA_VIDEO_HOME", str(tmp_path))
    monkeypatch.setenv("REA_ASR_LANG", "auto")  # recorded first, so whatever _asr_lang writes is undone after the test
    monkeypatch.delenv("REA_ASR_LANG")
    cli._asr_lang(types.SimpleNamespace(asr_lang=None))
    assert "REA_ASR_LANG" not in os.environ  # no flag, no pref: transcribe falls back to auto
    memory.set_pref("asr_lang", "bn")
    cli._asr_lang(types.SimpleNamespace(asr_lang=None))
    assert os.environ["REA_ASR_LANG"] == "bn"
    cli._asr_lang(types.SimpleNamespace(asr_lang="auto"))  # the flag beats the pref
    assert os.environ["REA_ASR_LANG"] == "auto"
    with pytest.raises(ValueError):
        memory.set_pref("asr_lang", "hi")
