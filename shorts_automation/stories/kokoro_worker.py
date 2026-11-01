"""Kokoro-82M synthesis worker. Runs under .venv-kokoro (Python 3.12), never the main venv.

    python -I kokoro_worker.py request.json

The request is {"repo", "speed", "result", "items": [{"text", "voice", "wav"}]}. Each
item is written as a 24 kHz WAV; the result JSON lists {"wav", "duration", "words"} per
item in request order. The model loads once per language for the whole batch.
"""

import json
import sys
from pathlib import Path

SAMPLE_RATE = 24000


def _is_punctuation(text: str) -> bool:
    return not any(char.isalnum() for char in text)


def tokens_to_words(tokens, offset: float, chunk_duration: float) -> list[dict]:
    """Kokoro tokens -> caption words with absolute times.

    Punctuation tokens join the neighbouring word instead of becoming caption words.
    Missing timestamps are bounded by the neighbouring words so no word is dropped.
    """
    words, prefix = [], ""
    for token in tokens or []:
        text = (token.text or "").strip()
        if not text:
            continue
        if _is_punctuation(text):
            # Trailing marks ("word," / "word.") stick to the word before them;
            # an opening mark with no word yet waits for the next word.
            if words and not words[-1]["spaced"]:
                words[-1]["text"] += text
                words[-1]["spaced"] = bool(token.whitespace)
            else:
                prefix += text
            continue
        words.append(
            {
                "text": prefix + text,
                "start": token.start_ts,
                "end": token.end_ts,
                "spaced": bool(token.whitespace),
            }
        )
        prefix = ""
    for index, word in enumerate(words):
        if word["start"] is None:
            word["start"] = words[index - 1]["end"] if index else 0.0
        if word["end"] is None:
            following = next(
                (w["start"] for w in words[index + 1 :] if w["start"] is not None), None
            )
            word["end"] = chunk_duration if following is None else following
    for word, following in zip(words, words[1:]):
        word["end"] = min(word["end"], following["start"])
    result = []
    for word in words:
        start = min(chunk_duration, max(0.0, float(word["start"])))
        end = min(chunk_duration, max(start, float(word["end"])))
        result.append(
            {"text": word["text"], "start": round(offset + start, 3), "end": round(offset + end, 3)}
        )
    return result


def main(request_path: str) -> None:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    pipelines, results = {}, []
    for item in request["items"]:
        lang = item["voice"][0]
        if lang not in pipelines:
            pipelines[lang] = KPipeline(lang_code=lang, repo_id=request["repo"])
        chunks, words, offset = [], [], 0.0
        for output in pipelines[lang](item["text"], voice=item["voice"], speed=request["speed"]):
            if output.audio is None:
                continue
            audio = output.audio.numpy()
            duration = len(audio) / SAMPLE_RATE
            words += tokens_to_words(output.tokens, offset, duration)
            chunks.append(audio)
            offset += duration
        if not chunks:
            raise RuntimeError("Kokoro returned no audio.")
        sf.write(item["wav"], np.concatenate(chunks), SAMPLE_RATE)
        results.append({"wav": item["wav"], "duration": offset, "words": words})
    Path(request["result"]).write_text(json.dumps({"items": results}), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
