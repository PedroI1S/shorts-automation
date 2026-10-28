# Local story evaluation

First new narration test completed on Windows: recovered the approved sample
voice IDs into the otherwise blank local credential fields (keys never printed).
Fish `s2.1-pro-free` generated `storage/audio/fish_c1e6ea37e8ca62f2.mp3` with
146 timestamped words and 56.293813 seconds of narration. Cached metadata rendered
to `storage/output/first_story_fish_preview.mp4` with 148 highlight states.
No background footage is present yet; this preview uses the plain dark background.
ElevenLabs's restored voice is the approved built-in George evaluation voice.

Hermes subscription login (`openai-codex`, `gpt-6.1-terra`) now drafts original
stories without Reddit, Ollama, Gemini or provider fallback:

```powershell
$env:PYTHONUTF8 = '1'
$env:HERMES_HOME = [Environment]::GetEnvironmentVariable('HERMES_HOME','User')
.venv\Scripts\python.exe draft_story.py --topic 'Your original horror premise'
```

The command disables session tools, limits tool turns, enforces a 150-second
client timeout, rejects failed/duplicate results and observed tool events, and
validates a 4–8-word title and 130–150-word narration. It does not retry failed
generation automatically. A timeout is a client limit; remote work might finish
after disconnection. Subscription usage is consumed, with no paid API fallback.

Drafts are saved under unique `storage/stories/story_<id>.json` filenames with
provider, model, topic, UTC creation time and word count. Word count is not a
duration guarantee. Review every draft before audio generation.

First live test: `storage/stories/story_fffedb5e31864563bb9e779e28f6d8b4.json`,
"The Room Beneath the Ringing", 146 words.

To render a reviewed draft with privately configured Fish credentials and your
own/licensed background footage:

```powershell
.venv\Scripts\python.exe pipeline.py --story-file storage/stories/story_fffedb5e31864563bb9e779e28f6d8b4.json --tts-provider fish --background-file storage/backgrounds/my_footage.mp4
```

This generates new TTS and consumes the provider's allowance. Do not run until
credentials and the free model offer are verified locally. ElevenLabs remains
available through `--tts-provider elevenlabs` with its existing free-account
guards. Never paste keys into chat. No voice credential files or background
footage were present during this implementation.

The explicit file options skip story generation/Reddit and footage downloading.
Unreadable footage is rejected before TTS. After synthesis, narration plus its
0.8s tail must fit 58 seconds and the footage must cover that full duration.
Outputs use unique suffixes to avoid overwriting prior renders. Accepted speech
timing and moving yellow captions are unchanged. No uploads occur here.

The legacy pipeline path without `--story-file` still uses content_hunter's
old fallbacks; it has not been migrated. Durable job state, retries, duplicate
prevention and scheduling corrections remain outstanding. A full story render
has not yet been tested on Windows with new narration and supplied footage.
