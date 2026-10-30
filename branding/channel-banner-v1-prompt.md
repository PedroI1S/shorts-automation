# Channel banner v1

Created and visually revised with the built-in imagegen tool using `channel-logo-v1.png` as the identity reference. The central emblem fits within the shallow middle band for mobile cropping. The generated master is retained as `channel-banner-v1-source.png`. The final upload file `channel-banner-v1.png` is a 2560 x 1440 PNG exported with FFmpeg Lanczos scaling; the native generated image was 1672 x 941.

## Initial generation prompt

Use case: logo-brand
Asset type: Finished YouTube channel banner, landscape 16:9, exactly 2560 x 1440 pixels.
Primary request: Create a polished atmospheric banner matching the provided existing logo for an English horror-story Shorts channel. Expand its visual world into a restrained, cinematic horizontal composition.
Input images: Image 1 is the existing channel logo. It is the identity reference and supporting compositing input. Preserve its recognizable ivory open book / hooded storyteller silhouette and its two sharp yellow eyes. Do not reinterpret the mark as a skull, animal, or game character.
Scene/backdrop: An expansive near-black background with charcoal drifting fog and very subtle angular shadow shapes suggesting pages disappearing into darkness. Low-contrast ghostly page shapes and subtle yellow light trails spread horizontally from the central emblem, fading away toward the edges. The backdrop has depth and a quiet unsettling atmosphere, not visual clutter.
Subject/composition: The existing logo is reproduced cleanly once at the exact center, deliberately small enough to fit inside a centered 1540 x 420 pixel mobile-safe rectangle on the 2560 x 1440 canvas. Keep the full logo about 360 pixels wide and 300 pixels tall, entirely within that center band. Surround it with generous dark breathing room. All important identity elements must be fully visible in a shallow center strip that is only 29 percent of the overall canvas height. The top and bottom are atmospheric background only; side decoration is secondary and safe to crop.
Style/medium: Premium horror-story channel art. Crisp flat ivory logo against a softly cinematic dark atmosphere, subtle graphic geometry connected to its angular pages. A refined visual identity with a clear focal point, not an esports advertisement.
Color palette: Near-black and charcoal, warm ivory, restrained vivid yellow matching the reference eyes and the channel's caption highlight. No new accent colors.
Text: None. No invented channel name, no lettering, no slogan, no watermark.
Constraints: A single finished landscape banner image, not a mockup or layout board. Edge-to-edge artwork with no borders. Keep the reference emblem proportions and identity intact. No extra faces, no blood, no gore, no Minecraft trademarks or characters, no obvious YouTube icon, no crop guides or safe-area lines. Render at exactly 2560 x 1440 pixels.

## Final composition edit prompt

Use case: precise-object-edit
Asset type: Final 16:9 YouTube channel banner.
Input images: Image 1 is the banner edit target. Image 2 is the logo identity reference.
Primary request: Make exactly one composition adjustment to Image 1: reduce the central ivory hooded-book emblem to 65 percent of its current size, preserving its exact design, and center it precisely both horizontally and vertically. Restore the dark atmospheric background naturally behind the space released by the reduced emblem.
The complete emblem should occupy only about one fifth of the full image height. It must comfortably fit inside the shallow middle 29 percent of the banner height with visible dark margin above and below it. Leave the surrounding flowing pages, charcoal fog, near-black background, and restrained golden-yellow light trails in their existing positions and appearance.
Invariants: Keep the 16:9 landscape composition, horror atmosphere, ivory/black/yellow identity, the two sharp yellow eyes, all surrounding scenery, and all background proportions. No extra logos, no new subjects, no titles, no channel name, no slogans, no guides, no watermark. Preserve crisp logo edges and the exact open-book and hood silhouette from the reference.
Output a single finished banner, ideally 2560 x 1440 pixels.
