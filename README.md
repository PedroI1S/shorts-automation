# 🎬 YouTube Shorts Automation Pipeline

An end-to-end local-first automation pipeline designed to generate high-retention, monetization-safe YouTube Shorts and TikToks.

## 🚀 Features

- **Story Hunter & Adaptor**: Scrapes viral premises from Reddit (`r/shortscarystories`, `r/WritingPrompts`, etc.) and rewrites them using local LLMs (Ollama / Nous Hermes 3 / Llama 3) or Gemini API into 50–55 second micro-stories with aggressive 0–3s hooks.
- **Copyright-Safe Gameplay Vault**: Automatically queries and downloads 4K/60fps copyright-free gameplay (Minecraft Parkour, GTA 5 Mega Ramps, Subway Surfers) via `yt-dlp` and caches them locally, picking unique random slices for each video.
- **Natural Voice Synthesis**: Uses Microsoft Neural Voices via `edge-tts` (100% free, no API keys, zero GPU required).
- **Kinetic Subtitles**: Word-chunked animated overlays with drop shadows, high-contrast yellow highlights, and dark rounded badges rendered with Pillow and FFmpeg.
- **9:16 Vertical Assembly**: Automatically crops 16:9 footage to 9:16 (1080x1920) centered, ducks gameplay audio to 5% for ambiance, and burns the subtitles in one pass.

---

## 🛠️ Quick Start

### Test narration and caption timing first (no downloads or uploads)

```bash
./venv/bin/python3 speech_preview.py
```

This creates a short local MP4 on a plain background in `storage/output/`.
Edge TTS now supplies individual word timestamps. Captions use those timestamps,
including pauses, rather than estimating timing from sentence length. Silences
longer than 650 ms in Edge narration are reduced to 350 ms; the same edits are
applied to the caption timestamps. The audio duration is measured with ffprobe.
Each caption render has a separate temporary directory.

Captions keep a three-word phrase visible and highlight only the word currently
being spoken in yellow, using the provider's word start and end times. Between
words the phrase stays white; during longer pauses it clears. Words whose provider
alignment has zero duration remain visible but receive no invented highlight time.
To re-render an existing sample without consuming API quota:

```bash
./venv/bin/python3 speech_preview.py --audio-metadata storage/audio/fish_093cbb6143f5270b.json --output-name preview_fish_word_highlight.mp4
```

Scripts are synthesized as a continuous passage. Repeated dots, ellipses, long
dashes, and layout whitespace are normalized to reduce artificial pauses.
This does not guarantee natural delivery for every voice or script.

For a free-plan ElevenLabs comparison, copy `elevenlabs.local.example.json` to
`elevenlabs.local.json` and fill in your API key and an available voice ID locally.
The credentials file is excluded from Git. Alternatively, set `ELEVENLABS_API_KEY`
and `ELEVENLABS_VOICE_ID` in your shell. The API key needs permission to read the
subscription and generate speech. Never share the key in chat.

```bash
./venv/bin/python3 speech_preview.py --provider elevenlabs
```

Both commands use the same sample text. Use `--text "Your passage"` to compare
another passage (maximum 1,200 characters). The ElevenLabs test checks the account
is on the free plan and has remaining quota, and stops on errors without switching
to paid services. It uses the timestamped speech endpoint, with no additional
transcription call. Generation consumes the account's free allowance.

If ElevenLabs rejects a library voice on the free plan, select a built-in voice
instead. For example, George can be tested without changing the credentials file:

```bash
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb ./venv/bin/python3 speech_preview.py --provider elevenlabs
```

Fish Audio is also available for local comparison. Fill in `fish.local.json`
using the same `api_key` and `voice_id` fields, then run:

```bash
./venv/bin/python3 speech_preview.py --provider fish
```

Fish requests explicitly select `s2.1-pro-free` and never retry with a paid model.
Native timestamp snapshots are combined by content chunk, with chunk offsets
applied to word timings. Raw generation events are saved locally so a failed
render can be retried without another API generation. Fish and ElevenLabs previews
retain the providers' natural pauses; only Edge applies silence shortening.

**ElevenLabs free-plan audio is for noncommercial evaluation.** Free-plan content
cannot be used commercially; shared noncommercial content requires attribution.
See [ElevenLabs usage rules](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform).
The regular upload pipeline remains on Edge TTS; the ElevenLabs option is exposed
only through the local preview CLI.

OpenCode currently lists `deepseek-v4.1-flash-free` as a limited-time free model.
Its documentation restricts free chat-model access to OpenCode itself. This project
does not yet integrate that model; do not substitute a paid direct DeepSeek API
under the assumption it is free. See [OpenCode models](https://dev.opencode.ai/v2/docs/console/models/).

Timing and free-quota regression checks:

```bash
./venv/bin/python3 -m unittest test_speech_timing -v
```

### 1. Run with Default Settings
```bash
cd "/Users/pedro/Documents/Documentos/shorts-automation"
./venv/bin/python3 pipeline.py
```

### 2. Generate on a Specific Topic / Fanfic Prompt
```bash
./venv/bin/python3 pipeline.py --topic "A time traveler who is forbidden to open door number 4"
```

### 3. Sourcing from a Specific Subreddit
```bash
./venv/bin/python3 pipeline.py --reddit "WritingPrompts"
```

### 4. Custom Gameplay Type
```bash
./venv/bin/python3 pipeline.py --gameplay "gta 5 mega ramp car stunts no copyright 4k"
```

---

## 🧠 Using Nous Hermes 3 or Local LLMs via Ollama

To run your storytelling agent 100% locally:
1. Pull Hermes 3:
   ```bash
   ollama pull hermes3
   ```
2. Set your environment variable (or let `config.py` use default `hermes3:latest`):
   ```bash
   export OLLAMA_MODEL="hermes3:latest"
   ```

To use Google Gemini Flash instead, export your key:
```bash
export GEMINI_API_KEY="your-api-key"
```

---

## 💰 YouTube Monetization Best Practices

1. **Avoid 1:1 Copied Text:** YouTube flags verbatim copied Reddit text as "Repetitious / Reused Content". This pipeline always paraphrases and restructures stories into original 130–150 word monologues.
2. **Never Download Copyrighted Clips:** Do not rip gameplay from big creators. Use the automated royalty-free scraper or record 30 minutes of your own Minecraft gameplay into `storage/backgrounds/`.
3. **Pacing Matters:** Retention drops if sentences exceed 4 seconds. The subtitle engine chunks speech into 2–3 words per card to keep viewer eyes glued to the screen.
