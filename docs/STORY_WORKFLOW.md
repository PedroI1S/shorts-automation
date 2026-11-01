# Stories, narration and captions

The automatic path uses original English horror premises and Hermes drafting,
not Reddit rewriting or a local Ollama model. Manual saved drafts use the same
validation and render pipeline. See [queue operations](ORCHESTRATOR.md) for retries.

## Saved drafts

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m shorts_automation.stories.draft_story --topic 'A night guard finds his name on a future visitor log'
```

Hermes uses the existing openai-codex / gpt-6.1-terra subscription login, with
session tools disabled, bounded turns and a 150-second timeout per call. Drafting
now makes two calls: an original draft, then a final editorial rewrite checking
causality, narrator knowledge, continuity and the frightening payoff. It does
not buy credits or switch to a paid provider. Draft JSON is saved under unique
storage/stories filenames with model/topic/time/word-count metadata.
Each call allows at most one repair for malformed JSON or length validation;
tool use and failed model sessions are never retried as format repairs. The six
latest saved endings are included as repetition exclusions. No paid fallback exists.

The horror brief lives in prompts/story_horror.md. Use one clear threat, immediate
stakes, sensible character actions and a planted detail that pays off. Supernatural
events do not need a forced ordinary explanation. Avoid unrelated last-second
villains and twists that require missing facts. New drafts carry story_revision
horror-v2 plus explicit protagonist_gender and narrator_gender. The first-person
protagonist and narrator must agree. Editorial checks improve the prompt but do
not guarantee subjective story quality; review new samples before more full renders.

Validation requires a 4-8 word title and nonempty script of at most 146 words.
The prompt caps drafts at 140 words but sets no minimum length or duration.
Quality, clarity and a complete frightening payoff determine length; do not pad
stories to reach a time target. The pipeline estimates duration before TTS and
checks measured duration afterward to retain the 58-second maximum including
the silent tail. Positive, finite narration below 45 seconds is accepted.
Queue retries are bounded; the standalone draft CLI does not regenerate indefinitely.

To render a saved draft with supplied footage:

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.rendering.pipeline --story-file <story.json> --tts-provider fish --background-file <footage.mp4>
```

Fresh narration consumes allowance. Source/story identity is reserved through
SQLite, including for supplied footage. The automatic worker obtains creator
footage before spending TTS allowance; see [footage research](FOOTAGE_RESEARCH.md).

## Series-only production and chat arcs (2026-10-31)

The user moved automatic production to series only, alternating arc formats.
With `story_format="series"` in secrets/production.json, every new automatic
release belongs to a 3/4-part arc, and `series_formats` (default
`["narrated", "chat"]`) is cycled one arc at a time, continuing from the most
recently created arc. No new standalone is drafted. Already drafted standalone
jobs keep their slots and render normally. Slots too close to prepare a whole
arc (`series_min_lead_hours`) are skipped instead of being filled with a
standalone. Unlike mixed mode, a low reserve starts an arc immediately because
there is no standalone fallback.

Narrated arcs are the existing first-person horror format below. Chat arcs are
first-person relationship drama (cheating, betrayal, revenge) from
prompts/story_chat_series.md, using drama premises from production.py. Each
part is one text thread between "me" (the protagonist) and one listed contact:

- Drafting validates contacts (1-3, explicit gender), 4-18 messages, at most
  30 words per message and 115 message words per part, no emoji, links,
  handles or phone numbers, and a conservative duration estimate including
  pauses. The same draft-then-editorial-rewrite flow and atomic bundle apply.
- Every message is voiced separately with its sender's voice and joined with
  0.25 s pauses (0.5 s when the other person answers). "Me" uses the normal
  story voice for the protagonist's gender; each contact gets a distinct voice.
  With only `voice_id` and `female_voice_id` configured, the drafter is told
  that contacts must be the opposite gender. Optional
  `chat_extra_voice_ids: {"female": [...], "male": [...]}` in the provider's
  secrets file unlocks same-gender contacts. Voices are planned before any TTS
  call; a missing voice stops the job without spending allowance.
- The overlay (shorts_automation/rendering/chat_overlay.py) draws a generic
  message card with the contact's initial and name. Each bubble appears when its
  sender starts speaking, the spoken word gets the yellow highlight, a typing
  indicator fills the pause before the contact replies, and older bubbles scroll
  off. Part labels and continuation cues match narrated arcs.
- The narration sidecar records `voice` as one identity string for the whole
  cast (`chat:me=<voice>|<contact>=<voice>`), so series voice-consistency and
  outdated-format checks work unchanged. Uploads use drama tags and hashtags.

Draft a chat arc manually (spends model allowance only):
`python -m shorts_automation.stories.series_story --format chat --gender female --topic "..."`.
An offline preview, voiced with local stand-in voices, is in
storage/reviews/chat_preview_20261031/.

## Narrated horror upgrade (2026-10-31)

prompts/story_horror_series.md now carries the full craft rules of the
standalone brief plus series-specific ones: Part 1 opens on its most disturbing
concrete event; later parts answer the cliffhanger within two sentences; every
nonfinal part ends on a specific danger, discovery or forced decision; the
threat follows one learnable rule that is tested in the middle and used in the
finale; at most one other named character; a planted clue explains the ending.
The editorial rewrite checks each of these.

Horror premises from production.py now include one threat rule (for example
"it gets closer each time the narrator ignores it"). The drafter also receives
the titles and bibles of the six most recent saved arcs of the same format and
is told not to repeat them. New narrated drafts are rejected and repaired when a
part opens with a warm-up cliché ("It was a normal night", "My name is",
"To this day"...) or uses a stock ending ("everything went black", "it was all a
dream"). Saved arcs are never re-judged by these lists. The `horror-v2` story
revision is unchanged, so already prepared videos stay current.

## Stories across 3–4 Shorts

Mixed mode (`story_format="mixed"`, superseded by series-only on 2026-10-31)
remains available. There, three standalone releases separate serial arcs. The worker prefers alternating 3- and
4-part arcs, using a supported length that fits consecutive free publishing slots.
Each part uses one normal Short slot; the schedule stays 07:00, 12:00 and 19:00
America/New_York. Already drafted, rendered and scheduled standalone jobs are retained.

The series brief is prompts/story_horror_series.md. One complete arc and continuity
bible are drafted together, then the whole arc receives an editorial rewrite.
Early parts end with a concrete cliffhanger; the next part answers it promptly
while escalating the same threat. The final part resolves the central danger and
planted clue, with an optional unsettling implication. There is no fake promise
of a Part 5 or padding to reach a duration target. Each script retains the 140-word
prompt target, 146-word validation ceiling and 58-second measured video maximum.

The protagonist, gender, provider and actual narration voice stay consistent.
Every script is saved before the first TTS call, under
storage/stories/series/<series-id>/manifest.json and part_01.json, part_02.json, etc.
Bundle admission is atomic; a restart reuses the same complete draft. An overlong
or altered part requires inspection of the arc instead of independently redrafting
one episode and breaking continuity. Ordinary source/render failures retain the bundle.

The worker renders at most one part per pass. It validates every part and checks
voice consistency before approving or scheduling Part 1. Prepared parts are then
uploaded in story order, at consecutive assigned slots. A finished arc can briefly
raise the future scheduled reserve above four; another arc is not started while
the reserve is full. If the reserve is below its minimum or the next release is
too close, a standalone replacement takes priority over starting a new series.

Video overlays show PART 1/3 (or 1/4). Nonfinal parts display a continuation cue
during their final two seconds, including the existing silent tail; speech timing,
yellow word highlighting and video length are unchanged. The final part has no
continuation cue. YouTube titles use `Part 1/3: <series title> #shorts`, with the
same searchable name throughout. Descriptions point viewers toward the next part
on the channel without claiming it is already public. Telegram upload notices
identify the series part too.

For a text-only draft on demand (two bounded model calls, no TTS/upload):

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.stories.series_story --topic 'A recorded voice predicts each attempted escape' --parts 3
```

This command saves a review bundle; it does not queue or publish it. Automatic
production creates its own durable series reservation. Inspect existing automatic
parts with `orchestrator.py status` and `orchestrator.py show <job-id>`.
Queue scheduling refuses missing/unapproved continuations, changed voices, reversed
order and uncertain earlier uploads. Bulk dry runs preview the whole arc without
fake IDs or state changes. YouTube uploads are separate API operations: a lost
response can still leave a partially scheduled series requiring explicit channel
inspection and reconciliation. Later parts stay blocked in that case.

## Voice providers

- Fish is preferred with the selected local voice and the explicit s2.1-pro-free
  model. Cached events/audio avoid repeating synthesis on rendering retries.
- Female protagonists/narrators select female_voice_id from the active provider's
  ignored local JSON, or FISH_FEMALE_VOICE_ID / ELEVENLABS_FEMALE_VOICE_ID. Fish is
  locally configured with Fish Official Delia, tagged female/en-us (American English);
  the original selected voice remains the default. Voice IDs participate in audio
  cache identity. Missing female configuration stops before TTS instead of using
  the male default. Edge selects en-US-JennyNeural for female-led stories.
- Gender is explicit metadata, never inferred from a name or incidental character.
  Legacy drafts without gender retain their existing default and need annotation
  before rerendering if they have a female protagonist. Existing videos are not
  automatically regenerated by this change.
- ElevenLabs remains available with free-account/quota guards and no paid fallback.
- Edge remains available for local evaluation. It tightens long silence and retimes
  its word boundaries accordingly.

Credentials stay in ignored local files or provider-specific environment variables.
The user verified Fish's restriction concerns selling generated voice products and
accepted narrated Shorts use. This is recorded as user verification in secrets/production.json.
Public scheduling was explicitly enabled on 2026-10-29. No paid upgrade or provider
fallback is authorized. The free-offer expiry guard remains in force.

## Caption behavior

Captions use provider word timestamps, show a fixed phrase, and move yellow to the
active spoken word. Gaps are not filled with invented speech timing. Zero-duration
articles are retained in a neighboring audible phrase; entirely untimed speech is
rejected. Each render owns a separate generated caption directory.

Recheck accepted caption behavior without AI calls:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\rendering\run_preview_windows.ps1
```

Early sample measurements and comparison history are preserved in
[the historical story notes](history/STORY_WORKFLOW_EARLY.md).
