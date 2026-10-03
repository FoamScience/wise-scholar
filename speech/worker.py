"""Speech worker for wise-scholar.

Runs in its own environment (see pyproject.toml). The app talks to it over JSON lines:
one request object per line on stdin, one response object per line on stdout.

    {"op": "tts", "text": "...", "lang": "de", "out": "/path/file.wav"} -> {"ok": true, "engine": "chatterbox"}
    {"op": "stt", "path": "/path/clip.webm", "lang": "de"|null}      -> {"ok": true, "text": "...", "language": "de", "words": [...]}
    {"op": "align", "path": "/path/clip.webm", "text": "..."}        -> {"ok": true, "words": [{"word": "...", "score": 0.0-1.0, "start": s, "end": s}]}
    {"op": "status"}                                                -> {"ok": true, "tts": "chatterbox"|"piper"|null, "stt": true}

`python worker.py --download` fetches every model once, so nothing is downloaded while learning.
Text-to-speech uses Chatterbox Multilingual on the GPU and Piper on the CPU when the GPU model cannot load.
Alignment uses torchaudio's MMS_FA bundle (CC-BY-NC 4.0): the recording is force-aligned to the romanized
target text, and each word's score is the mean emission probability of its characters.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
import wave
from pathlib import Path

MODELS = Path(os.environ.get("WISE_SCHOLAR_SPEECH_MODELS", Path(__file__).parent / "models"))
os.environ.setdefault("TORCH_HOME", str(MODELS / "torch"))
WHISPER = os.environ.get("WISE_SCHOLAR_WHISPER", "small")
PIPER_VOICES = {"de": "de_DE-thorsten-medium", "en": "en_US-lessac-medium"}
# ponytail: one Chatterbox voice per language, the model's own; reference clips come with the podcast bead
CHATTERBOX_LANGS = {"ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh"}


def base_language(tag: str) -> str:
    """'de-DE' -> 'de': the models take bare language codes."""
    return tag.split("-")[0].lower()


def romanize(word: str) -> str:
    """What the aligner's dictionary can hold: ascii letters and apostrophes, umlauts and ß folded."""
    folded = unicodedata.normalize("NFKD", word.replace("ß", "ss")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z']", "", folded)


class Speech:
    def __init__(self):
        self.tts_engine = None
        self.chatterbox = None
        self.piper = {}
        self.whisper = None
        self.aligner = None

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

    def align(self, path: str, text: str) -> dict:
        import torch
        from faster_whisper.audio import decode_audio
        from torchaudio.pipelines import MMS_FA as bundle

        if self.aligner is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.aligner = (bundle.get_model(with_star=False).to(device).eval(), bundle.get_tokenizer(), bundle.get_aligner(), device)
        model, tokenizer, aligner, device = self.aligner
        words = [w for w in re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", text) if romanize(w)]
        if not words:
            return {"ok": False, "error": "the text has no alignable words"}
        audio = torch.from_numpy(decode_audio(path, sampling_rate=bundle.sample_rate)).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = model(audio.to(device))
        spans = aligner(emission[0], tokenizer([romanize(w) for w in words]))
        seconds = audio.size(1) / emission.size(1) / bundle.sample_rate
        out = []
        for word, span in zip(words, spans):
            weight = sum(s.end - s.start for s in span) or 1
            out.append({
                "word": word,
                "score": round(sum(s.score * (s.end - s.start) for s in span) / weight, 3),
                "start": round(span[0].start * seconds, 2),
                "end": round(span[-1].end * seconds, 2),
            })
        return {"ok": True, "words": out}

    def status(self) -> dict:
        return {"ok": True, "tts": self.tts_engine, "stt": self.whisper is not None}


def download() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel

    WhisperModel(WHISPER, device="cpu", compute_type="int8", download_root=str(MODELS))
    subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(MODELS), *PIPER_VOICES.values()], check=True)
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    from torchaudio.pipelines import MMS_FA

    MMS_FA.get_model(with_star=False)
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
            elif req["op"] == "align":
                res = speech.align(req["path"], req["text"])
            elif req["op"] == "status":
                res = speech.status()
            else:
                res = {"ok": False, "error": f"unknown op {req['op']!r}"}
        except Exception as e:
            res = {"ok": False, "error": repr(e)}
        print(json.dumps(res), file=out, flush=True)


if __name__ == "__main__":
    download() if "--download" in sys.argv else serve()
