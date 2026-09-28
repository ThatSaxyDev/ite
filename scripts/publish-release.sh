#!/usr/bin/env bash
# Publish iTE release — build, package, create GitHub Release, deploy to web
#
# Usage:
#   scripts/publish-release.sh              # Build, create GitHub Release, copy to web
#   scripts/publish-release.sh --dry-run    # Preview
#   scripts/publish-release.sh --build-only # Only build artifacts
#   scripts/publish-release.sh --skip-release # Skip GitHub Release step

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLOUD_WEB_DIR="${ITE_CLOUD_WEB_DIR:-$PROJECT_ROOT/../ite-cloud-web}"
DRY_RUN="${DRY_RUN:-false}"
SKIP_RELEASE="${SKIP_RELEASE:-false}"
BUILD_TARGET="${BUILD_TARGET:-darwin-arm64}"

# ── Helpers ───────────────────────────────────────────
info()    { echo "  → $*"; }
warn()    { echo "  ⚠ $*" >&2; }
success() { echo "  ✓ $*"; }

# ── Step 1: Build runtime artifacts ──────────────────
build_artifacts() {
    info "Building runtime artifacts for ${BUILD_TARGET}..."

    if [ "$DRY_RUN" = "true" ]; then
        info "  [DRY RUN] Would run: python3 scripts/build_runtime.py --target ${BUILD_TARGET}"
        return
    fi

    python3 scripts/build_runtime.py --target "$BUILD_TARGET"
    success "Runtime artifacts built"
}

# ── Step 2: Copy static files to cloud-web ───────────
copy_to_web() {
    if [ ! -d "$CLOUD_WEB_DIR" ]; then
        warn "Cloud web directory not found: $CLOUD_WEB_DIR"
        warn "Set ITE_CLOUD_WEB_DIR env var or run from the correct location."
        return 1
    fi

    local public_dir="$CLOUD_WEB_DIR/public"

    info "Copying static files to cloud-web..."
    info "  From: $PROJECT_ROOT"
    info "  To:   $public_dir"

    if [ "$DRY_RUN" = "true" ]; then
        info "  [DRY RUN] Would copy:"
        info "    install.sh → $public_dir/install.sh"
        info "    install.ps1 → $public_dir/install.ps1"
        info "    dist/manifest.json → $public_dir/releases/manifest.json"
        return
    fi

    cp "$PROJECT_ROOT/install.sh" "$public_dir/install.sh"
    cp "$PROJECT_ROOT/install.ps1" "$public_dir/install.ps1"
    mkdir -p "$public_dir/releases"
    cp "$PROJECT_ROOT/dist/manifest.json" "$public_dir/releases/manifest.json"

    success "Static files copied to cloud-web"
}

# ── Step 3: Create GitHub Release ──────────────────
create_github_release() {
    info "Creating GitHub Release..."

    if [ "$DRY_RUN" = "true" ]; then
        info "  [DRY RUN] Would run: bash scripts/github-release.sh"
        return
    fi

    if [ "$SKIP_RELEASE" = "true" ]; then
        info "  Skipping GitHub Release (--skip-release)"
        return
    fi

    bash "$PROJECT_ROOT/scripts/github-release.sh"
}

# ── Step 4: Deploy instructions ──────────────────────
print_deploy_instructions() {
    echo ""
    echo "  ── Deploy Web ─────────────────────────────────"
    echo ""
    echo "  cd ../ite-cloud-web"
    echo "  git add public/install.sh public/install.ps1 public/releases/manifest.json"
    echo "  git commit -m 'release: iTE one-command installer'"
    echo "  git push"
    echo ""
    echo "  Netlify will auto-deploy."
    echo ""
    echo "  ── Verify ─────────────────────────────────────"
    echo "  curl -fsSL https://ite.kiishi.space/install.sh | head -5"
    echo "  curl -fsSL https://ite.kiishi.space/releases/manifest.json | python3 -m json.tool"
    echo ""
}

# ── Main ─────────────────────────────────────────────
main() {
    local build_only=false
    local web_only=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --target) BUILD_TARGET="$2"; shift ;;
            --dry-run) DRY_RUN=true ;;
            --build-only) SKIP_RELEASE=true ;;
            --skip-release) SKIP_RELEASE=true ;;
            *) info "Unknown option: $1"; exit 1 ;;
        esac
        shift
    done

    cd "$PROJECT_ROOT"

    echo ""
    echo "  iTE Release Publisher"
    echo ""

    build_artifacts
    copy_to_web
    create_github_release
    print_deploy_instructions
}

main "$@"
