"""Speech worker for wise-scholar.

Runs in its own environment (see pyproject.toml). The app talks to it over JSON lines:
one request object per line on stdin, one response object per line on stdout.

    {"op": "tts", "text": "...", "lang": "de", "out": "/path/file.wav"} -> {"ok": true, "engine": "chatterbox"}
    {"op": "stt", "path": "/path/clip.webm", "lang": "de"|null}      -> {"ok": true, "text": "...", "language": "de", "words": [...]}
    {"op": "status"}                                                -> {"ok": true, "tts": "chatterbox"|"piper"|null, "stt": true}

`python worker.py --download` fetches every model once, so nothing is downloaded while learning.
Text-to-speech uses Chatterbox Multilingual on the GPU and Piper on the CPU when the GPU model cannot load.
"""
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

MODELS = Path(os.environ.get("WISE_SCHOLAR_SPEECH_MODELS", Path(__file__).parent / "models"))
WHISPER = os.environ.get("WISE_SCHOLAR_WHISPER", "small")
PIPER_VOICES = {"de": "de_DE-thorsten-medium", "en": "en_US-lessac-medium"}
# ponytail: one Chatterbox voice per language, the model's own; reference clips come with the podcast bead
CHATTERBOX_LANGS = {"ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh"}


def base_language(tag: str) -> str:
    """'de-DE' -> 'de': the models take bare language codes."""
    return tag.split("-")[0].lower()


class Speech:
    def __init__(self):
        self.tts_engine = None
        self.chatterbox = None
        self.piper = {}
        self.whisper = None

    def load_tts(self) -> str | None:
        if self.tts_engine is None:
            try:
                import torch
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS

                if not torch.cuda.is_available():
                    raise RuntimeError("no CUDA device")
                self.chatterbox = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
                self.tts_engine = "chatterbox"
            except Exception as e:
                print(f"chatterbox unavailable, using piper: {e!r}", file=sys.stderr)
                self.tts_engine = "piper"
        return self.tts_engine

    def tts(self, text: str, lang: str, out: str) -> dict:
        lang = base_language(lang)
        engine = self.load_tts()
        if engine == "chatterbox" and lang in CHATTERBOX_LANGS:
            import torchaudio

            wav = self.chatterbox.generate(text, language_id=lang)
            torchaudio.save(out, wav, self.chatterbox.sr, encoding="PCM_S", bits_per_sample=16)
            return {"ok": True, "engine": "chatterbox"}
        name = PIPER_VOICES.get(lang)
        if not name:
            return {"ok": False, "error": f"no voice for language {lang!r}; Chatterbox needs the GPU, Piper has voices for {sorted(PIPER_VOICES)}"}
        if lang not in self.piper:
            from piper import PiperVoice

            model = MODELS / f"{name}.onnx"
            if not model.exists():
                return {"ok": False, "error": f"Piper voice {name} is not downloaded; run `make speech`"}
            self.piper[lang] = PiperVoice.load(str(model))
        with wave.open(out, "wb") as f:
            self.piper[lang].synthesize_wav(text, f)
        return {"ok": True, "engine": "piper"}

    def stt(self, path: str, lang: str | None) -> dict:
        if self.whisper is None:
            import torch
            from faster_whisper import WhisperModel

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.whisper = WhisperModel(WHISPER, device=device, compute_type="float16" if device == "cuda" else "int8",
                                        download_root=str(MODELS), local_files_only=True)
        segments, info = self.whisper.transcribe(
            path, language=base_language(lang) if lang else None, word_timestamps=True, vad_filter=True
        )
        words = []
        text = []
        for segment in segments:
            text.append(segment.text.strip())
            words += [{"word": w.word.strip(), "start": w.start, "end": w.end, "prob": w.probability} for w in segment.words or []]
        return {"ok": True, "text": " ".join(text), "language": info.language, "words": words}

    def status(self) -> dict:
        return {"ok": True, "tts": self.tts_engine, "stt": self.whisper is not None}


def download() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel

    WhisperModel(WHISPER, device="cpu", compute_type="int8", download_root=str(MODELS))
    subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(MODELS), *PIPER_VOICES.values()], check=True)
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    print("speech models ready")


def serve() -> None:
    # The libraries print to stdout; keep that channel for responses only.
    out, sys.stdout = sys.stdout, sys.stderr
    speech = Speech()
    for line in sys.stdin:
        req = json.loads(line)
        try:
            if req["op"] == "tts":
                res = speech.tts(req["text"], req["lang"], req["out"])
            elif req["op"] == "stt":
                res = speech.stt(req["path"], req.get("lang"))
            elif req["op"] == "status":
                res = speech.status()
            else:
                res = {"ok": False, "error": f"unknown op {req['op']!r}"}
        except Exception as e:
            res = {"ok": False, "error": repr(e)}
        print(json.dumps(res), file=out, flush=True)


if __name__ == "__main__":
    download() if "--download" in sys.argv else serve()
