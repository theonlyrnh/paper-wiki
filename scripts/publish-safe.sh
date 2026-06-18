#!/usr/bin/env bash
# publish-safe.sh — build and optionally publish a sanitized public snapshot.
#
# Safety principles:
#   1. This script must NEVER contain real private domains, IPs, API hosts, tokens, or passwords.
#   2. Public output is built from an explicit allowlist plus a hard denylist.
#   3. The script defaults to dry-run. It does not push unless --push is provided.
#   4. Push requires an explicit repository URL and typing YES at the final prompt.
#   5. Force-push is disabled unless --force is explicitly provided.
#
# Usage examples:
#   scripts/publish-safe.sh
#   scripts/publish-safe.sh --repo https://github.com/OWNER/REPO.git --push
#   scripts/publish-safe.sh --repo https://github.com/OWNER/REPO.git --push --force

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PUBLISH_DIR=""
REPO_URL="${PUBLIC_REPO_URL:-}"
COMMIT_MSG="${PUBLISH_COMMIT_MSG:-sanitize public repository}"
DO_PUSH=0
DO_FORCE=0
KEEP_DIR="${KEEP_PUBLISH_DIR:-0}"

usage() {
  sed -n '1,30p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --commit-msg)
      COMMIT_MSG="${2:-}"
      shift 2
      ;;
    --push)
      DO_PUSH=1
      shift
      ;;
    --force)
      DO_FORCE=1
      shift
      ;;
    --keep-dir)
      KEEP_DIR=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

require_command git
require_command python3
require_command rsync

cd "$SOURCE_DIR"

# Hard stop if the old unsafe upload helper reappears in the project tree.
# It is safe only outside the project, ignored by Git, and never copied to public snapshots.
if [[ -e "$SOURCE_DIR/upload-github.sh" ]]; then
  fail "Refusing to publish: upload-github.sh exists in project root. Move local upload helpers outside the repo."
fi

if git ls-files --error-unmatch upload-github.sh >/dev/null 2>&1; then
  fail "Refusing to publish: upload-github.sh is tracked by Git. Remove it from history/current tree first."
fi

if [[ "$DO_PUSH" -eq 1 ]]; then
  [[ -n "$REPO_URL" ]] || fail "--push requires --repo URL or PUBLIC_REPO_URL. No default URL is allowed."
  case "$REPO_URL" in
    https://github.com/*/*.git|git@github.com:*/*.git) ;;
    *) fail "Repository URL must be an explicit GitHub URL ending in .git" ;;
  esac
fi

PUBLISH_DIR="$(mktemp -d /tmp/paper-wiki-public-publish-XXXXXX)"

cleanup() {
  if [[ "$KEEP_DIR" != "1" && -n "$PUBLISH_DIR" && -d "$PUBLISH_DIR" ]]; then
    rm -rf "$PUBLISH_DIR"
  fi
}
trap cleanup EXIT

log "Building public snapshot"
echo "Source : $SOURCE_DIR"
echo "Output : $PUBLISH_DIR"

# Public allowlist. Keep this list broad enough for public app source, but never include local/private files.
PUBLIC_PATHS=(
  ".env.example"
  ".gitignore"
  "AI_DEV_RULES.md"
  "CHANGELOG.md"
  "README.md"
  "VERSION"
  "config.yaml.example"
  "requirements.txt"
  "tunnel.sh"
  "backend"
  "frontend"
  "scripts"
  "docs"
  "improvements"
)

# Denylist is applied even inside allowed directories.
RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--include=.env.example"
  "--exclude=.env"
  "--exclude=.env.*"
  "--exclude=config.yaml"
  "--exclude=config.local.yaml"
  "--exclude=config.*.local.yaml"
  "--exclude=data/"
  "--exclude=logs/"
  "--exclude=pids/"
  "--exclude=backups/"
  "--exclude=.upload-snapshot/"
  "--exclude=.upload-guard-backup/"
  "--exclude=upload-github.sh"
  "--exclude=*.local"
  "--exclude=*.local.sh"
  "--exclude=.upload-secrets.local"
  "--exclude=local-only/"
  "--exclude=artifacts/"
  "--exclude=screenshots/"
  "--exclude=PixPin_*.png"
  "--exclude=node_modules/"
  "--exclude=.venv/"
  "--exclude=venv/"
  "--exclude=__pycache__/"
  "--exclude=*.pyc"
  "--exclude=*.pyo"
  "--exclude=*.pem"
  "--exclude=*.key"
  "--exclude=id_rsa"
  "--exclude=id_ed25519"
  "--exclude=scripts/scan_sensitive.py"
  "--exclude=docs/security/AI_UPLOAD_SECURITY.md"
  "--exclude=docs/design/"
  "--exclude=docs/design/login-design.md"
  "--exclude=docs/design/frontend-layout-scroll-standards.md"
  "--exclude=docs/reviews/CODE_REVIEW.md"
  "--exclude=docs/ingest-stability-first-batch-handoff.md"
  "--exclude=superpowers/"
  "--exclude=scripts/cleanup_unknown.py"
  "--exclude=scripts/scan_sensitive.py"
  "--exclude=scripts/test_layout_regressions.sh"
  "--exclude=PROJECT_CONTEXT.md"
)

for path in "${PUBLIC_PATHS[@]}"; do
  if [[ -e "$SOURCE_DIR/$path" ]]; then
    mkdir -p "$PUBLISH_DIR/$(dirname "$path")"
    rsync -a "${RSYNC_EXCLUDES[@]}" "$SOURCE_DIR/$path" "$PUBLISH_DIR/$(dirname "$path")/"
  fi
done

log "Hard forbidden-file check"
for required in \
  ".env.example" \
  "config.yaml.example"; do
  if [[ ! -f "$PUBLISH_DIR/$required" ]]; then
    fail "Required public placeholder file is missing from public snapshot: $required"
  fi
done

for forbidden in \
  ".env" \
  "config.yaml" \
  "upload-github.sh" \
  ".upload-guard-backup" \
  "data" \
  "backups" \
  "logs" \
  "pids" \
  "local-only"; do
  if [[ -e "$PUBLISH_DIR/$forbidden" ]]; then
    fail "Forbidden path copied into public snapshot: $forbidden"
  fi
done

log "Running built-in public snapshot scanner"
python3 - "$PUBLISH_DIR" <<'PY'
from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
failures: list[str] = []
warnings: list[str] = []

FORBIDDEN_NAMES = {
    ".env",
    "config.yaml",
    "upload-github.sh",
    ".upload-guard-backup",
    ".upload-secrets.local",
    "id_rsa",
    "id_ed25519",
}
FORBIDDEN_DIR_PARTS = {
    ".git",
    "data",
    "logs",
    "pids",
    "backups",
    "local-only",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
}

TOKEN_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "literal secret assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b"
            r"\s*[:=]\s*['\"]([^'\"<>{}$\s][^'\"<>{}$\s]{11,})['\"]"
        ),
    ),
]

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"(?i)\bhttps?://([^/\"'`\s<>]+)")
CONFIG_HOST_RE = re.compile(
    r"""(?ix)
    \b(api[_-]?base|api[_-]?url|base[_-]?url|host|hostname|domain|server_name|repo_url)\b
    \s*[:=]\s*
    ['"]?
    (?!\$\{)
    (?:
        https?://
    )?
    (?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)
    (?::\d{2,5})?
    """,
)
LOCAL_PATH_RE = re.compile(r"/(?:home|Users)/(?!(?:your-user|example-user)(?:/|\b))[A-Za-z0-9._-]+/")

# Keep this allowlist small and intentionally boring. Add public CDN/docs domains only after review.
ALLOWED_DOMAIN_SUFFIXES = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".localhost",
)
ALLOWED_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "api.openai.com",
    "github.com",
    "raw.githubusercontent.com",
    "img.shields.io",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "cdn.tailwindcss.com",
    "pypi.org",
    "pypi.python.org",
    "python.org",
    "graphviz.org",
    "plantuml.com",
}

PLACEHOLDER_MARKERS = (
    "your_",
    "your-",
    "example",
    "changeme",
    "change_me",
    "placeholder",
    "<",
    ">",
    "${",
    "***",
    "xxxxx",
    "dummy",
    "not-set",
)

ALLOWED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/32"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]

TEXT_EXTS = {
    ".py", ".js", ".html", ".css", ".md", ".txt", ".yaml", ".yml",
    ".json", ".toml", ".sh", ".example", ".env", "",
}


def rel(path: Path) -> str:
    return str(path.relative_to(root))


def is_allowed_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(ip in network for network in ALLOWED_IP_NETWORKS)


def is_allowed_domain(value: str) -> bool:
    value = value.lower().strip(".")
    value = value.split(":", 1)[0]
    if value in ALLOWED_DOMAINS:
        return True
    return any(value.endswith(suffix) for suffix in ALLOWED_DOMAIN_SUFFIXES)


def is_allowed_host(value: str) -> bool:
    value = strip_url_port(value)
    if not value or value.startswith(("$", "{")):
        return True
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return is_allowed_domain(value)
    return is_allowed_ip(value)


def line_has_placeholder(line: str) -> bool:
    lower = line.lower()
    return any(marker in lower for marker in PLACEHOLDER_MARKERS)


def strip_url_port(host: str) -> str:
    return host.strip().strip("[]").split(":", 1)[0].lower().strip(".")


def looks_like_file_reference(value: str) -> bool:
    lower = value.lower()
    file_suffixes = (
        ".py", ".js", ".html", ".css", ".md", ".json", ".yaml", ".yml",
        ".txt", ".sh", ".db", ".pid", ".log", ".example", ".patch", ".class",
    )
    return lower.endswith(file_suffixes)


for path in root.rglob("*"):
    relative = rel(path)
    parts = set(path.relative_to(root).parts)
    if path.name in FORBIDDEN_NAMES:
        failures.append(f"forbidden file name: {relative}")
    if parts & FORBIDDEN_DIR_PARTS:
        failures.append(f"forbidden directory component: {relative}")
    if not path.is_file():
        continue
    if path.suffix not in TEXT_EXTS and path.name not in {"README", "LICENSE"}:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        warnings.append(f"could not read {relative}: {exc}")
        continue

    for label, pattern in TOKEN_PATTERNS:
        if pattern.search(text):
            for lineno, line in enumerate(text.splitlines(), 1):
                if line_has_placeholder(line):
                    continue
                if pattern.search(line):
                    failures.append(f"possible secret/token in {relative}:{lineno}: {label}")

    for match in IP_RE.finditer(text):
        value = match.group(0)
        if not is_allowed_ip(value):
            failures.append(f"non-placeholder IPv4 in {relative}: {value}")

    for match in LOCAL_PATH_RE.finditer(text):
        failures.append(f"local user path in {relative}: {match.group(0)}")

    for lineno, line in enumerate(text.splitlines(), 1):
        if line_has_placeholder(line):
            continue

        for match in URL_RE.finditer(line):
            host = strip_url_port(match.group(1))
            if not is_allowed_host(host):
                failures.append(f"unreviewed URL host in {relative}:{lineno}: {host}")

        for match in CONFIG_HOST_RE.finditer(line):
            host = strip_url_port(match.group("host"))
            if looks_like_file_reference(host):
                continue
            if not is_allowed_host(host):
                failures.append(f"unreviewed configured host in {relative}:{lineno}: {host}")

if failures:
    print("Public snapshot scanner FAILED:")
    for item in failures[:200]:
        print("  -", item)
    if len(failures) > 200:
        print(f"  ... {len(failures) - 200} more")
    sys.exit(1)

print("Public snapshot scanner OK")
if warnings:
    print("Warnings:")
    for item in warnings:
        print("  -", item)
PY

log "Running optional repo scanner if available"
if [[ -f "$SOURCE_DIR/scripts/scan_sensitive.py" ]]; then
  python3 "$SOURCE_DIR/scripts/scan_sensitive.py" "$PUBLISH_DIR"
else
  echo "scripts/scan_sensitive.py not found; skipped optional repo scanner"
fi

log "Running standardized safety check if configured"
SAFETY_CHECK="${AI_DEV_SAFETY_CHECK:-}"
if [[ -n "$SAFETY_CHECK" && -f "$SAFETY_CHECK" ]]; then
  python3 "$SAFETY_CHECK" "$PUBLISH_DIR"
else
  echo "AI_DEV_SAFETY_CHECK is not set to an existing file; skipped optional external checker"
fi

log "Creating temporary Git commit for review"
cd "$PUBLISH_DIR"
git init >/dev/null
if git show-ref --verify --quiet refs/heads/master; then
  git branch -m main
else
  git checkout -B main >/dev/null
fi
if ! git config user.email >/dev/null; then git config user.email "public-publish@example.com"; fi
if ! git config user.name >/dev/null; then git config user.name "Safe Public Publisher"; fi
git add -A
git commit -m "$COMMIT_MSG" >/dev/null

echo "Commit: $(git rev-parse --short HEAD) $COMMIT_MSG"
echo "Files : $(git ls-files | wc -l | tr -d ' ')"

log "Tracked forbidden-file check"
if git ls-files | grep -E '(^upload-github\.sh$|^data/|^backups/|^\.env$|^config\.yaml$|^\.upload-guard-backup/|^logs/|^pids/|^local-only/)'; then
  fail "Forbidden paths are tracked in public snapshot"
fi

echo "Public snapshot is ready at: $PUBLISH_DIR"

if [[ "$DO_PUSH" -ne 1 ]]; then
  echo "Dry-run only. Nothing was pushed. Use --push --repo <url> after reviewing the snapshot."
  if [[ "$KEEP_DIR" != "1" ]]; then
    echo "Set --keep-dir or KEEP_PUBLISH_DIR=1 if you want to inspect the snapshot after the script exits."
  fi
  exit 0
fi

log "Preparing to push"
git remote add origin "$REPO_URL"
git fetch origin main >/dev/null 2>&1 || true

echo "Repository: $REPO_URL"
echo "Branch    : main"
echo "Force     : $DO_FORCE"
echo "Commit    : $(git rev-parse --short HEAD)"
echo ""
echo "This operation publishes the sanitized snapshot built from the allowlist above."
echo "Type YES to continue:"
read -r confirm
if [[ "$confirm" != "YES" ]]; then
  fail "Push cancelled by user"
fi

if [[ "$DO_FORCE" -eq 1 ]]; then
  git push --force-with-lease=refs/heads/main origin main:main
else
  git push origin main:main
fi

log "Remote verification"
remote_head="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
[[ -n "$remote_head" ]] || fail "Could not read remote main after push"
echo "Remote main: ${remote_head:0:12}"
echo "Publish finished. If this replaced leaked history, also rotate/examine any exposed services and check GitHub caches."
