from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
SUSPICIOUS_MOJIBAKE_PREFIXES = {
    chr(codepoint)
    for codepoint in (0x0139, 0x00C4, 0x0102, 0x00E2, 0x00C2, 0x00C3, 0x00C5)
}


def suspicious_mojibake_pairs(text: str) -> list[str]:
    return [
        text[index:index + 2]
        for index, char in enumerate(text[:-1])
        if char in SUSPICIOUS_MOJIBAKE_PREFIXES and ord(text[index + 1]) > 0x7F
    ]


def test_release_text_is_utf8_without_bom_or_known_mojibake():
    suffixes = {
        ".py", ".js", ".css", ".html", ".yaml", ".yml", ".sh",
        ".md", ".json", ".txt", ".webmanifest",
    }
    ignored_directories = {"venv", ".venv", "deps", "node_modules", "__pycache__", ".pytest_cache"}
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and not ignored_directories.intersection(path.relative_to(ROOT).parts)
    ]
    if (ROOT / "Dockerfile").exists():
        files.append(ROOT / "Dockerfile")
    # Typowe pierwsze znaki całej klasy sekwencji powstałych po odczytaniu
    # bajtów UTF-8 jako cp1250/cp1252 i ponownym zapisaniu ich jako UTF-8.
    problems: list[str] = []
    for path in sorted(set(files)):
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"BOM: {path.relative_to(ROOT)}")
        text = raw.decode("utf-8")
        for pair in suspicious_mojibake_pairs(text):
            points = " ".join(f"U+{ord(item):04X}" for item in pair)
            problems.append(f"podejrzana sekwencja {points}: {path.relative_to(ROOT)}")
    assert not problems, "\n".join(problems)


def test_mojibake_guard_covers_polish_cp1250_and_cp1252_sequences():
    samples = "ąćęłńóśźż—"
    for encoding in ("cp1250", "cp1252"):
        for character in samples:
            damaged = character.encode("utf-8").decode(encoding)
            assert suspicious_mojibake_pairs(damaged), f"brak wykrycia {character!r} przez {encoding}"


def test_release_version_and_static_cache_are_consistent():
    from app import __version__

    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "static" / "service-worker.js").read_text(encoding="utf-8")

    assert re.fullmatch(r"\d+\.\d+\.\d+-gptsol\d+-v3native\d+(?:\.\d+)?", __version__)
    if (ROOT / "config.yaml").exists():
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        assert config["version"] == __version__
    if (ROOT / "Dockerfile").exists():
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert f'io.hass.version="{__version__}"' in dockerfile
    asset = re.search(r'ASSET_VERSION = "(gptsol-\d+)"', worker)
    cache = re.search(r'CACHE = "plumbox-gptsol-static-v(\d+)"', worker)
    assert asset and cache
    assert asset.group(1) == f"gptsol-{cache.group(1)}"
    assert f"assets/styles.css?v={asset.group(1)}" in index
    assert f"assets/app.js?v={asset.group(1)}" in index
