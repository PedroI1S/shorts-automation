import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import edge_tts
import requests

from config import AUDIO_DIR, DEFAULT_VOICE, SECRETS_DIR, SPEECH_WORDS_PER_SECOND

# Free built-in Edge voices used only when edge is the explicit provider.
EDGE_CHAT_VOICES = {
    "male": [DEFAULT_VOICE, "en-US-GuyNeural", "en-US-EricNeural"],
    "female": ["en-US-JennyNeural", "en-US-AriaNeural", "en-US-MichelleNeural"],
}


def prepare_text(text: str) -> str:
    """Remove layout pauses and exaggerated punctuation before synthesis."""
    text = re.sub(r"\.{2,}|…+", ".", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("Narration text is empty.")
    return text


def estimate_duration(text: str, provider: str) -> float:
    """Predict narration seconds from word count, without calling any TTS API."""
    if provider not in SPEECH_WORDS_PER_SECOND:
        raise ValueError(f"Unknown speech provider: {provider}")
    return len(prepare_text(text).split()) / SPEECH_WORDS_PER_SECOND[provider]


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def tighten_long_pauses(path: Path, words: list[dict]) -> list[dict]:
    """Shorten detected silences over 650ms to 350ms and retime captions together."""
    detection = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-45dB:d=0.65",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
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
    filters = [
        f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{i}]"
        for i, (start, end) in enumerate(segments)
    ]
    filters.append(
        "".join(f"[a{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=0:a=1[out]"
    )
    processed = path.with_name(path.stem + "_paced.mp3")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(processed),
        ],
        check=True,
    )
    processed.replace(path)

    def retime(timestamp):
        return timestamp - sum(max(0.0, min(timestamp, end) - start) for start, end in cuts)

    adjusted = [
        {**word, "start": retime(word["start"]), "end": retime(word["end"])} for word in words
    ]
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
                words.append(
                    {
                        "text": "".join(p[0] for p in pending),
                        "start": pending[0][1],
                        "end": pending[-1][2],
                    }
                )
                pending = []
        else:
            pending.append((char, start, end))
    if pending:
        words.append(
            {"text": "".join(p[0] for p in pending), "start": pending[0][1], "end": pending[-1][2]}
        )
    return words


async def generate_speech_async(
    text: str, voice: str = DEFAULT_VOICE
) -> tuple[Path, float, list[dict]]:
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
                sentences.append(
                    {"start": start_sec, "end": start_sec + dur_sec, "text": chunk["text"].strip()}
                )

    if not sentences:
        raise RuntimeError("TTS returned no word timestamps; refusing estimated captions.")
    sentences = tighten_long_pauses(audio_path, sentences)
    total_duration = audio_duration(audio_path)
    audio_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "provider": "edge",
                "text": text,
                "voice": voice,
                "duration": total_duration,
                "words": sentences,
            },
            indent=2,
        )
    )
    print(f"[+] Audio generated: {audio_path.name} ({total_duration:.2f}s, {len(sentences)} words)")
    return audio_path, total_duration, sentences


def generate_elevenlabs(
    text: str, voice_override: str | None = None
) -> tuple[Path, float, list[dict]]:
    """Local evaluation using only an ElevenLabs free account; never buy credits."""
    text = prepare_text(text)
    key, voice = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_VOICE_ID")
    credentials_path = SECRETS_DIR / "elevenlabs.local.json"
    if credentials_path.exists() and (not key or not voice):
        credentials = json.loads(credentials_path.read_text())
        key = key or credentials.get("api_key")
        voice = voice or credentials.get("voice_id")
    voice = voice_override or voice
    if not key or not voice:
        raise RuntimeError(
            "Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID, or fill secrets/elevenlabs.local.json locally."
        )
    headers = {"xi-api-key": key}
    sub = requests.get(
        "https://api.elevenlabs.io/v1/user/subscription", headers=headers, timeout=30
    )
    if not sub.ok:
        raise RuntimeError(f"Could not verify ElevenLabs free quota (HTTP {sub.status_code}).")
    account = sub.json()
    if account.get("tier") != "free":
        raise RuntimeError(
            "This test only allows ElevenLabs free accounts; paid usage is disabled."
        )
    remaining = account["character_limit"] - account["character_count"]
    if len(text) > remaining:
        raise RuntimeError("Not enough ElevenLabs free quota; generation skipped.")
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
        headers=headers,
        params={"output_format": "mp3_44100_128"},
        timeout=90,
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
    )
    if not response.ok:
        detail = response.json().get("detail", {})
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        raise RuntimeError(
            f"ElevenLabs generation failed (HTTP {response.status_code}): {message.replace(key, '[REDACTED]')[:500]}"
        )
    data = response.json()
    words = alignment_to_words(data.get("normalized_alignment") or data["alignment"])
    if not words:
        raise RuntimeError("ElevenLabs returned no word timestamps.")
    digest = hashlib.sha256(f"elevenlabs:{voice}:{text}".encode()).hexdigest()[:16]
    path = AUDIO_DIR / f"elevenlabs_{digest}.mp3"
    path.write_bytes(base64.b64decode(data["audio_base64"]))
    duration = audio_duration(path)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "provider": "elevenlabs",
                "text": text,
                "voice": voice,
                "duration": duration,
                "words": words,
                "usage": "Free-plan noncommercial evaluation only",
            },
            indent=2,
        )
    )
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
            words.append(
                {
                    "text": segment["text"].strip(),
                    "start": offset + segment["start"],
                    "end": offset + segment["end"],
                }
            )
    # Providers can return overlapping word ends; each next onset bounds the prior word.
    for word, following in zip(words, words[1:]):
        word["end"] = min(word["end"], following["start"])
    return [word for word in words if word["text"] and word["end"] >= word["start"]]


def generate_fish(text: str, voice_override: str | None = None) -> tuple[Path, float, list[dict]]:
    """Evaluate the explicitly free Fish model with native word timestamps."""
    text = prepare_text(text)
    config_path = SECRETS_DIR / "fish.local.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    key = os.getenv("FISH_API_KEY") or config.get("api_key")
    voice = voice_override or os.getenv("FISH_VOICE_ID") or config.get("voice_id")
    if not key or not voice:
        raise RuntimeError("Fill api_key and voice_id in secrets/fish.local.json locally.")
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
            headers={
                "Authorization": f"Bearer {key}",
                "model": model,
                "Accept": "text/event-stream",
            },
            json={
                "text": text,
                "reference_id": voice,
                "format": "mp3",
                "latency": "normal",
                "chunk_length": 300,
            },
            timeout=(15, 120),
            stream=True,
        ) as response:
            if not response.ok:
                raise RuntimeError(
                    f"Fish free generation failed (HTTP {response.status_code}); no paid fallback."
                )
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise RuntimeError("Unexpected Fish response format; no paid fallback.")
            events = list(read_sse_events(response.iter_lines()))
        events_path.write_text(json.dumps(events))
    audio = b"".join(
        base64.b64decode(event["audio_base64"]) for event in events if event.get("audio_base64")
    )
    if not audio:
        raise RuntimeError("Fish returned no audio; saved response retained for diagnosis.")
    path.write_bytes(audio)
    words = fish_alignment_to_words(events)
    if not words:
        raise RuntimeError(
            "Fish returned no word alignment; no estimated captions or paid transcription."
        )
    duration = audio_duration(path)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "provider": "fish",
                "model": model,
                "text": text,
                "voice": voice,
                "duration": duration,
                "words": words,
                "usage": "Local evaluation",
            },
            indent=2,
        )
    )
    return path, duration, words


def select_story_voice(story: dict, provider: str, default: str = DEFAULT_VOICE) -> str:
    """Use explicit story metadata, never names or incidental female characters."""
    if "female" not in (story.get("protagonist_gender"), story.get("narrator_gender")):
        return default
    if provider == "edge":
        return "en-US-JennyNeural"
    if provider not in ("fish", "elevenlabs"):
        raise ValueError(f"Unknown speech provider: {provider}")
    path = SECRETS_DIR / f"{provider}.local.json"
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    selected = os.getenv(f"{provider.upper()}_FEMALE_VOICE_ID") or settings.get("female_voice_id")
    if not isinstance(selected, str) or not selected.strip():
        raise RuntimeError(
            f"Female protagonist requires female_voice_id in secrets/{provider}.local.json; "
            "narration stopped before spending quota."
        )
    return selected.strip()


def generate_speech(
    text: str, voice: str = DEFAULT_VOICE, provider: str = "edge"
) -> tuple[Path, float, list[dict]]:
    """Synchronous wrapper for generate_speech_async."""
    if provider == "elevenlabs":
        return generate_elevenlabs(text, voice_override=voice if voice != DEFAULT_VOICE else None)
    if provider == "fish":
        return generate_fish(text, voice_override=voice if voice != DEFAULT_VOICE else None)
    if provider != "edge":
        raise ValueError(f"Unknown speech provider: {provider}")
    return asyncio.run(generate_speech_async(text, voice))


def _provider_settings(provider: str) -> dict:
    path = SECRETS_DIR / f"{provider}.local.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def resolve_voice(voice: str, provider: str) -> str:
    """The voice identity generate_speech will actually use, without any TTS call."""
    if provider == "edge" or voice != DEFAULT_VOICE:
        return voice
    if provider not in ("fish", "elevenlabs"):
        raise ValueError(f"Unknown speech provider: {provider}")
    configured = os.getenv(f"{provider.upper()}_VOICE_ID") or _provider_settings(provider).get(
        "voice_id"
    )
    if not isinstance(configured, str) or not configured.strip():
        raise RuntimeError(f"Configure voice_id in secrets/{provider}.local.json.")
    return configured.strip()


def chat_voice_pools(provider: str) -> dict:
    """Distinct voices per gender: the story voice first, then optional chat extras.

    Extras come from chat_extra_voice_ids {"female": [...], "male": [...]} in the
    provider's local settings. Missing extras simply limit same-gender contacts.
    """
    if provider == "edge":
        return {gender: list(voices) for gender, voices in EDGE_CHAT_VOICES.items()}
    if provider not in ("fish", "elevenlabs"):
        raise ValueError(f"Unknown speech provider: {provider}")
    extras = _provider_settings(provider).get("chat_extra_voice_ids") or {}
    pools = {"male": [DEFAULT_VOICE], "female": []}
    try:
        pools["female"].append(select_story_voice({"protagonist_gender": "female"}, provider))
    except RuntimeError:
        pass
    for gender in pools:
        for voice in extras.get(gender) or []:
            if isinstance(voice, str) and voice.strip() and voice.strip() not in pools[gender]:
                pools[gender].append(voice.strip())
    return pools


def chat_contact_capacity(provider: str, protagonist_gender: str) -> dict:
    """How many contacts of each gender can get a voice distinct from everyone else."""
    pools = chat_voice_pools(provider)
    if not pools[protagonist_gender]:
        raise RuntimeError(f"No {protagonist_gender} voice configured for {provider}.")
    return {
        gender: len(voices) - (gender == protagonist_gender) for gender, voices in pools.items()
    }


def chat_voice_plan(story: dict, provider: str) -> dict:
    """Assign one distinct, stable voice to me and to every listed contact, in order."""
    pools = chat_voice_pools(provider)
    gender = story["protagonist_gender"]
    plan = {"me": select_story_voice(story, provider)}
    used = {plan["me"]}
    for contact in story["chat"]["contacts"]:
        voice = next((v for v in pools[contact["gender"]] if v not in used), None)
        if voice is None:
            raise RuntimeError(
                f"Not enough distinct {contact['gender']} voices for this chat (protagonist is "
                f"{gender}); add chat_extra_voice_ids to secrets/{provider}.local.json. "
                "Stopped before spending quota."
            )
        plan[contact["name"]] = voice
        used.add(voice)
    return plan


def chat_voice_identity(story: dict, provider: str) -> str:
    """One stable string for the whole cast, identical across every part of an arc."""
    plan = chat_voice_plan(story, provider)
    return "chat:" + "|".join(f"{who}={resolve_voice(v, provider)}" for who, v in plan.items())


def estimate_chat_duration(chat: dict, provider: str) -> float:
    from shorts_automation.stories.draft_story import chat_gap

    messages = chat["messages"]
    return sum(estimate_duration(m["text"], provider) for m in messages) + sum(
        chat_gap(a, b) for a, b in zip(messages, messages[1:])
    )


def generate_chat_speech(story: dict, provider: str) -> tuple[Path, float, list[dict], dict]:
    """Voice each message with its sender's voice, then join them on one timeline.

    Returns the joined narration, its duration, words tagged with their message
    index and the per-message timeline used by the chat overlay.
    """
    from shorts_automation.stories.draft_story import chat_gap

    plan = chat_voice_plan(story, provider)
    identity = chat_voice_identity(story, provider)
    messages = story["chat"]["messages"]
    clips = []
    for message in messages:
        expected = resolve_voice(plan[message["from"]], provider)
        path, duration, words = generate_speech(
            message["text"], voice=plan[message["from"]], provider=provider
        )
        actual = json.loads(path.with_suffix(".json").read_text(encoding="utf-8")).get("voice")
        if actual != expected:
            raise RuntimeError("A chat message was voiced with an unexpected voice.")
        clips.append((path, duration, words))
    timeline, words_out, cursor = [], [], 0.0
    for index, (message, (path, duration, words)) in enumerate(zip(messages, clips)):
        gap = chat_gap(message, messages[index + 1]) if index + 1 < len(messages) else 0.0
        timeline.append(
            {"start": cursor, "end": cursor + duration, "from": message["from"], "gap_after": gap}
        )
        for word in words:
            start = min(duration, max(0.0, float(word["start"])))
            end = min(duration, max(start, float(word["end"])))
            words_out.append(
                {
                    "text": word["text"],
                    "start": cursor + start,
                    "end": cursor + end,
                    "message": index,
                }
            )
        cursor += duration + gap
    digest = hashlib.sha256(
        json.dumps([provider, identity, messages], sort_keys=True).encode()
    ).hexdigest()[:16]
    output = AUDIO_DIR / f"chat_{digest}.mp3"
    filters = [
        f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,apad,"
        f"atrim=end={item['end'] - item['start'] + item['gap_after']:.6f},asetpts=PTS-STARTPTS[a{i}]"
        for i, item in enumerate(timeline)
    ]
    filters.append(
        "".join(f"[a{i}]" for i in range(len(timeline))) + f"concat=n={len(timeline)}:v=0:a=1[out]"
    )
    command = ["ffmpeg", "-v", "error", "-y"]
    for path, _, _ in clips:
        command += ["-i", str(path)]
    partial = output.with_name(output.stem + ".partial.mp3")
    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(partial),
    ]
    subprocess.run(command, check=True, capture_output=True)
    partial.replace(output)
    duration = audio_duration(output)
    output.with_suffix(".json").write_text(
        json.dumps(
            {
                "provider": provider,
                "format": "chat",
                "voice": identity,
                "voices": {who: resolve_voice(v, provider) for who, v in plan.items()},
                "duration": duration,
                "messages": timeline,
                "words": words_out,
                "clips": [str(path) for path, _, _ in clips],
            },
            indent=2,
        )
    )
    print(f"[+] Chat voiced: {len(messages)} messages, {len(plan)} voices, {duration:.2f}s")
    return output, duration, words_out, {"messages": timeline, "voice": identity}


if __name__ == "__main__":
    sample = (
        "Rule number one: Never open the basement door after midnight. My brother broke that rule."
    )
    audio_file, dur, blocks = generate_speech(sample)
    print("Audio file:", audio_file)
    print("Duration:", dur)
    print("Blocks:", blocks)
