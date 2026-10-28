"""Package source, handoff, and selected comparison media without local secrets."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
MEDIA = [
    "storage/audio/fish_093cbb6143f5270b.mp3",
    "storage/audio/fish_093cbb6143f5270b.json",
    "storage/audio/fish_093cbb6143f5270b.events.json",
    "storage/audio/elevenlabs_8b96ba29bc458d05.mp3",
    "storage/audio/elevenlabs_8b96ba29bc458d05.json",
    "storage/output/preview_fish_word_highlight.mp4",
    "storage/output/preview_elevenlabs_word_highlight.mp4",
]


def main():
    files = set()
    for pattern in ("*.py", "*.md", "*.ps1", "*.example.json"):
        files.update(ROOT.glob(pattern))
    files.update(ROOT / name for name in (".gitignore", "requirements.txt", "START_HERE.txt"))
    files.update(ROOT / name for name in MEDIA)
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("Required transfer files missing: " + ", ".join(missing))

    # Check for known local API keys in selected source/docs/media without logging keys.
    secrets = []
    for name in ("fish.local.json", "elevenlabs.local.json", "opencode.local.json"):
        path = ROOT / name
        if path.exists():
            key = json.loads(path.read_text()).get("api_key", "")
            if isinstance(key, str) and len(key) >= 12:
                secrets.append(key.encode())
    for path in files:
        if any(secret in path.read_bytes() for secret in secrets):
            raise RuntimeError("Local API key detected in selected file: " + str(path.relative_to(ROOT)))

    output = ROOT / "deployment"
    output.mkdir(exist_ok=True)
    archive = output / "shorts-automation-windows.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        for path in sorted(files):
            entry = "shorts-automation/" + path.relative_to(ROOT).as_posix()
            stream.write(path, entry)
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise RuntimeError("Archive integrity check failed.")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Created {archive}")
    print(f"{len(files)} files; {archive.stat().st_size:,} bytes")
    print("Local credentials, environments, and gameplay downloads excluded.")


if __name__ == "__main__":
    main()
