"""
Stage 1 of experience grading: the App Dossier (Python only; nothing from the repository is ever executed).
Turns a repository into what a person experiences: what it says it is, libraries, data and endpoints, screens,
shared multi-device use, custom mechanics, setup burden, launch, saving, hostile patterns and on-screen text.
Capped at ~12,000 characters (~3,000 tokens) so a model sees the whole thing.
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

CAP = 12000
CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".kt", ".java", ".gd", ".cs", ".go", ".rs", ".swift", ".vue", ".svelte", ".html", ".lua")
SKIP = re.compile(r"(^|/)(node_modules|vendor|third_party|dist|build|\.git|venv|\.venv|__pycache__|site-packages|static/vendor|libs?/)(/|$)|\.min\.(js|css)$|package-lock\.json$")
TEST = re.compile(r"(^|/)(tests?|__tests__|spec|androidTest|testing)(/|$)|(_test|\.test|\.spec|Test)\.\w+$|(^|/)test_")
GENERIC_IDS = set("""data value values index item items result results response request error errors event events state props
self this args kwargs key keys name names text title type types list map dict obj object config options settings params param
path file files line lines count total size len length width height x y i j k n temp tmp val res req ctx context app main init
setup start stop run update render draw handle callback cb fn func function method model view controller component element node
child children parent root id ids url uri str string num number int float bool flag flags status message msg info debug log
logger output input buffer stream client server db conn cursor query row rows col cols table field fields default defaults""".split())
# Hostile patterns need code-level evidence: an ads, payment or sign-in library (in the dependencies or an import) or a
# code name such as showPaywall. Words in on-screen, story or asset text never count (a story chapter called "The
# Software Paywall" or a character who is a store clerk is not a paywall or a sign-in service). Energy/wait timers are
# not checked: games use stamina and timers legitimately, and a pattern cannot tell them from pay-to-skip timers.
HOSTILE = {
    "ads (an advertising library)": r"play-services-ads|google-mobile-ads|com\.google\.android\.gms\.ads|\bAdMob\b|adsbygoogle\.js|"
                                     r"\bUnityAds\b|unity\.ads|com\.applovin|\bAppLovin\w*|com\.ironsource|chartboost|vungle|mopub|"
                                     r"\b(Interstitial|Rewarded)Ad\b",
    "payments or a paywall": r"@stripe/|loadStripe\(|^\s*import stripe\b|[\"']stripe[\"']\s*:|stripe\.(checkout|paymentIntents|subscriptions)\.|"
                             r"@paypal/|paypal-js|PayPalButtons|com\.android\.billingclient|\bBillingClient\b|purchases_flutter|"
                             r"react-native-purchases|\bRevenueCat\b|\bin_app_purchase\b|\bSKPaymentQueue\b|"
                             r"\b(show|open|present)Paywall\b|\bPaywall(Screen|View|Dialog|Modal)\b",
    "a required sign-in service": r"@clerk/|\bClerkProvider\b|\bSignedIn\b.{0,40}\bSignedOut\b|firebase/auth|firebase-auth|"
                                  r"com\.google\.firebase:firebase-auth|@auth0/|auth0-|next-auth|\bsupabase\.auth\.|"
                                  r"@login_required\b|\bProtectedRoute\b|\bRequireAuth\b",
    "a review prompt": r"\bReviewManagerFactory\b|\brequestReviewFlow\b|\bSKStoreReviewController\b|\bInAppReview\b",
}
CONTENT_FILE = re.compile(r"(^|/)(assets?|res/raw|story|stories|dialogues?|lore|locales?|i18n|l10n|translations?|content|levels?|"
                          r"chapters?|scripts?/data|data)(/|$)|\.(txt|md|csv|tsv|po|pot|srt|vtt|lrc)$", re.I)
MANIFEST_FILE = re.compile(r"(^|/)(package\.json|requirements[^/]*\.txt|pyproject\.toml|Pipfile|build\.gradle(\.kts)?|"
                           r"libs\.versions\.toml|Podfile|Package\.swift|pubspec\.yaml|Cargo\.toml|go\.mod|composer\.json|Gemfile)$")
SAVE = [("localStorage", r"localStorage\."), ("sessionStorage", r"sessionStorage\."), ("IndexedDB", r"indexedDB|idb\.|Dexie"),
        ("SQLite", r"sqlite3|SQLite|\.db['\"]|Room\.databaseBuilder|@Entity|better-sqlite3"),
        ("JSON/file save", r"json\.dump\(|JSON\.stringify\(.{0,60}(writeFile|save)|writeFileSync|write_text\(|open\([^)]*['\"]w"),
        ("SharedPreferences/DataStore", r"SharedPreferences|getSharedPreferences|DataStore|preferencesDataStore"),
        ("pickle/shelve", r"pickle\.dump|shelve\.open"),
        ("Android/Kotlin file save", r"AtomicFile|openFileOutput|FileOutputStream|filesDir|\.writeText\(|\.writeBytes\("), ("Godot save", r"FileAccess\.open|ConfigFile|user://")]
ENV_KEY = re.compile(r"(?:os\.environ(?:\.get)?\(?\[?|os\.getenv\(|process\.env\.|import\.meta\.env\.|System\.getenv\()\s*['\"]?([A-Z][A-Z0-9_]{2,})")


def files_of(repo: Path) -> dict:
    names = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split("\n")
    out = {}
    for n in names:
        if not n or SKIP.search(n):
            continue
        p = repo / n
        try:
            if p.stat().st_size > 1_500_000:
                continue
            out[n] = p.read_text(errors="ignore")
        except Exception:
            pass
    return out


def clean_md(t: str) -> str:
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                 # images / badges
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)              # links -> text
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    return re.sub(r"[ \t]+", " ", t)


def readme_identity(files: dict):
    rd = next((c for f, c in files.items() if re.fullmatch(r"readme(\.md|\.rst|\.txt)?", f, re.I)), "")
    t = clean_md(rd)
    title = next((l.strip("# ").strip() for l in t.splitlines() if l.strip().startswith("#") and len(l.strip("# ").strip()) > 2), "")
    paras = [re.sub(r"\*\*|__", "", p.strip()).replace("\n", " ") for p in re.split(r"\n\s*\n", t)
             if len(p.strip()) > 60 and not re.match(r"(#|\||- |\* |>|\d+\.)", p.strip())]
    quick = len(re.findall(r"```(?:bash|sh|shell|console|powershell|cmd)?\n", rd))
    return title, (paras[0][:500] if paras else ""), quick, rd


def collect_strings(path: str, c: str) -> list:
    out = []
    # developer-only text is not on-screen text: drop comments and docstrings first
    if path.endswith(".py"):
        c = re.sub(r'(?s)("""|\'\'\').*?\1', " ", c)
        c = re.sub(r"(?m)^\s*#.*$", " ", c)
    elif path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".kt", ".java", ".cs", ".go", ".rs", ".swift", ".gd")):
        c = re.sub(r"(?s)/\*.*?\*/", " ", c)
        c = re.sub(r"(?m)^\s*//.*$", " ", c)
    if path.endswith((".html", ".vue", ".svelte", ".jsx", ".tsx")):
        out += [s for s in re.findall(r">\s*([^<>{}\n]{6,160}?)\s*<", c)]
        out += re.findall(r"(?:placeholder|title|aria-label|alt)=[\"']([^\"']{6,120})[\"']", c)
    if path.endswith(".xml") and "strings" in path:
        out += re.findall(r"<string[^>]*>([^<]{4,200})</string>", c)
    for q in re.findall(r"\"((?:[^\"\\\n]|\\.){8,200})\"|'((?:[^'\\\n]|\\.){8,200})'|`([^`$\n]{8,200})`", c):
        s = next(x for x in q if x)
        out.append(s)
    keep = []
    for s in out:
        s = re.sub(r"\s+", " ", s).strip()
        if len(s.split()) < 2 or not re.search(r"[A-Za-z]{3}", s):
            continue
        if re.search(r"[{}<>;=]|\\n|%[sd]|\{\d|https?://|/\w+/|\w+\.\w{2,4}$|^[\w\-]+(\.[\w\-]+)+$|SELECT |INSERT |CREATE |FROM \w|\bimport\b|\bdef\b|\bclass\b|className|px\b|rgba?\(|#[0-9a-f]{3,6}\b", s, re.I):
            continue
        if re.search(r"[()\[\]]\s*$|^\s*[)\]]|\w\(|\)\s*(or|and)\b|=>|::|\$\w", s):
            continue
        if re.fullmatch(r"[\w\-\s:,./]+", s) and (s.count("_") > 1 or s.count("-") > 2):
            continue
        keep.append(s)
    return keep


def screens_of(files: dict) -> list:
    sc = []
    for f, c in files.items():
        if f.endswith(".html") and not f.startswith(("node_modules",)):
            sc.append(f"page {f}")
        for m in re.finditer(r"@(?:app|router|bp|api|\w+)\.(?:get|route|post)\(\s*['\"]([^'\"]+)['\"]", c):
            if not m.group(1).startswith("/api"):
                sc.append(f"route {m.group(1)}")
        if re.search(r"(^|/)app/(.*/)?page\.(tsx|jsx|js)$", f):
            sc.append("page /" + re.sub(r"(^|/)?app/?|/?page\.\w+$", "", f).strip("/"))
        sc += [f"screen {m}" for m in re.findall(r"@Composable\s+fun\s+(\w+(?:Screen|Page|Dialog|View))\s*\(", c)]
        sc += [f"activity {m}" for m in re.findall(r"class\s+(\w+Activity)\s*[:(]", c)]
        sc += [f"component {m}" for m in re.findall(r"(?:function|const)\s+([A-Z]\w*(?:Screen|Page|View|Modal|Dialog|Menu|Panel))\b", c)]
        sc += [f"game state {m}" for m in re.findall(r"\b(?:STATE|SCENE|SCREEN)_([A-Z][A-Z_]+)\b", c)
               if not re.search(r"TIMER|INTENSITY|SHAKE|WIDTH|HEIGHT|SIZE|SCALE|DURATION|COLOR|SPEED", m)]
        sc += [f"window {m}" for m in re.findall(r"class\s+(\w+(?:Window|Frame|Dialog))\s*[\(:]", c)]
    return list(dict.fromkeys(sc))


def mechanics_of(files: dict) -> list:
    ids = Counter()
    for f, c in files.items():
        if not f.endswith(CODE) or TEST.search(f):
            continue
        for m in re.findall(r"\b(?:def|fun|function|func|void)\s+([a-zA-Z_]\w{5,})|\b(?:const|let|var|val)\s+([a-zA-Z_]\w{5,})\s*=|\bself\.([a-z_]\w{5,})\s*=|\bon([A-Z]\w{4,})\s*[=(]", c):
            name = next(x for x in m if x)
            parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name.replace("_", " "))
            if re.search(r"(Btn|Button|El|Elem|Element|Sel|Select|Container|Div|Input|Label|Span|Wrapper|Ref|Id|Icon|Img|Canvas|Ctx|Bar|Text)$", name):
                continue
            if len(parts) < 2 or name.lower() in GENERIC_IDS or all(p.lower() in GENERIC_IDS for p in parts):
                continue
            if re.match(r"(get|set|is|has|test|load|save|init|create|update|delete|handle|render|build|parse|read|write|to|from|on)[A-Z_]", name) and len(parts) < 3:
                continue
            ids[name] += 1
    return [n for n, _ in ids.most_common(60)]


def libraries_of(files: dict) -> list:
    libs = []
    pj = files.get("package.json")
    if pj:
        try:
            d = json.loads(pj)
            libs += list((d.get("dependencies") or {}).keys())
        except Exception:
            pass
    for f, c in files.items():
        if re.search(r"(^|/)requirements[^/]*\.txt$", f) and len(re.findall(r"==", c)) < 25:   # skip pip-freeze dumps
            libs += [re.split(r"[<>=~!\[; ]", l.strip())[0] for l in c.splitlines() if l.strip() and not l.startswith(("#", "-"))]
        if f.endswith("pyproject.toml"):
            libs += re.findall(r"^\s*\"([A-Za-z][\w\-.]+)[<>=~\[ \"]", c, re.M)
        if f.endswith((".gradle", ".gradle.kts")):
            libs += re.findall(r"implementation\s*\(?\s*[\"']([\w.\-]+:[\w.\-]+)", c)
            libs += [m.replace("libs.", "") for m in re.findall(r"implementation\s*\(\s*(libs\.[\w.]+)", c)]
    py_imports = Counter()
    for f, c in files.items():
        if f.endswith(".py"):
            for m in re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_]\w*)", c, re.M):
                py_imports[m] += 1
    local = {Path(f).stem for f in files} | {f.split("/")[0] for f in files}
    stdlib = set(sys.stdlib_module_names)
    libs = [m for m, _ in py_imports.most_common() if m not in stdlib and m not in local] + libs
    return list(dict.fromkeys(l for l in libs if l))[:40]


def journey_of(files: dict, readme: str, quick_blocks: int) -> dict:
    launch = [f for f in files if re.search(r"(^|/)(start|run|launch|install|setup)\.(sh|bat|cmd|ps1|command)$|\.iss$|PKGBUILD$|AppImage|\.desktop$|(^|/)Dockerfile$|docker-compose|(^|/)Makefile$|\.spec$|vercel\.json$|netlify\.toml$|(^|/)index\.html$|electron-builder|tauri\.conf", f)]
    pj = files.get("package.json")
    scripts = []
    if pj:
        try:
            scripts = list((json.loads(pj).get("scripts") or {}).keys())
        except Exception:
            pass
    apk = [f for f in files if re.search(r"(^|/)app/build\.gradle(\.kts)?$", f)]
    env_keys = sorted({m for f, c in files.items() if f.endswith(CODE) and not TEST.search(f) for m in ENV_KEY.findall(c)})
    env_files = [f for f in files if re.search(r"\.env(\.example|\.sample|\.template)?$|config\.example|example\.(json|toml|ya?ml)$", f)]
    api_key = sorted({k for k in env_keys if re.search(r"KEY|TOKEN|SECRET", k)} |
                     {m for c in files.values() for m in re.findall(r"\b([A-Z_]*(?:API_KEY|APIKEY|ACCESS_TOKEN))\b", c)})
    readme_cmds = re.findall(r"^\s*(?:\$ )?((?:pip|npm|pnpm|yarn|git clone|python3?|cd|make|cargo|go run|docker|chmod|\./)\S*[^\n]{0,60})", readme, re.M)
    saves = {}
    for label, rx in SAVE:
        hits = sorted({f for f, c in files.items() if f.endswith(CODE) and not TEST.search(f) and re.search(rx, c)})
        if hits:
            saves[label] = hits[:5]
    named = sorted(f for f in files if re.search(r"(save|persist|storage|repository|dao)\w*\.\w+$", f, re.I) and f.endswith(CODE) and not TEST.search(f))
    if named:
        saves["files named for saving"] = named[:5]
    autosave = sorted({f for f, c in files.items() if f.endswith(CODE) and re.search(r"auto_?save|autosave|save_on|onchange.{0,40}save|useEffect\([^)]{0,200}localStorage", c, re.I | re.S)})
    modals = sum(len(re.findall(r"\b(?:Modal|Dialog|AlertDialog|Popup|Toplevel|messagebox|BottomSheet)\b", c)) for f, c in files.items() if f.endswith(CODE))
    depth = max([r.count("/") for r in re.findall(r"['\"](/[a-z0-9_\-/{}:<>]+)['\"]", " ".join(c for f, c in files.items() if f.endswith(CODE)))] or [0])
    settings = sorted({f for f in files if re.search(r"setting|preference|option|config", f, re.I) and f.endswith(CODE)})[:6]
    evidence_files = {f: c for f, c in files.items()
                      if MANIFEST_FILE.search(f) or (f.endswith(CODE) and not TEST.search(f) and not CONTENT_FILE.search(f))}
    hostile = {}
    for name, rx in HOSTILE.items():
        where = sorted({f for f, c in evidence_files.items() if re.search(rx, c, re.M)})
        if where:
            hostile[name] = where[:3]
    return {"launch_files": launch[:12], "package_scripts": scripts[:10], "android_app": bool(apk), "env_keys": env_keys[:15],
            "env_or_example_config_files": env_files[:6], "needs_api_key": api_key[:8], "readme_install_commands": readme_cmds[:8],
            "readme_command_blocks": quick_blocks, "save_mechanisms": saves, "autosave_hints": autosave[:5],
            "modal_dialog_mentions": modals, "max_route_depth": depth, "settings_files": settings,
            "hostile_patterns": {k: v for k, v in hostile.items() if v}}


JARGON = re.compile(r"\b(port|ip|dns|api|token|ssl|tls|ssid|wpa\d?|subdomain|domain|tunnel|cloudflare|tailscale|duckdns|ngrok|"
                    r"bore|proxy|subnet|hostname|localhost|alsa|pulseaudio|pipewire|jack|wasapi|asio|sink|latency|buffer|codec|"
                    r"sample rate|bitrate|hz|khz|lufs|r128|dsp|monitoring|hdmi|path|directory|env|oauth|webhook|"
                    r"json|yaml|regex|cli|daemon|gpu|cuda|vram|ffmpeg|binary)\b", re.I)
SETUP_FILE = re.compile(r"setup|onboard|wizard|first.?run|welcome|get.?started|initial", re.I)
INPUT_RX = (r"<(?:input|select|textarea)\b(?![^>]*type=[\"'](?:hidden|submit|button)[\"'])|\b(?:TextField|OutlinedTextField|Switch|Slider|"
            r"Checkbox|DropdownMenu|ExposedDropdownMenuBox)\s*\(|\b(?:Entry|Combobox|Checkbutton|Spinbox|Scale|QLineEdit|QComboBox|"
            r"QCheckBox|QSpinBox)\s*\(")


def setup_burden(files: dict) -> dict:
    """How much a person must fill in or understand before first use (Python counts only)."""
    def is_screen(f, c):
        if f.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte")):
            return True
        if f.endswith((".kt", ".java")):
            return bool(re.search(r"@Composable|Activity|Fragment", c))
        if f.endswith(".py"):
            return bool(re.search(r"tkinter|Tk\(|QWidget|QDialog|QMainWindow|pygame|curses", c)) and "setuptools" not in c
        return False
    setup = {f: c for f, c in files.items() if SETUP_FILE.search(f.rsplit("/", 1)[-1]) and f.endswith(CODE)
             and not TEST.search(f) and is_screen(f, c)}
    inputs = sum(len(re.findall(INPUT_RX, c)) for c in setup.values())
    required = sum(len(re.findall(r"\brequired\b", c)) for f, c in setup.items() if f.endswith((".html", ".jsx", ".tsx", ".vue")))
    labels = []
    for c in setup.values():
        labels += [re.sub(r"\s+", " ", l).strip() for l in re.findall(r"<label[^>]*>\s*([^<]{3,90})", c)]
        labels += re.findall(r"(?:label|Text)\s*=?\s*\(?\s*[\"']([^\"']{3,80})[\"']\s*\)?", c)
    labels = list(dict.fromkeys(l for l in labels if re.search(r"[A-Za-z]{3}", l)))
    jargon = [l for l in labels if JARGON.search(l)]
    gates = []
    for f, c in files.items():
        if not f.endswith(CODE) or TEST.search(f):
            continue
        for m in re.finditer(r"if\s+not\s+\w*(?:configured|setup_complete|onboarded|is_setup|has_config)\w*\s*\(?\)?\s*:?[^\n]{0,80}\n?[^\n]{0,120}(?:setup|onboard|wizard)", c, re.I):
            gates.append(f)
            break
        if re.search(r"(?:redirect|navigate|router\.push|startActivity)\s*\([^)]{0,80}(?:setup|onboard|wizard)", c, re.I) and f not in gates:
            gates.append(f)
    return {"setup_files": sorted(setup)[:6], "setup_inputs": inputs, "required_fields": required, "setup_labels": labels[:30],
            "technical_labels": jargon[:20], "technical_share": round(len(jargon) / len(labels), 2) if labels else 0.0,
            "setup_forced_before_use": sorted(set(gates))[:5]}


def multi_device(files: dict, readme: str) -> dict:
    """Views served over the network for other devices, QR joining, and live sync between them (Python facts)."""
    code = {f: c for f, c in files.items() if f.endswith(CODE) and not TEST.search(f)}
    views = []
    for c in code.values():
        views += [m for m in re.findall(r"@(?:app|router|\w+)\.(?:get|route)\(\s*['\"](/[a-z][\w\-]*)/?['\"]", c)
                  if not re.match(r"/(api|static|stream|qr|auth|favicon|health|legal)", m)]
    views = list(dict.fromkeys(views))
    allc = "\n".join(code.values())
    live = sorted({name for name, rx in (("WebSockets", r"WebSocket|@\w+\.websocket|websockets\.|ws://|wss://"),
                                         ("Socket.IO", r"socket\.io|socketio|\bio\(\)"), ("server push (SSE)", r"EventSource|text/event-stream"))
                   if re.search(rx, allc)})
    qr = bool(re.search(r"\bqrcode\b|QRCode|qr_code|/qr/|generateQR|toDataURL\(", allc))
    lan = bool(re.search(r"0\.0\.0\.0|get_lan_ip|lan_address|local_ip|gethostbyname|hotspot", allc, re.I))
    rd = "\n".join(l for l in clean_md(readme).splitlines()
                   if l.strip() and not re.match(r"\s*(#|---|\||!|\[)", l) and ".svg" not in l and "%20" not in l)
    rd = re.sub(r"^\s*>\s*", "", rd, flags=re.M).replace("**", "")
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", rd) if re.search(r"synchroni[sz]|real[- ]time|websocket|any device|"
                 r"every (phone|device)|multiple (devices|screens|phones)|simultaneous|at the same time|second screen|their (own )?phones?", x, re.I)]
    return {"network_views": views[:10], "live_sync": live, "qr_join": qr, "lan_server": lan,
            "readme_lines": [re.sub(r"\s+", " ", x)[:220] for x in sentences[:3]]}


UI_CODE = (".html", ".jsx", ".tsx", ".vue", ".svelte", ".js", ".ts", ".css", ".scss", ".kt", ".java", ".swift", ".dart", ".py", ".gd", ".xml")


def ui_facts(files: dict, strings: list) -> dict:
    """What the screens do for the person using them (Python counts only)."""
    ui = {f: c for f, c in files.items() if f.endswith(UI_CODE) and not TEST.search(f)}
    allc = "\n".join(ui.values())

    def count(rx, flags=re.I):
        return len(re.findall(rx, allc, flags))

    styles = "\n".join(c for f, c in ui.items() if f.endswith((".css", ".scss", ".html", ".vue", ".svelte", ".jsx", ".tsx")))
    hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", styles))
    jargon = [s for s in strings[:300] if JARGON.search(s)]
    return {
        "loading_indicators": count(r"\b(spinner|loading|skeleton|progress(bar|indicator)?|CircularProgressIndicator|LinearProgressIndicator|please wait)\b"),
        "empty_states": count(r"\b(no \w+ yet|nothing (here|to show|found)|empty (state|list|queue|library)|get started by|isEmpty\(\)\s*\)?\s*\{?\s*(Text|<))"),
        "error_messages": count(r"(toast\.error|showError|messagebox\.showerror|Snackbar|AlertDialog|alert\(|role=[\"']alert|errorMessage|setError\(|QMessageBox\.(critical|warning))"),
        "success_messages": count(r"(toast\.success|showSuccess|messagebox\.showinfo|\b(saved|added|done|success(fully)?|complete(d)?)!|Snackbar)"),
        "adapts_to_screen": count(r"@media|<meta[^>]+viewport|WindowSizeClass|BoxWithConstraints|layout-land|sm:|md:|lg:|flex-wrap|minmax\(|clamp\("),
        "accessibility_labels": count(r"aria-label|aria-labelledby|\balt=[\"'][^\"']+|contentDescription\s*=|accessibilityLabel|role=[\"']"),
        "theme_variables": count(r"--[a-z][\w-]*\s*:|MaterialTheme|ThemeData|colorScheme|@color/|theme\.(colors|palette)"),
        "distinct_hard_coded_colors": len(hexes),
        "technical_onscreen_share": round(len(jargon) / max(1, min(len(strings), 300)), 2),
        "technical_onscreen_examples": jargon[:6],
    }


def build(repo: Path) -> dict:
    files = files_of(repo)
    title, blurb, quick, readme = readme_identity(files)
    code = {f: c for f, c in files.items() if (f.endswith(CODE) or (f.endswith(".xml") and "strings" in f)) and not TEST.search(f)}
    windows = []
    for c in code.values():
        windows += re.findall(r"set_caption\(\s*['\"]([^'\"]+)", c) + re.findall(r"<title>([^<]{2,80})</title>", c)
        windows += re.findall(r"\.title\(\s*['\"]([^'\"]{3,80})", c) + re.findall(r"setTitle\(\s*['\"]([^'\"]{3,80})", c)
        windows += re.findall(r"(?:title|description)\s*[:=]\s*['\"]([^'\"]{6,140})['\"]", c)[:3]
    meta = {}
    if "package.json" in files:
        try:
            d = json.loads(files["package.json"])
            meta = {k: d[k] for k in ("name", "description") if d.get(k)}
        except Exception:
            pass
    strings = Counter()
    for f, c in code.items():
        for s in collect_strings(f, c):
            strings[s] += 1
    ranked = [s for s, _ in sorted(strings.items(), key=lambda kv: (-min(kv[1], 3), -len(kv[0])))]
    data_models = []
    for f, c in code.items():
        data_models += re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+[`\"]?(\w+)", c, re.I)
        data_models += re.findall(r"@Entity[^\n]*\n\s*(?:data\s+)?class\s+(\w+)", c)
        data_models += re.findall(r"class\s+(\w+)\((?:\w+\.)?(?:Model|Base|BaseModel|db\.Model)\)", c)
    api = []
    for f, c in code.items():
        api += [f"{m[0].upper()} {m[1]}" for m in re.findall(r"@\w+\.(get|post|put|delete|patch)\(\s*['\"](/api[^'\"]*)", c)]
        if re.search(r"(^|/)app/api/.+/route\.(ts|js)$", f):
            api.append("API /" + re.sub(r"^.*?app/|/route\.\w+$", "", f))
    data_models = [m for m in data_models if m.lower() not in ("if", "not", "exists", "table")
                   and not re.search(r"(Request|Response|Payload|Action|Params|Schema|Form)$", m)]
    return {"repo": repo.name, "readme_title": title, "readme_blurb": blurb, "window_titles": list(dict.fromkeys(windows))[:8],
            "package_meta": meta, "libraries": libraries_of(files), "data_models": list(dict.fromkeys(data_models))[:20],
            "api_endpoints": list(dict.fromkeys(api))[:20], "screens": screens_of(code)[:40], "mechanics": mechanics_of(code),
            "strings": ranked, "journey": journey_of(files, readme, quick), "setup": setup_burden(files),
            "ui": ui_facts(files, ranked),
            "multi_device": multi_device(files, readme),
            "size": {"files": len(files), "code_files": len(code), "lines": sum(c.count("\n") for c in code.values())}}


def render(d: dict) -> str:
    j = d["journey"]
    head = [f"# App Dossier: {d['repo']}", "",
            "## 1. What it says it is (README and titles; the owner's own words)",
            f"- README title: {d['readme_title'] or '(none)'}",
            f"- README description: {d['readme_blurb'] or '(none)'}",
            f"- Window/page titles and descriptions: {'; '.join(d['window_titles']) or '(none found)'}",
            f"- Package name/description: {json.dumps(d['package_meta']) if d['package_meta'] else '(none)'}",
            f"- Size: {d['size']['code_files']} code files, about {d['size']['lines']} lines", "",
            "## 2. What it actually does (from the code)",
            f"- External libraries: {', '.join(d['libraries']) or '(none found)'}",
            f"- Data it stores (tables/models): {', '.join(d['data_models']) or '(none found)'}",
            f"- API endpoints: {', '.join(d['api_endpoints']) or '(none found)'}", "",
            "## 3. Screens and views",
            f"- {', '.join(d['screens']) or '(none found)'}", "",
            "## 4. Custom mechanics (names of the program's own state and actions)",
            f"- {', '.join(d['mechanics']) or '(none found)'}", "",
            "## 5. User journey facts",
            f"- Launch/packaging files: {', '.join(j['launch_files']) or '(none)'}",
            f"- package.json scripts: {', '.join(j['package_scripts']) or '(none)'}; Android app module: {'yes' if j['android_app'] else 'no'}",
            f"- Install commands shown in the README: {'; '.join(j['readme_install_commands']) or '(none)'} ({j['readme_command_blocks']} command blocks)",
            f"- Environment variables the code reads: {', '.join(j['env_keys']) or '(none)'}",
            f"- Example config / .env files: {', '.join(j['env_or_example_config_files']) or '(none)'}",
            f"- API keys or tokens the code can read (may be optional; check the README): {', '.join(j['needs_api_key']) or '(none found)'}",
            "- Saving: " + ("; ".join(k + " in " + ", ".join(v) for k, v in j["save_mechanisms"].items()) or "no saving found"),
            f"- Auto-save hints: {', '.join(j['autosave_hints']) or '(none)'}",
            f"- Dialog/modal mentions: {j['modal_dialog_mentions']}; deepest route: {j['max_route_depth']} levels; settings files: {', '.join(j['settings_files']) or '(none)'}",
            f"- Setup burden: setup screens {', '.join(d['setup']['setup_files']) or '(none found)'}; {d['setup']['setup_inputs']} input fields "
            f"({d['setup']['required_fields']} marked required); {round(d['setup']['technical_share'] * 100)}% of setup labels use technical terms"
            f"{(': ' + '; '.join(d['setup']['technical_labels'][:12])) if d['setup']['technical_labels'] else ''}; setup forced before first use: "
            f"{('yes (' + ', '.join(d['setup']['setup_forced_before_use']) + ')') if d['setup']['setup_forced_before_use'] else 'no'}",
            f"- Ads, payments, required sign-in or review prompts found in the code (library or code name; never story text): "
            + ("; ".join(k + " (in " + ", ".join(v) + ")" for k, v in j["hostile_patterns"].items()) or "none found"), "",
            "## 5b. Screen and feedback facts (Python counts)",
            f"- Loading indicators: {d['ui']['loading_indicators']}; empty-state messages: {d['ui']['empty_states']}; error messages shown "
            f"to the user: {d['ui']['error_messages']}; success or confirmation messages: {d['ui']['success_messages']}",
            f"- Layout adapts to screen size (media queries, responsive layouts): {d['ui']['adapts_to_screen']} places; accessibility labels: "
            f"{d['ui']['accessibility_labels']}",
            f"- Theme: {d['ui']['theme_variables']} shared theme colors/variables; {d['ui']['distinct_hard_coded_colors']} different hard-coded colors",
            f"- Share of on-screen text using technical terms: {round(d['ui']['technical_onscreen_share'] * 100)}%"
            + (f" (e.g. {'; '.join(d['ui']['technical_onscreen_examples'][:4])})" if d['ui']['technical_onscreen_examples'] else ""),
            *([""] + d["proven_problems"] if d.get("proven_problems") else []),
            "",
            "## 6. On-screen text (what users read: labels, messages, dialogue)"]
    md_ = d["multi_device"]
    if md_["network_views"] and (md_["live_sync"] or md_["qr_join"]):
        head[head.index("## 4. Custom mechanics (names of the program's own state and actions)"):0] = [
            "## 3b. Shared, multi-device use",
            f"- Separate views served over the network, which other devices (phones, TVs, other computers) can open at the same time: {', '.join(md_['network_views'])}",
            f"- Live sync between devices: {', '.join(md_['live_sync']) or 'none found'}; join by QR code: {'yes' if md_['qr_join'] else 'no'}; "
            f"serves the local network: {'yes' if md_['lan_server'] else 'no'}",
            f"- README says: {' / '.join(md_['readme_lines']) or '(nothing)'}", ""]
    text = "\n".join(head)
    room = CAP - len(text) - 50
    lines = []
    for s in d["strings"]:
        line = f"- {s}"
        if room - len(line) - 1 < 0:
            break
        lines.append(line)
        room -= len(line) + 1
    return text + "\n" + "\n".join(lines) + "\n"


