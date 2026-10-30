"""Package source, handoff, and selected comparison media without local secrets."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTRA_FILES = (
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "START_HERE.txt",
    "secrets/production.json",
    "secrets/opencode.local.example.json",
)
SOURCE_TREES = {
    "shorts_automation": {".py", ".ps1"},
    "scripts": {".ps1"},
    "docs": {".md"},
    "prompts": {".md"},
    "tests": {".py"},
    "legacy": {".py"},
}
MEDIA = [
    "storage/audio/fish_093cbb6143f5270b.mp3",
    "storage/audio/fish_093cbb6143f5270b.json",
    "storage/audio/fish_093cbb6143f5270b.events.json",
    "storage/audio/elevenlabs_8b96ba29bc458d05.mp3",
    "storage/audio/elevenlabs_8b96ba29bc458d05.json",
    "storage/output/preview_fish_word_highlight.mp4",
    "storage/output/preview_elevenlabs_word_highlight.mp4",
]


def collect_files(root=ROOT):
    """Select only approved source trees and the explicit media whitelist."""
    root = Path(root).resolve()
    files = set()
    for pattern in ("*.py", "*.md", "*.ps1"):
        files.update(root.glob(pattern))
    for folder, extensions in SOURCE_TREES.items():
        files.update(
            path
            for path in (root / folder).rglob("*")
            if path.is_file() and path.suffix in extensions and "__pycache__" not in path.parts
        )
    files.update(root / name for name in EXTRA_FILES)
    files.update(root / name for name in MEDIA)
    missing = [str(path.relative_to(root)) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("Required transfer files missing: " + ", ".join(missing))
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise RuntimeError(
                "Transfer source escapes the project or is a symlink: "
                + str(path.relative_to(root))
            )
    return files


def check_secrets(root, files):
    """Scan selected bytes without logging credential values, including OAuth."""
    secret_fields = {"api_key", "token", "access_token", "refresh_token", "client_secret"}
    secrets = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in secret_fields and isinstance(item, str) and len(item) >= 12:
                    secrets.add(item.encode())
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    credential_paths = set(root.glob("*.local.json"))
    credential_paths.update(root / name for name in ("client_secret.json", "token.json"))
    credential_paths.update((root / "secrets").glob("*.json"))
    for path in credential_paths:
        if path.exists():
            visit(json.loads(path.read_text(encoding="utf-8-sig")))
    for path in files:
        if any(secret in path.read_bytes() for secret in secrets):
            raise RuntimeError(
                "Local credential detected in selected file: " + str(path.relative_to(root))
            )


def build_package(root=ROOT):
    root = Path(root).resolve()
    files = collect_files(root)
    check_secrets(root, files)
    output = root / "deployment"
    output.mkdir(exist_ok=True)
    archive = output / "shorts-automation-windows.zip"
    staged = output / "shorts-automation-windows.partial.zip"
    try:
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(files):
                entry = "shorts-automation/" + path.relative_to(root).as_posix()
                stream.write(path, entry)
        with zipfile.ZipFile(staged) as stream:
            if stream.testzip() is not None:
                raise RuntimeError("Archive integrity check failed.")
        staged.replace(archive)
    finally:
        staged.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, len(files)


def main():
    archive, count = build_package()
    print(f"Created {archive}")
    print(f"{count} files; {archive.stat().st_size:,} bytes")
    print("Local credentials, environments, and gameplay downloads excluded.")


if __name__ == "__main__":
    main()
