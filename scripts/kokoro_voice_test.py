"""Offline Kokoro-82M (Hugging Face) voice test. Run with the isolated venv:

    .venv-kokoro/Scripts/python.exe scripts/kokoro_voice_test.py [--voices am_fenrir,af_heart] [--speed 1.1]

Writes MP3 samples and word-timestamp JSON to storage/voice_tests/kokoro/.
Does not touch the production pipeline, database or any paid API.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24000
OUT_DIR = Path(__file__).resolve().parents[1] / "storage" / "voice_tests" / "kokoro"
DEFAULT_TEXT = (
    "My neighbor has been mowing his lawn at three in the morning for six weeks. "
    "Last night I finally walked over to ask him why. "
    "He turned off the mower, looked straight at me, and whispered, "
    "if I stop, they can hear the house breathing. "
    "Then I noticed his lawn was perfectly short. He wasn't cutting grass at all."
)
# Highest-graded English voices from the model card, plus deeper male narrators.
DEFAULT_VOICES = "af_heart,af_bella,am_fenrir,am_michael,am_puck,bm_george"


def synthesize(pipeline: KPipeline, text: str, voice: str, speed: float):
    chunks, words, offset = [], [], 0.0
    for result in pipeline(text, voice=voice, speed=speed):
        audio = result.audio.numpy()
        for token in result.tokens or []:
            if token.start_ts is not None and token.end_ts is not None and token.text.strip():
                words.append(
                    {
                        "word": token.text,
                        "start": round(offset + token.start_ts, 3),
                        "end": round(offset + token.end_ts, 3),
                    }
                )
        chunks.append(audio)
        offset += len(audio) / SAMPLE_RATE
    return np.concatenate(chunks), words


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default=DEFAULT_VOICES)
    parser.add_argument("--speed", type=float, default=1.1)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    load_start = time.perf_counter()
    voices = args.voices.split(",")
    pipelines = {}
    print(f"Speed {args.speed} | {len(args.text.split())} words")
    for voice in voices:
        lang = voice[0]  # 'a' = American, 'b' = British
        if lang not in pipelines:
            pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
            print(f"Loaded pipeline '{lang}' in {time.perf_counter() - load_start:.1f}s")

        start = time.perf_counter()
        audio, words = synthesize(pipelines[lang], args.text, voice, args.speed)
        elapsed = time.perf_counter() - start
        duration = len(audio) / SAMPLE_RATE

        wav = OUT_DIR / f"{voice}.wav"
        mp3 = OUT_DIR / f"{voice}.mp3"
        sf.write(wav, audio, SAMPLE_RATE)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "192k", str(mp3)],
            check=True,
        )
        wav.unlink()
        (OUT_DIR / f"{voice}.words.json").write_text(json.dumps(words, indent=1), encoding="utf-8")
        print(
            f"{voice:<11} {duration:5.1f}s audio in {elapsed:5.1f}s "
            f"(RTF {elapsed / duration:.2f}) | {len(words)} timed words -> {mp3.name}"
        )


if __name__ == "__main__":
    main()
