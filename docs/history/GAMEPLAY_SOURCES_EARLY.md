# Background footage sourcing

## Automatic source path (implemented 2026-10-28)

`gameplay_fetcher.py` now searches Wikimedia Commons using its public API;
it no longer runs unrestricted YouTube searches. Default query is
`Labyrinth Minetest`. Change it using `--gameplay` in pipeline.py or `--query`
in gameplay_fetcher.py. No account, API key, subscription or paid fallback.

Only candidates with an explicit supported license (CC0, CC BY 3.0/4.0,
CC BY-SA 3.0/4.0), creator, source page, and license link are considered.
Downloads must come directly from upload.wikimedia.org, with no redirects.
The limits are 20 search results, three candidate downloads, 100 MiB per download,
120-second download wall budget checked per chunk, and 180-second normalization
timeout per candidate. Source resolution must be at least 640x360.

Sources must be at least 15 seconds and at least one quarter of prepared duration.
Short sources can loop at most four times; looping is recorded. Sources are
normalized to a muted 720p H.264 MP4 covering at least 60 seconds. Final crop and
caption rendering remain 1080x1920. The original download is temporary.

The cache is scoped to the exact search query and checked for matching SHA256,
source metadata and sufficient duration before reuse. Supplying a query no
longer forces a download. Unrelated or untracked MP4s are never fallback sources.
Failures stop clearly; they don't fall back to an arbitrary latest download.

Each clip has a `.source.json` with source URL, creator, license and raw license
metadata, retrieval time, looping/transformation information and output hash.
New downloads also record the original download hash. Each pipeline output
preserves the source in `.metadata.json` and writes `.credits.txt`.

This is local-evaluation sourcing. Metadata cannot establish every underlying
right, guarantee license accuracy or distinguish every menu/trailer automatically.
All clips retain `requires_visual_review: true` and `publication_cleared: false`.
Share-alike sources are identified in metadata; fulfill their conditions before
sharing derivatives. No automatic publishing is authorized.

Verified live: downloaded a 33.191-second cave-maze gameplay clip, listed CC BY-SA
4.0, normalized it to a looped 60-second clip, then reused it with all HTTP blocked.
The full Fish-story pipeline rendered successfully using that automatic cache.
23 tests pass (including seven source validation/cache/failure tests).

Commands:

```powershell
.venv\Scripts\python.exe gameplay_fetcher.py --duration 56.3
.venv\Scripts\python.exe pipeline.py --story-file storage/stories/story_fffedb5e31864563bb9e779e28f6d8b4.json --tts-provider fish
```

This supplies voxel cave gameplay; continuous Minecraft parkour and a broader
visual-quality-ranked catalog are still future improvements.

The workflow includes finding and downloading footage; user-recorded footage is
not required. Download only from a source with an explicit permission/license
record. A search title saying "no copyright" is insufficient by itself.

## First downloaded local test asset

- Work: MineClone2 - Release 0.84 - The Very Nice Release
- Creator: VoxeLibre
- Page: https://commons.wikimedia.org/wiki/File:MineClone2_-_Release_0.84_-_The_Very_Nice_Release.webm
- Listed license option used: CC BY 3.0, https://creativecommons.org/licenses/by/3.0/
- Commons notes that external license review is pending. Keep this provenance
  caveat; do not treat the asset as cleared for unattended publication.
- Downloaded original: `storage/backgrounds/voxelibre_084.webm`.
- Provenance sidecar: `storage/backgrounds/voxelibre_084.source.json`.
- Local derivative: `voxelibre_084_muted.mp4`, 60s from source second 6, audio
  removed to exclude its music. Final video crops to vertical and overlays text.
- This is voxel gameplay feature-showcase footage, not continuous Minecraft parkour.

Suggested attribution if subsequently shared after rights review:
"Gameplay: VoxeLibre, MineClone2 - Release 0.84 - The Very Nice Release,
via Wikimedia Commons, CC BY 3.0. Trimmed, muted, cropped; narration and captions added."
Include the source page and license links above with this attribution.

Vimeo candidate https://vimeo.com/1005854698 explicitly allowed downloads/reuse
in its description, but anonymous download failed because Vimeo required login.
No login cookies or paid account were used.

The manual test asset above remains outside the new validated cache. It is never
silently selected by the automatic source path. No publishing is enabled.
# Creator-download discovery brief (2026-10-28)

Update: the research tool denial is resolved through a public-evidence broker and
isolated AGY ranking session, and a creator-file import adapter is implemented.
The active worker uses creator_downloads. See FOOTAGE_RESEARCH.md for the live
verified source and adapter details; the earlier blocked-test notes below are
historical, not the current state.

The user supplied https://www.youtube.com/watch?v=u7kdVe8q5zs as the visual target:
Minecraft parkour, creator-provided download in the description, suitable for
edited Shorts. `AGY_FOOTAGE_PROMPT.md` is the new research brief. It permits actual
public browsing and asks for real video/download/permission evidence, native
1080p+ fluid parkour, preferably 60fps, and explicit price/access checks. It does
not restrict discovery to Commons or accept dark cave demos as a substitute.

Run `.venv\Scripts\python.exe agy_footage_research.py --count 4` to save an
evidence catalog under storage/reviews. This research command is separate from
the existing Commons download adapter; creator download records require an
import/download adapter before they can feed production automatically. Do not
pass YouTube URLs into the Commons keyword search or claim the catalog alone
has downloaded footage.

The reference description was retrieved with yt-dlp metadata-only: Orbital - No
Copyright Gameplay, 1,852s, 2560x1440 at 60fps, Creative Commons Attribution,
explicit monetized reuse permission with creator credit and no raw no-copyright
reuploads. It links to https://ko-fi.com/s/0a60cae8c9, whose page advertises a
1440p/60fps Google Drive MP4 download. Minimum price/free-direct access was not
verified, and no checkout or purchase was performed.

Live AGY research test returned status SUCCESS but an empty response with
denied_actions: RunCommand. The runner now reports this denial honestly; CLI
permissions were not bypassed and no source catalog was fabricated. The prompt
is usable with AGY once its read-only research tools are available.
