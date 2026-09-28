#!/usr/bin/env bash
# Create GitHub Release with iTE runtime artifacts
#
# Usage:
#   scripts/github-release.sh                          # create release for current version
#   scripts/github-release.sh --version 0.0.70         # specific version
#   scripts/github-release.sh --dry-run                # show what would happen
#
# Requires: gh CLI (brew install gh && gh auth login)
#    OR:    GITHUB_TOKEN env var for curl-based fallback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Helpers ───────────────────────────────────────────
info()    { echo "  → $*"; }
success() { echo "  ✓ $*"; }
warn()    { echo "  ⚠ $*" >&2; }
fail()    { echo "  ✗ $*" >&2; exit 1; }

# ── Get version ──────────────────────────────────────
get_version() {
    if [ -n "${VERSION_OVERRIDE:-}" ]; then
        echo "$VERSION_OVERRIDE"
        return
    fi
    python3 -c "from ite import __version__; print(__version__)" 2>/dev/null || \
    python3 -c "
import tomli
with open('pyproject.toml', 'rb') as f:
    print(tomli.load(f)['project']['version'])
" 2>/dev/null || \
    echo "0.0.0-dev"
}

# ── Find artifacts ───────────────────────────────────
find_artifacts() {
    local version="$1"
    local artifacts=()
    local runtime_dir="$PROJECT_ROOT/dist/runtime"

    for target in darwin-arm64 darwin-x64 linux-x64; do
        local archive="$runtime_dir/${target}/ite-${version}-${target}.tar.gz"
        if [ -f "$archive" ]; then
            artifacts+=("$archive")
            local checksum="$archive.sha256"
            if [ -f "$checksum" ]; then
                artifacts+=("$checksum")
            fi
        fi
    done

    local win_archive="$runtime_dir/win32-x64/ite-${version}-win32-x64.zip"
    if [ -f "$win_archive" ]; then
        artifacts+=("$win_archive")
        local win_checksum="$win_archive.sha256"
        if [ -f "$win_checksum" ]; then
            artifacts+=("$win_checksum")
        fi
    fi

    for artifact in "${artifacts[@]}"; do
        echo "$artifact"
    done
}

# ── Create release with gh CLI ───────────────────────
create_with_gh() {
    local version="$1"
    local tag="v${version}"
    local title="v${version}"
    shift
    local artifacts=("$@")

    if [ ${#artifacts[@]} -eq 0 ]; then
        fail "No artifacts found. Run build first: python3 scripts/build_runtime.py --target darwin-arm64"
    fi

    info "Creating GitHub Release with gh CLI..."
    info "  Tag:   $tag"
    info "  Title: $title"
    info "  Files: ${#artifacts[@]}"

    if [ "${DRY_RUN:-false}" = "true" ]; then
        for f in "${artifacts[@]}"; do
            info "  [DRY RUN] Would upload: $f"
        done
        return
    fi

    # Check if the tag already exists
    if gh release view "$tag" --repo ThatSaxyDev/ite-releases &>/dev/null; then
        warn "Release $tag already exists. Uploading artifacts..."

        # Delete existing release and recreate
        gh release delete "$tag" --repo ThatSaxyDev/ite-releases --yes 2>/dev/null || true
        # Also delete the tag locally and remotely
        git -C "$PROJECT_ROOT" tag -d "$tag" 2>/dev/null || true
    fi

    # Create the release
    gh release create "$tag" \
        --repo ThatSaxyDev/ite-releases \
        --title "$title" \
        --notes "iTE v${version} — standalone runtime

### One-command install

\`\`\`bash
curl -fsSL https://ite.kiishi.space/install.sh | bash
\`\`\`

### Artifacts

Built with PyInstaller. Includes bundled Python + all dependencies.
" \
        "${artifacts[@]}"

    success "GitHub Release $tag created with ${#artifacts[@]} files."
}

# ── Create release with curl (GITHUB_TOKEN) ──────────
create_with_curl() {
    local version="$1"
    local tag="v${version}"
    shift
    local artifacts=("$@")

    local repo="ThatSaxyDev/ite-releases"
    local token="${GITHUB_TOKEN:-}"

    if [ -z "$token" ]; then
        fail "Missing GITHUB_TOKEN env var for curl-based release. Set GITHUB_TOKEN or install gh CLI (brew install gh)."
    fi

    if [ ${#artifacts[@]} -eq 0 ]; then
        fail "No artifacts found. Run build first."
    fi

    info "Creating GitHub Release via API..."
    info "  Tag: $tag"

    if [ "${DRY_RUN:-false}" = "true" ]; then
        for f in "${artifacts[@]}"; do
            info "  [DRY RUN] Would upload: $f"
        done
        return
    fi

    # Create the release
    local response
    response=$(curl -s -X POST \
        -H "Authorization: token $token" \
        -H "Content-Type: application/json" \
        "https://api.github.com/repos/$repo/releases" \
        -d "{
            \"tag_name\": \"$tag\",
            \"name\": \"$tag\",
            \"body\": \"iTE v${version} — standalone runtime build\",
            \"draft\": false,
            \"prerelease\": false
        }")

    local upload_url
    upload_url=$(echo "$response" | python3 -c "import json,sys; print(json.load(sys.stdin).get('upload_url','').replace('{?name,label}',''))" 2>/dev/null)

    if [ -z "$upload_url" ]; then
        fail "Failed to create release. Response: $response"
    fi

    # Upload each artifact
    for f in "${artifacts[@]}"; do
        local filename
        filename=$(basename "$f")
        info "  Uploading: $filename"

        local content_type="application/octet-stream"
        case "$f" in
            *.sha256) content_type="text/plain" ;;
            *.tar.gz) content_type="application/gzip" ;;
            *.zip)    content_type="application/zip" ;;
        esac

        curl -s -X POST \
            -H "Authorization: token $token" \
            -H "Content-Type: $content_type" \
            --data-binary "@$f" \
            "$upload_url?name=$filename" > /dev/null
    done

    success "GitHub Release $tag created with ${#artifacts[@]} files."
}

# ── Main ─────────────────────────────────────────────
main() {
    local version
    DRY_RUN=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --version) VERSION_OVERRIDE="$2"; shift 2 ;;
            --dry-run) DRY_RUN=true; shift ;;
            *) fail "Unknown option: $1" ;;
        esac
    done

    version=$(get_version)
    cd "$PROJECT_ROOT"

    echo ""
    echo "  iTE GitHub Release Publisher"
    echo ""

    # Collect artifacts
    local artifacts=()
    while IFS= read -r line; do
        [ -n "$line" ] && artifacts+=("$line")
    done < <(find_artifacts "$version")

    if [ ${#artifacts[@]} -eq 0 ]; then
        echo ""
        warn "No artifacts found in dist/runtime/"
        echo ""
        echo "  Build for darwin-arm64 first:"
        echo "    python3 scripts/build_runtime.py --target darwin-arm64"
        echo ""
        echo "  For all platforms:"
        echo "    python3 scripts/build_runtime.py --all"
        echo ""
        exit 1
    fi

    info "Found ${#artifacts[@]} artifacts for v${version}"
    for f in "${artifacts[@]}"; do
        echo "       $(basename "$f")"
    done
    echo ""

    # Use gh CLI if available, otherwise curl with GITHUB_TOKEN
    if command -v gh &>/dev/null; then
        info "Using gh CLI"
        create_with_gh "$version" "${artifacts[@]}"
    elif [ -n "${GITHUB_TOKEN:-}" ]; then
        info "gh CLI not found, using curl + GITHUB_TOKEN"
        create_with_curl "$version" "${artifacts[@]}"
    elif [ "$DRY_RUN" = "true" ]; then
        info "  [DRY RUN] Would create release with ${#artifacts[@]} files"
    else
        warn "Cannot create GitHub Release — no auth method found."
        echo ""
        echo "  Option 1: Install gh CLI (recommended)"
        echo "    brew install gh"
        echo "    gh auth login"
        echo "    bash scripts/github-release.sh"
        echo ""
        echo "  Option 2: Use a personal access token"
        echo "    export GITHUB_TOKEN=ghp_..."
        echo "    bash scripts/github-release.sh"
        echo ""
        echo "  Option 3: Create the release manually:"
        echo "    https://github.com/ThatSaxyDev/ite-releases/releases/new"
        echo "    Tag: v$version"
        echo "    Upload: $(ls "$PROJECT_ROOT/dist/runtime"/darwin-arm64/ite-*.tar.gz 2>/dev/null || echo 'ite-VERSION-darwin-arm64.tar.gz')"
        echo ""
        exit 0
    fi

    echo ""
    echo "  Next: Deploy cloud-web to update the installer manifest"
    echo "  cd ../ite-cloud-web && git push"
    echo ""
}

main "$@"
