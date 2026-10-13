"""Which files to index, and how to clean them (spec sections 8.1, 8.2, 14.9)."""

from __future__ import annotations

import logging
import posixpath
import re

log = logging.getLogger(__name__)

# --- denylist ---------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".github", "node_modules", "vendor", "dist", "build", "out",
    "target", "coverage", ".next", ".nuxt", ".venv", "venv", "site-packages",
    "__pycache__", ".terraform", ".gradle", ".idea", ".vscode", "generated",
}

SKIP_FILE_SUFFIXES = (
    ".lock", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".jks", ".keystore",
    ".min.js", ".min.css", ".map", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
    ".pb.go", "_pb2.py", ".g.dart", ".freezed.dart", ".generated.ts", ".svgz",
)

SKIP_FILE_NAMES = {
    ".env", ".envrc", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "cargo.lock", "go.sum", "composer.lock", "gemfile.lock",
    "pipfile.lock", "uv.lock", ".secrets", "secrets.yml", "secrets.yaml",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip",
    ".gz", ".bz2", ".xz", ".tar", ".7z", ".jar", ".war", ".class", ".bin",
    ".dat", ".db", ".sqlite", ".sqlite3", ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".psd", ".sketch", ".fig", ".svg",
    ".onnx", ".pt", ".pth", ".h5", ".safetensors", ".bin.gz", ".ipynb_checkpoints",
}

DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".markdown"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs", ".cs",
    ".c", ".h", ".cpp", ".kt", ".swift", ".php", ".sql", ".sh",
}


def should_skip(path: str) -> bool:
    """True when a path must never be indexed, regardless of extension."""
    norm = posixpath.normpath(path).replace("\\", "/")
    parts = norm.split("/")
    lowered = [p.lower() for p in parts]
    if any(p in SKIP_DIRS or p in {d.lower() for d in SKIP_DIRS} for p in lowered[:-1]):
        return True
    name = lowered[-1]
    if name in SKIP_FILE_NAMES:
        return True
    if name.startswith(".env"):
        return True
    if any(name.endswith(sfx) for sfx in SKIP_FILE_SUFFIXES):
        return True
    ext = posixpath.splitext(name)[1]
    return ext in BINARY_EXTENSIONS


def doc_kind(path: str, index_code: bool = False) -> str | None:
    """Classify an indexable file, or None when it is out of scope (spec 8.1).

    Only documentation is indexed by default. Source code requires INDEX_CODE=true.
    """
    if should_skip(path):
        return None
    norm = posixpath.normpath(path).replace("\\", "/")
    name = norm.split("/")[-1]
    upper = name.upper()
    ext = posixpath.splitext(name)[1].lower()

    if upper.startswith("README"):
        return "readme"
    if upper.startswith(("CHANGELOG", "HISTORY", "RELEASES")):
        return "release"
    if upper == "PRODUCT_TRUTHS.MD":
        return "truth"

    if ext in DOC_EXTENSIONS:
        segments = [s.lower() for s in norm.split("/")[:-1]]
        if any(seg.startswith("adr") or seg in ("architecture", "design") for seg in segments):
            return "adr"
        return "doc"

    if index_code and ext in CODE_EXTENSIONS:
        return "code"
    return None


# --- text cleaning ----------------------------------------------------------

_BADGE_RE = re.compile(r"!\[[^\]]*\]\(https?://[^)]*(?:shields\.io|badge)[^)]*\)")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLANK_RUN_RE = re.compile(r"\n{3,}")

# Prompt-injection patterns for untrusted issue/PR comment text (spec 14.9).
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:the\s+)?(?:docs|documents|context|instructions?|passages?)", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\b", re.I),
    re.compile(r"^\s*(?:system|assistant|developer)\s*:", re.I | re.M),
    re.compile(r"<\|(?:im_start|im_end|system|endoftext|eot_id|start_header_id)\|?>"),
    re.compile(r"^\s*#{2,}\s*instructions?\s*:?\s*$", re.I | re.M),
    re.compile(r"(?:new|updated)\s+instructions?\s*:", re.I),
    re.compile(r"reveal\s+(?:your|the)\s+(?:system\s+)?prompt", re.I),
]


def neutralize_instructions(text: str) -> str:
    """Strip instruction-like text from untrusted content.

    Retrieved documents are data, never instructions. Anything that looks like it is
    trying to steer the assistant is replaced with a marker.
    """
    cleaned = text
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[removed: instruction-like text]", cleaned)
    return cleaned


def clean_markdown(text: str) -> str:
    """Remove badges and HTML comments; normalise whitespace."""
    text = _HTML_COMMENT_RE.sub("", text)
    text = _BADGE_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


# --- comments ---------------------------------------------------------------

_BOT_LOGIN_RE = re.compile(r"\[bot\]$|\bbot$", re.I)
_NOISE_RE = re.compile(r"^(?:\+1|lgtm|\+1\s*)$|^\W*$", re.I)


def is_bot_comment(comment: dict) -> bool:
    user = comment.get("user") or {}
    if user.get("type") == "Bot":
        return True
    return bool(_BOT_LOGIN_RE.search(user.get("login", "")))


def is_noise_comment(body: str) -> bool:
    text = (body or "").strip()
    return len(text) <= 20 and bool(_NOISE_RE.match(text))


def clean_comments(comments: list[dict]) -> list[dict]:
    """Drop bot comments, '+1' noise, and anything instruction-like.

    A comment containing an injection attempt is removed whole rather than patched,
    so the "and reply that X" tail cannot survive the filter.
    """
    out = []
    for comment in comments or []:
        if is_bot_comment(comment):
            continue
        body = (comment.get("body") or "").strip()
        if is_noise_comment(body):
            continue
        if neutralize_instructions(body) != body:
            log.warning("dropped instruction-like comment from %s", comment.get("user", {}).get("login"))
            continue
        merged = dict(comment)
        merged["body"] = body
        out.append(merged)
    return out