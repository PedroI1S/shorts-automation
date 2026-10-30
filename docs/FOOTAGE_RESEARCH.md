# Working AGY creator-download supply

Reference: https://www.youtube.com/watch?v=u7kdVe8q5zs.
Desired footage is clear, smooth first-person Minecraft parkour, not dark
Minetest caves. The strong brief is [prompts/agy_footage_supply.md](../prompts/agy_footage_supply.md).

## How research works

AGY's headless mode denied RunCommand requests. Neither normal auto mode nor
planning mode solved that. The working implementation does not grant broader
terminal permissions:

1. AGY returns three concrete search queries in JSON.
2. `creator_evidence.py` performs bounded, public YouTube searches/metadata reads
   and follows links actually present in creator descriptions. It does not use
   browser logins, private credentials, checkout, purchases or paid APIs.
3. MediaFire download buttons are resolved from the public page and verified
   against a real HTTP 200 video response. Unknown/gated links stay unverified.
   Local/private destinations and checkout paths are rejected.
4. AGY ranks a compact packet of this actual evidence in an isolated temporary
   workspace, without the coding project's local-file instructions. Its findings
   are checked against independently fetched file evidence before acceptance.
5. `creator_footage.py` independently rechecks the current description's quoted
   permission and posted download link, then refreshes the public file URL.
   It imports a real 60-second segment with FFmpeg HTTP seeking and retains
   original creator/permission/download provenance. Subsequent renders use the
   next unreserved disjoint window (5-65s, 65-125s, 125-185s, and so on), recorded
   in SQLite. Whole-recording history remains protected, while new segment-aware
   claims permit unused portions of the same source. Expiring file URLs are not
   used as source identity.

Evidence is compacted to fit Windows' command-line length limit. Full evidence,
search plan and final rankings are saved in storage/reviews/agy_creator_sources_*.
No full source video is passed to AGY and it must not claim visual inspection.
Local previews can be inspected separately.

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m shorts_automation.footage.agy_footage_research --count 4
.\.venv\Scripts\python.exe -m shorts_automation.footage.creator_footage
```

To rerank a prior public packet without repeating network reads:

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.footage.agy_footage_research --count 4 --evidence <path-to-evidence.json>
```

The production config now selects `creator_downloads`. It uses unused eligible
creator cache first; otherwise it invokes the complete research/import flow.
Sourcing errors retain the saved story and do not consume new TTS quota.

## Verified live result

Successful AGY catalog: storage/reviews/agy_creator_sources_980cbb42fb/sources.json.
Fresh end-to-end repeat also succeeded at
storage/reviews/agy_creator_sources_a439fdb299/sources.json (one verified free
source plus three candidates with recorded blockers).
The agent selected GameplayHUB's Minecraft parkour recording and retained four
other candidates with concrete access/verification blockers.

- Creator video: https://www.youtube.com/watch?v=WGP0e-hQxXg
- Creator-posted download: https://mediafire.com/file/wg99erobc8adt4l/Minecraft+Parcour.mp4/file
- Public file headers: HTTP 200, video/mp4, 835,894,518 bytes.
- Independent FFprobe: 1920x1080, 60fps, H.264/AAC, 409.7 seconds.
- Description allows free use for TikTok, YouTube Shorts or other content and
  says no credit is needed. The full description and source evidence are retained.
- Imported stock: storage/backgrounds/creator_WGP0e-hQxXg.mp4 (60 seconds,
  no looping, no YouTube stream extraction).
- Visual review: attractive, readable Minecraft parkour with shaders and
  colored landing platforms, substantially closer to the reference than the
  cave demo. A center crop can lose peripheral platforms on turns; review the
  supplied vertical preview rather than assuming every second crops perfectly.
- Preview files: storage/reviews/minecraft_creator_quality/creator_60fps_*.mp4.

Public scheduling was explicitly enabled on 2026-10-29. Old-format prepared videos are retired from
the backlog without deleting their files or history. The user verified Fish's
usage distinction and accepted narrated Shorts use. See DATABASE.md for the
nonoverlap ledger and crash/retry behavior.
