import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from config import (
    AUDIO_DIR,
    DEFAULT_VOICE,
    KOKORO_PYTHON,
    KOKORO_REPO,
    KOKORO_SPEED,
    KOKORO_TIMEOUT_SECONDS,
    KOKORO_VOICES,
    SPEECH_WORDS_PER_SECOND,
    TEMP_DIR,
)

PROVIDER = "kokoro"
WORKER = Path(__file__).with_name("kokoro_worker.py")


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


def _check_provider(provider: str) -> None:
    if provider != PROVIDER:
        raise ValueError(f"Unknown speech provider: {provider}")


def resolve_voice(voice: str, provider: str) -> str:
    """The voice identity generate_speech will actually use, without any TTS call."""
    _check_provider(provider)
    # English Kokoro voices only: a = American, b = British; f/m = female/male.
    if not isinstance(voice, str) or not re.fullmatch(r"[ab][fm]_[a-z]+", voice):
        raise ValueError(f"Not an English Kokoro voice: {voice!r}")
    return voice


def _kokoro_path(text: str, voice: str) -> Path:
    key = f"kokoro:{KOKORO_REPO}:{voice}:{KOKORO_SPEED}:{text}"
    return AUDIO_DIR / f"kokoro_{hashlib.sha256(key.encode()).hexdigest()[:16]}.mp3"


def synthesize_kokoro(items: list[tuple[str, str]]) -> None:
    """Render every uncached (text, voice) pair in one local worker run.

    The worker loads the model once per batch. The metadata JSON is written last,
    so it marks a complete cached narration that later calls reuse.
    """
    pending = {}
    for text, voice in items:
        text = prepare_text(text)
        path = _kokoro_path(text, resolve_voice(voice, PROVIDER))
        if not path.with_suffix(".json").exists():
            pending[path] = (text, voice)
    if not pending:
        return
    if not KOKORO_PYTHON.is_file():
        raise RuntimeError(
            f"Kokoro environment not found at {KOKORO_PYTHON}; run scripts/windows/setup_windows.ps1."
        )
    with tempfile.TemporaryDirectory(dir=TEMP_DIR) as tmp:
        tmp = Path(tmp)
        request = {
            "repo": KOKORO_REPO,
            "speed": KOKORO_SPEED,
            "result": str(tmp / "result.json"),
            "items": [
                {"text": text, "voice": voice, "wav": str(tmp / f"{index}.wav")}
                for index, (text, voice) in enumerate(pending.values())
            ],
        }
        (tmp / "request.json").write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            [str(KOKORO_PYTHON), "-I", str(WORKER), str(tmp / "request.json")],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=KOKORO_TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode:
            raise RuntimeError(f"Kokoro synthesis failed: {result.stderr.strip()[-800:]}")
        outputs = json.loads((tmp / "result.json").read_text(encoding="utf-8"))["items"]
        for (path, (text, voice)), output in zip(pending.items(), outputs, strict=True):
            if not output["words"]:
                raise RuntimeError(
                    "Kokoro returned no word timestamps; refusing estimated captions."
                )
            partial = path.with_name(path.stem + ".partial.mp3")
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    output["wav"],
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(partial),
                ],
                check=True,
                capture_output=True,
            )
            partial.replace(path)
            path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "provider": PROVIDER,
                        "model": KOKORO_REPO,
                        "text": text,
                        "voice": voice,
                        "speed": KOKORO_SPEED,
                        "duration": audio_duration(path),
                        "words": output["words"],
                    },
                    indent=2,
                )
            )


def select_story_voice(story: dict, provider: str, default: str = DEFAULT_VOICE) -> str:
    """Use explicit story metadata, never names or incidental female characters."""
    _check_provider(provider)
    if "female" in (story.get("protagonist_gender"), story.get("narrator_gender")):
        return KOKORO_VOICES["female"][0]
    return default


def generate_speech(
    text: str, voice: str = DEFAULT_VOICE, provider: str = PROVIDER
) -> tuple[Path, float, list[dict]]:
    """Local Kokoro narration with native word timestamps."""
    _check_provider(provider)
    text = prepare_text(text)
    synthesize_kokoro([(text, voice)])
    path = _kokoro_path(text, voice)
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    print(f"[+] Audio generated: {path.name} ({metadata['duration']:.2f}s, {voice})")
    return path, metadata["duration"], metadata["words"]


def chat_voice_pools(provider: str) -> dict:
    """Distinct voices per gender from KOKORO_VOICES: the story voice first."""
    _check_provider(provider)
    return {gender: list(voices) for gender, voices in KOKORO_VOICES.items()}


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
                f"{gender}); add voices to KOKORO_VOICES in config.py. "
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
    # One worker run voices every uncached message; the loop below reads the cache.
    synthesize_kokoro([(message["text"], plan[message["from"]]) for message in messages])
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
