# Handoff: YouTube Shorts workflow and Windows migration

## Project relocation — 2026-10-28

Active project path: `C:\Users\Pedro\Documents\shorts-automation`.
Copied the OneDrive project, verified the full file inventory/sizes and root
file hashes (including credential files without printing contents), repaired
native venv launchers and updated stored output paths in SQLite and render
metadata. All 32 tests, pip check and SQLite integrity check pass. Two render
history rows remain; repeated import after relocation adds no duplicates.

Automatic approval review blocked removal of the original OneDrive copy. That
old copy remains and must not be used for new jobs; its database is now stale.
Open the new folder in Codex/PowerShell. Tell Hermes the new project path in
Telegram; old sessions may still remember the OneDrive location.

## Windows continuation — 2026-10-28

Latest database update: added SQLite render/story/source claims with transactional
reservations, completion/failure handling, persistent crash reservations and
manual recovery safeguards. Pipeline blocks duplicate story before TTS and used
sources during sourcing, with a final atomic source reservation before render.
Imported two previous gameplay renders. See DATABASE.md. No publishing enabled.

Latest sourcing update: gameplay_fetcher.py replaced with bounded Commons API
discovery, license/provenance filtering, streamed downloads, muted H.264
normalization and query-scoped checksummed cache. No unrelated local fallback.
Live download/cache-only reuse/full Fish-story pipeline render passed. 23 tests
pass. Default source is voxel cave-maze gameplay, not continuous parkour. Clips
retain visual-review/publication-uncleared status. See GAMEPLAY_SOURCES.md.

Latest workflow update: added draft_story.py, tested live with Hermes subscription
Terra (146-word original draft), plus four draft validation tests. All 16 tests
pass. Pipeline now accepts --story-file, --background-file and explicit Fish or
ElevenLabs selection. Added duration gates and unique output filenames. See
STORY_WORKFLOW.md. Voice credential files and background footage are absent,
so a full new-story render remains pending. The old default content_hunter path
is unchanged; prefer the explicit saved-draft workflow.

Reboot/sign-in test passed by user report and log inspection: login startup ran,
initial Telegram DNS/network failures recovered automatically after about a
minute, and the bot replied. Startup is delayed until network recovery; crash
recovery and unattended production remain unverified.

Latest: Telegram's numeric allowlist is corrected; one inbound Telegram message
and completed Hermes reply were verified. Hermes login startup is installed via
the Startup-folder VBS fallback (Scheduled Task creation required admin approval,
which was not used). The exact Startup VBS passed a stop/relaunch smoke test.
Real reboot/sign-in and crash recovery remain untested. No production tasks or
uploads enabled. See HERMES_WINDOWS_NEXT.md for current state over older notes.

Latest remote-control update: user completed subscription model selection.
Hermes `openai-codex` / `gpt-6.1-terra` passed an authenticated inference and
terminal `pwd` tool call in this project. Fixed a Windows MAX_PATH SDK import
failure with a local short-path activation change in Hermes; details and backup
location are in HERMES_WINDOWS_NEXT.md. Manual gateway restarted successfully;
Telegram credentials/allowlist remain unconfigured in the checked profile.
No gateway auto-start or production publishing enabled.

The target PC now passed `setup_windows.ps1` (12/12 tests) and
`run_preview_windows.ps1`. Python 3.13.15 and FFmpeg 9.0.2 are installed;
the native `.venv` is ready. Cached Fish preview rendered in 6.41 seconds,
fully decoded successfully, and three extracted frames verified the moving
yellow I / HEARD / MY highlight. See WINDOWS_VALIDATION.md for details.

Hermes v0.22.5 is installed and its CLI version verified inside Codex; gateway
status is stopped. Automatic borrowed CLI logins are disabled, provider fallbacks
are empty, and the background skill curator is paused. Verify the launcher in a
fresh external PowerShell because Windows AppData redirection affected install.
Private local credential steps are tracked in HERMES_WINDOWS_NEXT.md.
The user has no free model API account or Telegram bot
yet. Groq Free is the proposed first model test; no authenticated model or
Telegram connection has been verified. No publishing or production tasks enabled.

The original Mac-session history below is retained; statements that nothing is
installed on Windows describe the earlier session, not this continuation.

Prepared 2026-10-28 from the working Mac session. This is a continuation brief,
not a claim that the system is ready for unattended production. Inspect the files
and target environment before making changes. Provider offers and tool interfaces
below were checked during this session and should be reverified when relevant.

## What the user wants

Build an inexpensive AI-assisted YouTube Shorts workflow that can eventually run
on an always-on PC. The format so far is original short horror/thriller narration,
vertical background gameplay, and readable captions. The user may later explore
other visual formats. No final channel strategy or upload volume is agreed.

The original result disappointed the user because captions drifted from the
speech and the narration paused unnaturally. We fixed the caption timing and
tested better TTS services. The user liked both Fish and ElevenLabs samples,
preferred the selected Fish voice, and explicitly said to keep both available.
The user then requested a yellow highlight on the word being spoken. That is
implemented and was visually verified on rendered frames.

Current priority is setting up the other computer and remote maintenance.
The user is transferring this folder/ZIP and will continue with another GPT
session on that PC. Carry the work forward; do not restart the architecture
discussion or regenerate the successful samples merely to prove APIs work.

## Hardware, operating system, budget, and control preferences

- Target PC: AMD Ryzen 5 4600G with integrated graphics, 16 GB DDR4 RAM.
- User explicitly chose to keep Windows and may use it for other work.
- Mac was the development machine. Its virtual environment cannot be copied into
  Windows; create `.venv` on the PC. Python 3.13 is the setup script's target.
- No paid subscriptions, API top-ups, provider upgrades, or paid fallback usage
  have been authorized. Use existing free allowances and local cached media.
  The user may reconsider spending if results look promising; that is not current
  authorization to spend.
- User wants to fix things remotely with Hermes Agent and explicitly chose
  Telegram as the remote-control interface.
- User already uses **MonoCode**, repository:
  https://github.com/hardbeat920/monocode
  They initially called it Monopode/Monocode interchangeably; this is now resolved.
- MonoCode is a GUI that runs installed CLIs and reuses their logins. The user's
  free DeepSeek V4.1 Flash access is through OpenCode in MonoCode, not a verified
  direct API connection available to Hermes.
- Relevant timezone from the original environment: America/Sao_Paulo. Confirm
  channel publishing timezone rather than assuming the new Windows clock is UTC.

## Intended roles of the tools

1. Python + FFmpeg: deterministic video generation.
2. Windows Task Scheduler: start production jobs and manage their schedule once
   persistence, retry, and duplicate handling are implemented.
3. Hermes + Telegram: remote maintenance, inspection, and user-requested fixes.
4. MonoCode + OpenCode: familiar coding interface, including remote sessions
   from the Mac to the Windows PC if desired.

These tools can coexist. The user values Hermes's phone access; do not replace
that preference merely because MonoCode can connect remotely too. Hermes still
needs a compatible model connection; no working one has been configured here.

## What is implemented and tested

### Speech (`tts_engine.py`)

The common return value is `(audio_path, duration_seconds, word_blocks)`, where
each word block contains `text`, `start`, and `end` in seconds.

- `prepare_text` collapses layout whitespace, converts ellipses to periods, and
  converts long dashes to commas before synthesis.
- Edge TTS explicitly requests `WordBoundary` instead of sentence boundaries.
- Edge alone shortens detected silence longer than 650 ms to 350 ms using FFmpeg.
  The same cuts retime the word timestamps. This was verified on a live sample;
  it is a pacing heuristic, not an acoustic alignment guarantee for every voice.
- Duration is measured with ffprobe rather than guessed from the last boundary.
- Generated audio gets a JSON sidecar with text, provider, voice, duration, words.
- File hashes include provider/voice/text (and Fish model) so voices do not share
  the same narration filename.
- Fish and ElevenLabs samples retain their natural pauses for comparison.

### Fish Audio

- Credentials: `fish.local.json`, fields `api_key` and `voice_id` (Fish reference ID).
  Environment overrides: `FISH_API_KEY`, `FISH_VOICE_ID`.
- Exact selected model header: `s2.1-pro-free`; never silently substitute a paid
  model. Fish's docs say missing/unknown model headers can fall back to paid.
- Endpoint: `POST https://api.fish.audio/v1/tts/stream/with-timestamp`.
- SSE returns base64 audio fragments plus cumulative alignment snapshots per
  `chunk_seq`. Concatenate audio fragments in arrival order, REPLACE alignment
  snapshots for each chunk, then add `chunk_audio_offset_sec` to segment times.
- Snapshots are saved as `.events.json` and reused to avoid another generation
  when re-rendering. Metadata-only previews do not need a key at all.
- Overlapping segment ends are clipped to the next word onset. Zero-duration
  words must remain in caption text: the tested article "a" had start=end.
- Fish sample has 31 caption words and 10.50 seconds of narration.
- The free offer was listed at $0 through November 30, 2026, subject to fair use.
  Recheck current availability. General terms and free-API commercial descriptions
  were not entirely consistent, so commercial publication rights remain unresolved.

### ElevenLabs

- Credentials: `elevenlabs.local.json`, fields `api_key`, `voice_id`.
  Environment overrides: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.
- Endpoint: `/v1/text-to-speech/{voice_id}/with-timestamps`.
- Model: `eleven_multilingual_v2`, stability 0.5, similarity boost 0.75,
  `mp3_44100_128` output. Convert character alignment to word intervals.
- Current test code verifies `/v1/user/subscription`, requires account tier `free`,
  checks available character quota, then generates. It deliberately rejects paid
  accounts in this testing phase and never purchases or falls back to a paid API.
- First failure was HTTP 401: missing `user_read` permission. User enabled it.
- The user's chosen library voice then returned HTTP 402 because free accounts
  cannot use library voices through the API. That is not an invalid-key problem.
- We fetched built-in voices and successfully tested **George**, voice ID
  `JBFqnCBsd6RMkjVDRZzb`, via a temporary environment override. We did NOT replace
  the user's original voice selection in their credential file. That saved voice
  may still trigger HTTP 402 if used unchanged.
- The key was able to list voices; free account and speech generation worked.
- ElevenLabs sample has 31 caption words and 9.06 seconds of narration.
- ElevenLabs free-plan output was confirmed to be noncommercial, with attribution
  required if shared. Keep these outputs for evaluation; paid commercial terms
  would need a separate decision before monetized publication.
- ElevenLabs generation currently has no response cache. Use metadata-only
  previews to avoid wasting its allowance on repeated renders.

### Captions (`subtitle_engine.py`)

- `build_caption_cues` groups up to three actual timestamped words into a phrase.
  Long pauses split phrases. No character-count timing or minimum-duration padding.
- `build_highlight_cues` emits states for each word onset/end within a phrase.
  The phrase stays fixed while only the active word turns yellow. Short silent
  gaps have no highlighted word; long gaps clear the card.
- Zero-duration words remain visible in their phrase, with no fabricated highlight
  duration. A whole phrase with no positive duration is rejected.
- `create_subtitle_image(..., highlight_index=...)` renders transparent PNG cards,
  white words, yellow current word, black stroke, dark rounded badge.
- The text layout stays in place as the highlight advances. Word advance uses
  Pillow text length rather than repeatedly adding stroke width.
- Caption cards are still single-line, generally three words. Very long words
  may need fitting/wrapping later; do not claim general overflow is solved.
- Each render owns a unique `storage/temp/captions_*` directory. It no longer
  deletes another render's slides or shares one mutable concat file.
- FFconcat uses `option framerate 1000` per image to avoid accumulated 25fps image
  duration rounding. Export remains 30fps, so visible timing is frame-quantized.
- Final caption clears, followed by the 0.8s compiler tail.
- This works using FFmpeg and Pillow without requiring the libass filter.
- `config.py` now finds Mac, Windows Impact/Arial Bold, or Linux DejaVu fonts.
  `SUBTITLE_FONT_PATH` can override selection.

### Preview CLI (`speech_preview.py`)

Generates a local 1080x1920, 30fps, H.264/AAC MP4 on a plain dark background.
No story generation, gameplay download, or upload. Supports `edge`, `fish`, and
`elevenlabs`; `--text` limits new test input to 1,200 characters.

`--audio-metadata` loads an existing narration JSON and adjacent MP3, bypassing
all generation calls and ignoring the normal text/provider selection. Optional
`--output-name` preserves old comparison files under a new MP4 filename.

The default comparison passage is:

> I heard my phone ring from the kitchen. But it was already in my hand.
> The screen lit up with a message from my own number. Don't answer the other phone.

## Tests and accepted artifacts

`test_speech_timing.py` contains **12 passing regression tests**, covering:
word/card timing, long pauses, rejection of sentence estimates, character-to-word
alignment, exact concat duration, SSE parsing, snapshot replacement, chunk offsets,
zero-duration article preservation, moving highlight, and free-only quota guards.

Both highlighted MP4s were fully decoded with FFmpeg without errors. Frames
showing `I HEARD MY` were inspected at three successive times; yellow moved from
`I` to `HEARD` to `MY` without shifting the caption. The user approved the earlier
voice/caption samples and said the moving highlight was much better.

Included in the transfer package:

- `storage/audio/fish_093cbb6143f5270b.mp3`
- `storage/audio/fish_093cbb6143f5270b.json`
- `storage/audio/fish_093cbb6143f5270b.events.json`
- `storage/audio/elevenlabs_8b96ba29bc458d05.mp3`
- `storage/audio/elevenlabs_8b96ba29bc458d05.json`
- `storage/output/preview_fish_word_highlight.mp4`
- `storage/output/preview_elevenlabs_word_highlight.mp4`

There are no API keys in those media sidecars/events. Voice IDs are public
identifiers, not API keys. The comparison outputs are local evaluation artifacts.

## Windows setup files and first steps

- `requirements.txt`: seven direct dependencies pinned to versions installed on
  the Mac. The Mac environment used Python 3.15; Windows 3.13 compatibility still
  needs to be verified. Do not claim the Windows installation already passed.
- `setup_windows.ps1`: checks Python launcher/3.13 and FFmpeg/ffprobe, creates
  `.venv`, installs dependencies, and runs regression checks.
- `run_preview_windows.ps1`: renders included Fish metadata/audio offline to
  `storage/output/windows_caption_test.mp4`.
- Both scripts set `PYTHONUTF8=1` and use `.venv\Scripts\python.exe` explicitly.
  Native Windows console encoding matters because project logs contain emoji.
- `SETUP_WINDOWS.md`: installation, Telegram and MonoCode guide with source links.
- `.gitignore`: excludes environments, storage, `.env`, local credential files,
  Google OAuth files and `deployment/`.
- `build_transfer_package.py`: builds a small whitelisted ZIP without credentials,
  huge background downloads, or the Mac environment. Exclusion by this builder
  is explicit; `.gitignore` alone does not protect a manually zipped folder.

On the Windows PC, start in the extracted project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_preview_windows.ps1
```

That Bypass is process-scoped. No scheduled tasks or uploads are created by these
scripts. Install missing prerequisites on the actual PC, then resolve any package,
font, FFconcat-path, audio, or encoding issues. Paths containing apostrophes and
native Windows FFmpeg paths have not been exhaustively tested.

Reuse ElevenLabs offline as well:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe speech_preview.py --audio-metadata storage/audio/elevenlabs_8b96ba29bc458d05.json --output-name windows_elevenlabs_test.mp4
```

Keys existed and worked on the Mac. They are intentionally not included in the
prepared ZIP. The user can transfer `fish.local.json` / `elevenlabs.local.json`
privately or enter them locally from the blank example files. Never print keys
to check whether they exist; report field presence or sanitized API errors only.

## Full pipeline: important implementation gaps

The improved preview is real and tested. These remaining defects were identified
in review; do not confuse them with already-fixed caption problems.

1. **Main CLI still uses Edge.** `generate_speech` supports all three providers,
   and `run_pipeline(tts_provider=...)` accepts them programmatically, but
   `pipeline.py --tts-provider` only accepts `edge`. `batch_generator.py` also
   uses Edge defaults. Fish/ElevenLabs have not been integrated into full daily
   production with provider-specific voice selection or licensing decisions.
2. **No OpenCode story integration.** `content_hunter.py` still tries local Ollama
   (`hermes3:latest`, a model distinct from Hermes Agent), then a Gemini endpoint,
   then one of three fixed stories. No Hermes/MonoCode/OpenCode orchestration is
   implemented in this Python project.
3. **Gemini fallback is stale.** It hardcodes `gemini-2.0-flash`, which official
   docs listed as shut down. Do not enable a paid replacement automatically.
4. **Story validation is weak.** Any script with at least 80 words passes; no
   upper word limit or measured-duration regeneration is enforced. The 45/58s
   constants are unused. A 300-word mocked response was accepted in review.
5. **Malformed Ollama JSON skips Gemini.** Provider fallback happens before
   validation, so malformed nonempty output goes straight to a fixed template.
   Templates ignore requested topics and have no deduplication. The initial
   disappointing video title matched one of those templates.
6. **Scheduling timezone is wrong.** Batch code creates naive local timestamps
   then appends `Z`. 09:00 Sao Paulo should be 12:00 UTC, not 09:00 UTC. Slots
   above count 3 wrap to the same day/time, and past slots are accepted. YouTube
   documented that past publishAt timestamps cause immediate publication.
7. **Uploads are not idempotent.** Returned video IDs are not stored; processing
   a manifest twice uploads every item twice. No retry/backoff or uncertain-upload
   reconciliation. Standalone upload defaults public. No real uploads were done
   in this session, and unattended publication has not been enabled.
8. **Batch state is fragile.** Manifest is written only after the whole batch,
   so a crash can lose records for completed renders. Titles are reconstructed
   from truncated filenames rather than preserved generation metadata. Same-date
   reruns/filename collisions can overwrite files; Windows rename semantics may
   differ. Use unique jobs and durable stage state, likely SQLite.
9. **Gameplay cache needs work.** Each batch passes a search query, forcing a
   download attempt even with usable cache; random selection can ignore that
   query. Short or unreadable footage is accepted rather than rejected/looped.
   A download can fall back to an unrelated latest MP4. Large partial downloads
   and AV1 source decoding caused overhead on the Mac; avoid transferring those.
10. **Renderer is basic.** `video_compiler.py` uses CPU libx264 `fast`, CRF20,
    scale/crop to 1080x1920 and a single FFmpeg render. Gameplay audio is mixed
    at constant 6%, not true sidechain ducking; amix normalization may affect
    narration volume. It does not loop short backgrounds. Hardware encoding on
    the Ryzen iGPU is untested; benchmark CPU first and verify available encoders.
11. **Lifecycle/cleanup.** Unique caption directories fix slide conflicts, but
    cleanup, atomic output publication, per-job locks, and bounded disk usage
    remain. Global narration filenames can still collide for simultaneous jobs
    with identical text and voice. Do one render at a time initially.
12. **Content/business assumptions.** README and banners still overclaim
    "monetization-ready", "copyright-safe" and "high-retention". Searching for
    "no copyright" does not establish footage rights; paraphrasing a Reddit post
    does not establish originality or monetization eligibility. Use owned or
    explicitly licensed assets, preserve sources, and verify current policies
    before publishing. No analytics feedback loop is implemented.

## Remote control status and facts checked

Nothing has been installed on the Windows PC from this session. Hermes,
Telegram, MonoCode remote SSH, and Windows scheduled tasks are not configured.
The source Mac and target PC do not share a working process/environment.

### Hermes + Telegram

Hermes supports native Windows. Official install command for Windows PowerShell:

```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

Then reopen PowerShell; use `hermes model` for the model setup and
`hermes gateway setup` to select Telegram. User creates a bot with @BotFather,
enters the token locally, and allows their numeric Telegram user ID only.
Do not put tokens or API keys in Telegram messages or handoff documents.

Official gateway commands: `hermes gateway install`, `hermes gateway start`,
`hermes gateway status`. Native Windows registration starts at USER LOGON, not
guaranteed before sign-in after a reboot. Also, the docs describe a detached VBS
launcher: Task Scheduler's launcher success is not proof the gateway stays alive.
Test actual restart/crash/reboot behavior before calling it resilient.

Hermes includes its own cron and no-agent script jobs, but the current proposed
production scheduler is separate so rendering does not depend on conversational
agent availability. No need to use an LLM for every deterministic pipeline step.

### OpenCode model access

The user first thought their working setup was an OpenCode API key, then corrected
that they were using MonoCode connected to CLI. Reading the provided repository
confirmed that MonoCode runs installed CLIs and reuses existing logins.

OpenCode's official Hermes integration guide currently says free chat models return
HTTP 403 from Hermes; supported direct providers cover paid/Go access. Therefore
do not assume free `deepseek-v4.1-flash-free` can be used as Hermes's direct model.
Actual provider IDs/version behavior should be verified rather than guessed.

Possible legitimate avenues: use OpenCode CLI as a constrained story generator,
and separately configure a supported free model for Hermes; or use a documented
CLI-backed Hermes integration if one is available and appropriate. Hermes's
ability to delegate a coding task to OpenCode is not evidence that OpenCode can
be its main reasoning provider. No such bridge was implemented or tested here.
Do not spoof client headers or buy a subscription as a workaround.

### MonoCode remote sessions

Repository docs confirm remote Windows sessions over SSH. On the Mac:
Settings -> Connections -> Add machine. Windows host prerequisites include
OpenSSH Server, PowerShell 5.1, Task Scheduler, and the installed/logged-in agent
under the connecting account. MonoCode downloads its matching host package.

The feature is experimental. On Windows, user must stay signed in and PC awake;
locking and SSH disconnect are okay, signing out/reboot interrupts agents and
service resumes at next login. Source remains on the host; it is not file sync.
No connection, bot, or remote host setup was performed in this session.

## Suggested order for the next session

1. Read this handoff and verify Windows environment/project path.
2. Install/check prerequisites, create native `.venv`, run 12 tests and offline
   Fish preview; verify the moving highlight and measure render runtime.
3. Set up Hermes native Windows + Telegram with the user's chosen free-compatible
   model route. Resolve model access separately; do not accidentally enable billing.
   If useful, connect MonoCode from the Mac to OpenCode on the PC over SSH.
4. Transfer voice credentials privately and verify availability only when needed;
   no need to repeat successful API calls just for setup.
5. Implement bounded original-story generation using the chosen model connection;
   select providers explicitly, save script and all asset metadata.
6. Test one full-length story with supplied/owned background footage, selected
   Fish or built-in ElevenLabs voice, and the accepted moving highlight.
7. Add durable jobs/retries/deduplication, fix timezone/future-slot scheduling,
   and test failures/reboot before installing unattended production tasks.
8. Enable publishing only within the user's actual instruction and applicable
   content rights. Migration/setup alone is not an instruction to publish videos.

The user has already approved the visual direction of the captions. Focus on
making the accepted result portable and repeatable before redesigning it.

## Primary sources used in this session

- MonoCode CLI behavior: https://github.com/hardbeat920/monocode/blob/main/docs/providers.md
- MonoCode remote Windows behavior: https://github.com/hardbeat920/monocode/blob/main/docs/remote-access.md
- Hermes Windows: https://hermes-agent.nousresearch.com/docs/user-guide/windows-native
- Hermes Telegram: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram/
- Hermes gateway: https://hermes-agent.nousresearch.com/docs/user-guide/messaging
- Hermes providers: https://hermes-agent.nousresearch.com/docs/integrations/providers
- Hermes cron: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
- OpenCode/Hermes: https://dev.opencode.ai/v2/docs/console/harnesses/hermes
- OpenCode free model list: https://dev.opencode.ai/v2/docs/console/models/
- Fish schema: https://docs.fish.audio/api-reference/openapi.json
- Fish pricing: https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits
- Fish free offer: https://fish.audio/blog/s2-1-pro-free-api/
- Fish terms: https://fish.audio/terms/
- ElevenLabs timestamps: https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps
- ElevenLabs free rights: https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform
- YouTube publishAt: https://developers.google.com/youtube/data/reference/rest/v3/videos#status.publishAt
- YouTube monetization: https://support.google.com/youtube/answer/1311392?hl=en

No external messages were sent, no YouTube videos were uploaded, and no paid
services or subscriptions were purchased in the Mac session.
