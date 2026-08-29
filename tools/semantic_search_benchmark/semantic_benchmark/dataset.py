from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import certifi

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PUBLIC_SEARCHES = [
    ("dog", "dog photograph"), ("cat", "cat photograph"), ("car", "car photograph"),
    ("person", "person portrait photograph"), ("food", "food meal photograph"),
    ("laptop", "laptop computer photograph"), ("snow", "snow landscape photograph"),
    ("beach", "beach sea photograph"), ("mountain", "mountain landscape photograph"),
    ("city", "city street photograph"), ("night", "night city photograph"),
    ("office", "office interior photograph"), ("indoor", "indoor room photograph"),
    ("outdoor", "outdoor landscape photograph"), ("dog running", "dog running photograph"),
    ("person walking", "person walking photograph"), ("person cooking", "person cooking photograph"),
    ("car driving", "car driving photograph"), ("animal snow", "animal in snow photograph"),
    ("person laptop", "person using laptop photograph"),
]
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "CapixeSemanticBenchmark/1.0 (local evaluation)"})
    with urllib.request.urlopen(request, timeout=120, context=TLS_CONTEXT) as response, partial.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
    partial.replace(target)


def _plain(metadata: dict, key: str) -> str:
    value = metadata.get(key, {}).get("value", "")
    return " ".join(value.replace("<br>", " ").replace("<p>", " ").replace("</p>", " ").split())


def _commons_records(root: Path, count: int, seed: int) -> list[dict]:
    image_dir = root / "data" / "images"
    api_cache = root / "data" / "downloads" / "commons_api"
    api_cache.mkdir(parents=True, exist_ok=True)
    records, seen = [], set()
    per_search = max(1, (count + len(PUBLIC_SEARCHES) - 1) // len(PUBLIC_SEARCHES))
    searches = list(PUBLIC_SEARCHES)
    random.Random(seed).shuffle(searches)
    for label, search in searches:
        params = urllib.parse.urlencode({
            "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {search}",
            "gsrnamespace": 6, "gsrlimit": min(10, per_search + 4), "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 960, "format": "json", "formatversion": 2,
        })
        cache_file = api_cache / f"{label.replace(' ', '_')}_{per_search}.json"
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            request = urllib.request.Request(f"{COMMONS_API}?{params}", headers={"User-Agent": "CapixeSemanticBenchmark/1.0 (local evaluation; no redistribution)"})
            for attempt in range(5):
                try:
                    payload = json.loads(urllib.request.urlopen(request, timeout=60, context=TLS_CONTEXT).read())
                    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    break
                except urllib.error.HTTPError as error:
                    if error.code != 429 or attempt == 4:
                        raise
                    time.sleep(5 * (attempt + 1))
            time.sleep(1.25)
        added = 0
        for page in payload.get("query", {}).get("pages", []):
            if added >= per_search or len(records) >= count or not page.get("imageinfo"):
                break
            info = page["imageinfo"][0]
            url = info.get("thumburl") or info.get("url")
            if not url or url in seen:
                continue
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            target = image_dir / f"commons_{len(records):03d}{ext}"
            try:
                _download(url, target)
                with Image.open(target) as probe:
                    probe.verify()
            except Exception:
                target.unlink(missing_ok=True)
                continue
            metadata = info.get("extmetadata", {})
            license_name = _plain(metadata, "LicenseShortName") or "Unknown"
            records.append({
                "id": f"commons-{len(records):03d}", "path": str(target.relative_to(root)),
                "source": "Wikimedia Commons", "source_page": info.get("descriptionurl"),
                "license": license_name, "license_url": _plain(metadata, "LicenseUrl"),
                "creator": _plain(metadata, "Artist"), "kind": "photo",
                "level": 3 if " " in label and label not in {"dog", "cat"} else (2 if label in {"snow", "beach", "mountain", "city", "night", "office", "indoor", "outdoor"} else 1),
                "labels": label.split(), "captions": [page.get("title", ""), _plain(metadata, "ImageDescription")],
                "no_text_expected": True,
            })
            seen.add(url)
            added += 1
        if len(records) >= count:
            break
    return records


def _font(size: int):
    candidates = [Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/arial.ttf")]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _synthetic_screen(path: Path, kind: str, variant: int) -> dict:
    themes = [("#10151f", "#e6edf3", "#58a6ff"), ("#f7f8fa", "#17202a", "#6c5ce7")]
    bg, fg, accent = themes[variant % len(themes)]
    image = Image.new("RGB", (960, 600), bg)
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(28), _font(18), _font(14)
    draw.rectangle((0, 0, 960, 52), fill="#252c38" if variant % 2 == 0 else "#e8eaf0")
    draw.text((24, 13), f"Capixe Benchmark — {kind.replace('_', ' ').title()}", fill=fg, font=title_font)
    meta = {"screen_type": kind, "scene": "computer screen", "objects": [], "action": [], "visible_text": [], "expected_concepts": []}
    if kind == "code_editor":
        draw.rectangle((0, 52, 190, 600), fill="#171d27")
        for i, name in enumerate(["src", "search.py", "models.py", "README.md"]):
            draw.text((22 + (15 if i else 0), 82 + i * 30), name, fill="#b6beca", font=body_font)
        code = ["def semantic_search(query):", "    vector = embed(query)", "    return rank(vector)", "", "results = semantic_search(input_text)"]
        for i, line in enumerate(code):
            draw.text((220, 90 + i * 38), line, fill=accent if i in (0, 4) else fg, font=body_font)
        meta.update(objects=["code editor", "sidebar", "source code"], action=["writing code"], expected_concepts=["code", "programming", "editor"])
    elif kind == "terminal":
        for i, line in enumerate(["> capixe analyze ./images", "Scanning 128 images...", "Embedding 87/128", "Ready"]):
            draw.text((42, 100 + i * 48), line, fill="#62d26f" if i in (0, 3) else fg, font=body_font)
        meta.update(objects=["terminal", "command prompt"], action=["running command"], expected_concepts=["terminal", "command line"])
    elif kind == "error_dialog":
        draw.rounded_rectangle((230, 140, 730, 430), 18, fill="#ffffff", outline="#d7dbe2", width=3)
        draw.ellipse((270, 185, 330, 245), fill="#e74c3c")
        draw.text((292, 194), "!", fill="white", font=title_font)
        draw.text((360, 180), "Something went wrong", fill="#20242b", font=title_font)
        draw.text((280, 275), "The request could not be completed.", fill="#505967", font=body_font)
        draw.rounded_rectangle((555, 350, 680, 400), 8, fill="#346beb")
        draw.text((592, 364), "Retry", fill="white", font=body_font)
        meta.update(objects=["error dialog", "warning icon", "retry button"], action=["showing an error"], expected_concepts=["error", "failure", "problem"])
    elif kind == "settings":
        draw.text((45, 92), "Settings", fill=fg, font=title_font)
        for i, label in enumerate(["Appearance", "Notifications", "Search indexing", "Privacy"]):
            y = 160 + i * 82
            draw.text((60, y), label, fill=fg, font=body_font)
            draw.rounded_rectangle((720, y - 5, 790, y + 30), 17, fill=accent if (i + variant) % 2 else "#7b8491")
            draw.ellipse((755 if (i + variant) % 2 else 725, y, 780 if (i + variant) % 2 else 750, y + 25), fill="white")
        meta.update(objects=["settings panel", "toggle switches"], action=["configuring application"], expected_concepts=["settings", "preferences"])
    elif kind in {"product_page", "comparison_page"}:
        if kind == "product_page":
            draw.rectangle((70, 120, 430, 480), fill="#dfe6ee")
            draw.ellipse((155, 170, 345, 360), fill=accent)
            draw.text((500, 145), "Aurora Headphones", fill=fg, font=title_font)
            draw.text((500, 215), "$129", fill=accent, font=title_font)
            draw.rounded_rectangle((500, 300, 750, 365), 12, fill=accent)
            draw.text((570, 320), "Add to cart", fill="white", font=body_font)
            meta.update(objects=["product", "price", "add to cart button"], action=["shopping"], expected_concepts=["product page", "online shopping"])
        else:
            for x, name, price in [(85, "Lite", "$79"), (365, "Plus", "$129"), (645, "Pro", "$189")]:
                draw.rounded_rectangle((x, 115, x + 230, 500), 14, outline="#9da7b5", width=3)
                draw.text((x + 72, 150), name, fill=fg, font=title_font)
                draw.text((x + 78, 215), price, fill=accent, font=title_font)
                for j, feature in enumerate(["Cloud sync", "Fast search", "Export"]):
                    draw.text((x + 35, 300 + j * 43), "✓ " + feature, fill=fg, font=small_font)
            meta.update(objects=["three products", "prices", "feature table"], action=["comparing products", "comparing prices"], expected_concepts=["comparison", "pricing", "products"])
    elif kind == "login_screen":
        draw.rounded_rectangle((300, 105, 660, 520), 18, fill="#ffffff")
        draw.text((420, 145), "Sign in", fill="#20242b", font=title_font)
        for y, label in [(230, "Email"), (315, "Password")]:
            draw.text((345, y - 27), label, fill="#56606c", font=small_font)
            draw.rounded_rectangle((340, y, 620, y + 52), 8, outline="#aab2be", width=2)
        if variant % 2:
            draw.text((345, 378), "Incorrect password. Try again.", fill="#d63031", font=small_font)
        draw.rounded_rectangle((340, 420, 620, 475), 8, fill=accent)
        draw.text((450, 436), "Continue", fill="white", font=body_font)
        concepts = ["login", "authentication"] + (["login failure", "incorrect password"] if variant % 2 else [])
        meta.update(objects=["login form", "password field"], action=["signing in"], expected_concepts=concepts)
    elif kind == "dashboard":
        for x, label, value in [(45, "Images", "12,480"), (350, "Storage", "8.2 GB"), (655, "Tags", "238")]:
            draw.rounded_rectangle((x, 95, x + 260, 230), 12, fill="#252c38" if variant % 2 == 0 else "#ffffff", outline="#737f90")
            draw.text((x + 24, 120), label, fill=fg, font=small_font)
            draw.text((x + 24, 160), value, fill=accent, font=title_font)
        points = [(70, 470), (190, 390), (310, 430), (430, 300), (550, 350), (670, 245), (820, 285)]
        draw.line(points, fill=accent, width=5)
        meta.update(objects=["dashboard", "metric cards", "line chart"], action=["viewing analytics"], expected_concepts=["dashboard", "statistics", "analytics"])
    elif kind == "documentation":
        draw.rectangle((0, 52, 230, 600), fill="#202733")
        for i, label in enumerate(["Introduction", "Install", "Quick start", "API", "Examples"]):
            draw.text((25, 100 + i * 42), label, fill="#c5ccd6", font=body_font)
        draw.text((275, 100), "Semantic Search API", fill=fg, font=title_font)
        for i, line in enumerate(["Create image embeddings once and reuse them.", "Queries are encoded into the same vector space.", "Results are ranked by cosine similarity."]):
            draw.text((275, 175 + i * 48), line, fill=fg, font=small_font)
        meta.update(objects=["documentation", "navigation sidebar", "article"], action=["reading documentation"], expected_concepts=["documentation", "help", "API guide"])
    image.save(path, quality=92)
    meta["visible_text"] = [kind.replace("_", " ")]
    return meta


def prepare_dataset(root: Path, public_count: int, screenshot_count: int, seed: int) -> list[dict]:
    data_dir = root / "data"
    manifest = data_dir / "manifest.json"
    if manifest.exists():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if len(existing) >= 100 and all((root / item["path"]).exists() for item in existing):
            return existing
    image_dir = data_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    records = _commons_records(root, public_count, seed)
    kinds = ["code_editor", "terminal", "error_dialog", "settings", "product_page", "comparison_page", "login_screen", "dashboard", "documentation"]
    for index in range(screenshot_count):
        kind = kinds[index % len(kinds)]
        target = image_dir / f"synthetic_{kind}_{index:03d}.png"
        metadata = _synthetic_screen(target, kind, index)
        records.append({"id": f"synthetic-{index:03d}", "path": str(target.relative_to(root)), "source": "Capixe synthetic UI", "kind": "screenshot", "level": 5 if any(x in metadata["expected_concepts"] for x in ["login failure", "comparison"]) else 4, "labels": metadata["expected_concepts"], "captions": metadata["action"], "metadata": metadata, "no_text_expected": False})
    manifest.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records
