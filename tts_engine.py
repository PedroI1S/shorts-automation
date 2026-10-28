import asyncio
import hashlib
import base64
import json
import os
import re
import subprocess
from pathlib import Path
import edge_tts
import requests
from config import AUDIO_DIR, DEFAULT_VOICE, BASE_DIR

def prepare_text(text: str) -> str:
    """Remove layout pauses and exaggerated punctuation before synthesis."""
    text = re.sub(r"\.{2,}|…+", ".", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("Narration text is empty.")
    return text


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def tighten_long_pauses(path: Path, words: list[dict]) -> list[dict]:
    """Shorten detected silences over 650ms to 350ms and retime captions together."""
    detection = subprocess.run([
        "ffmpeg", "-hide_banner", "-i", str(path), "-af",
        "silencedetect=noise=-45dB:d=0.65", "-f", "null", "-",
    ], capture_output=True, text=True, check=True)
    cuts, silence_start = [], None
    for line in detection.stderr.splitlines():
        match = re.search(r"silence_start: ([\d.]+)", line)
        if match:
            silence_start = float(match[1])
        match = re.search(r"silence_end: ([\d.]+)", line)
        if match and silence_start is not None:
            end = float(match[1])
            if end - silence_start > 0.65:
                cuts.append((silence_start + 0.175, end - 0.175))
            silence_start = None
    if not cuts:
        return words
    duration = audio_duration(path)
    segments, cursor = [], 0.0
    for start, end in cuts:
        segments.append((cursor, start))
        cursor = end
    if cursor < duration:
        segments.append((cursor, duration))
    filters = [f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{i}]"
               for i, (start, end) in enumerate(segments)]
    filters.append("".join(f"[a{i}]" for i in range(len(segments))) +
                   f"concat=n={len(segments)}:v=0:a=1[out]")
    processed = path.with_name(path.stem + "_paced.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path),
                    "-filter_complex", ";".join(filters), "-map", "[out]",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(processed)], check=True)
    processed.replace(path)
    def retime(timestamp):
        return timestamp - sum(max(0.0, min(timestamp, end) - start) for start, end in cuts)
    adjusted = [{**word, "start": retime(word["start"]), "end": retime(word["end"])}
                for word in words]
    print(f"[+] Shortened {len(cuts)} long pauses; caption timestamps adjusted with audio.")
    return adjusted


def alignment_to_words(alignment: dict) -> list[dict]:
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    if not (len(chars) == len(starts) == len(ends)):
        raise ValueError("ElevenLabs returned inconsistent alignment arrays.")
    words, pending = [], []
    for char, start, end in zip(chars, starts, ends):
        if char.isspace():
            if pending:
                words.append({"text": "".join(p[0] for p in pending),
                              "start": pending[0][1], "end": pending[-1][2]})
                pending = []
        else:
            pending.append((char, start, end))
    if pending:
        words.append({"text": "".join(p[0] for p in pending),
                      "start": pending[0][1], "end": pending[-1][2]})
    return words


async def generate_speech_async(text: str, voice: str = DEFAULT_VOICE) -> tuple[Path, float, list[dict]]:
    """Generates audio file and boundary timestamps using edge-tts."""
    text = prepare_text(text)
    text_hash = hashlib.sha256(f"edge:{voice}:{text}".encode()).hexdigest()[:16]
    audio_path = AUDIO_DIR / f"narration_{text_hash}.mp3"
    
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    sentences = []
    
    with open(audio_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start_sec = chunk["offset"] / 10_000_000
                dur_sec = chunk["duration"] / 10_000_000
                sentences.append({
                    "start": start_sec,
                    "end": start_sec + dur_sec,
                    "text": chunk["text"].strip()
                })

    if not sentences:
        raise RuntimeError("TTS returned no word timestamps; refusing estimated captions.")
    sentences = tighten_long_pauses(audio_path, sentences)
    total_duration = audio_duration(audio_path)
    audio_path.with_suffix(".json").write_text(json.dumps({"provider": "edge", "text": text,
        "voice": voice, "duration": total_duration, "words": sentences}, indent=2))
    print(f"[+] Audio generated: {audio_path.name} ({total_duration:.2f}s, {len(sentences)} words)")
    return audio_path, total_duration, sentences

def generate_elevenlabs(text: str) -> tuple[Path, float, list[dict]]:
    """Local evaluation using only an ElevenLabs free account; never buy credits."""
    text = prepare_text(text)
    key, voice = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_VOICE_ID")
    credentials_path = BASE_DIR / "elevenlabs.local.json"
    if credentials_path.exists() and (not key or not voice):
        credentials = json.loads(credentials_path.read_text())
        key = key or credentials.get("api_key")
        voice = voice or credentials.get("voice_id")
    if not key or not voice:
        raise RuntimeError("Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID, or fill elevenlabs.local.json locally.")
    headers = {"xi-api-key": key}
    sub = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers, timeout=30)
    if not sub.ok:
        raise RuntimeError(f"Could not verify ElevenLabs free quota (HTTP {sub.status_code}).")
    account = sub.json()
    if account.get("tier") != "free":
        raise RuntimeError("This test only allows ElevenLabs free accounts; paid usage is disabled.")
    remaining = account["character_limit"] - account["character_count"]
    if len(text) > remaining:
        raise RuntimeError("Not enough ElevenLabs free quota; generation skipped.")
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
        headers=headers, params={"output_format": "mp3_44100_128"}, timeout=90,
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
    )
    if not response.ok:
        detail = response.json().get("detail", {})
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        raise RuntimeError(f"ElevenLabs generation failed (HTTP {response.status_code}): {message.replace(key, '[REDACTED]')[:500]}")
    data = response.json()
    words = alignment_to_words(data.get("normalized_alignment") or data["alignment"])
    if not words:
        raise RuntimeError("ElevenLabs returned no word timestamps.")
    digest = hashlib.sha256(f"elevenlabs:{voice}:{text}".encode()).hexdigest()[:16]
    path = AUDIO_DIR / f"elevenlabs_{digest}.mp3"
    path.write_bytes(base64.b64decode(data["audio_base64"]))
    duration = audio_duration(path)
    path.with_suffix(".json").write_text(json.dumps({"provider": "elevenlabs", "text": text,
        "voice": voice, "duration": duration, "words": words,
        "usage": "Free-plan noncommercial evaluation only"}, indent=2))
    return path, duration, words


def read_sse_events(lines):
    """Decode SSE data fields; events may span multiple lines."""
    pending = []
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line:
            if pending:
                payload = "\n".join(pending)
                pending = []
                if payload != "[DONE]":
                    yield json.loads(payload)
        elif line.startswith("data:"):
            pending.append(line[5:].lstrip())
    if pending and "\n".join(pending) != "[DONE]":
        yield json.loads("\n".join(pending))


def fish_alignment_to_words(events: list[dict]) -> list[dict]:
    """Replace cumulative snapshots per chunk, then convert to absolute times."""
    chunks = {}
    for event in events:
        if event.get("alignment") is not None:
            chunks[event["chunk_seq"]] = event
    words = []
    for seq in sorted(chunks):
        event = chunks[seq]
        offset = event["chunk_audio_offset_sec"]
        for segment in event["alignment"]["segments"]:
            words.append({"text": segment["text"].strip(),
                          "start": offset + segment["start"],
                          "end": offset + segment["end"]})
    # Providers can return overlapping word ends; each next onset bounds the prior word.
    for word, following in zip(words, words[1:]):
        word["end"] = min(word["end"], following["start"])
    return [word for word in words if word["text"] and word["end"] >= word["start"]]


def generate_fish(text: str) -> tuple[Path, float, list[dict]]:
    """Evaluate the explicitly free Fish model with native word timestamps."""
    text = prepare_text(text)
    config_path = BASE_DIR / "fish.local.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    key = os.getenv("FISH_API_KEY") or config.get("api_key")
    voice = os.getenv("FISH_VOICE_ID") or config.get("voice_id")
    if not key or not voice:
        raise RuntimeError("Fill api_key and voice_id in fish.local.json locally.")
    model = "s2.1-pro-free"
    digest = hashlib.sha256(f"fish:{model}:{voice}:{text}".encode()).hexdigest()[:16]
    path = AUDIO_DIR / f"fish_{digest}.mp3"
    events_path = path.with_suffix(".events.json")
    # Re-render saved responses without consuming another generation.
    if events_path.exists():
        events = json.loads(events_path.read_text())
    else:
        with requests.post(
            "https://api.fish.audio/v1/tts/stream/with-timestamp",
            headers={"Authorization": f"Bearer {key}", "model": model,
                     "Accept": "text/event-stream"},
            json={"text": text, "reference_id": voice, "format": "mp3",
                  "latency": "normal", "chunk_length": 300},
            timeout=(15, 120), stream=True,
        ) as response:
            if not response.ok:
                raise RuntimeError(f"Fish free generation failed (HTTP {response.status_code}); no paid fallback.")
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise RuntimeError("Unexpected Fish response format; no paid fallback.")
            events = list(read_sse_events(response.iter_lines()))
        events_path.write_text(json.dumps(events))
    audio = b"".join(base64.b64decode(event["audio_base64"]) for event in events if event.get("audio_base64"))
    if not audio:
        raise RuntimeError("Fish returned no audio; saved response retained for diagnosis.")
    path.write_bytes(audio)
    words = fish_alignment_to_words(events)
    if not words:
        raise RuntimeError("Fish returned no word alignment; no estimated captions or paid transcription.")
    duration = audio_duration(path)
    path.with_suffix(".json").write_text(json.dumps({"provider": "fish", "model": model,
        "text": text, "voice": voice, "duration": duration, "words": words,
        "usage": "Local evaluation"}, indent=2))
    return path, duration, words


def generate_speech(text: str, voice: str = DEFAULT_VOICE, provider: str = "edge") -> tuple[Path, float, list[dict]]:
    """Synchronous wrapper for generate_speech_async."""
    if provider == "elevenlabs":
        return generate_elevenlabs(text)
    if provider == "fish":
        return generate_fish(text)
    if provider != "edge":
        raise ValueError(f"Unknown speech provider: {provider}")
    return asyncio.run(generate_speech_async(text, voice))

if __name__ == "__main__":
    sample = "Rule number one: Never open the basement door after midnight. My brother broke that rule."
    audio_file, dur, blocks = generate_speech(sample)
    print("Audio file:", audio_file)
    print("Duration:", dur)
    print("Blocks:", blocks)
