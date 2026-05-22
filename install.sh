#!/usr/bin/env bash
# iTE One-Shot Installer
#   curl -fsSL https://ite.kiishi.space/install.sh | sh
#
# Detects OS/arch, downloads the correct standalone iTE runtime,
# verifies the checksum, and installs to ~/.ite/bin/ite.
#
# Environment overrides:
#   ITE_INSTALL_MANIFEST_URL   - override manifest URL for dev/testing
#   ITE_INSTALL_DIR            - override install directory
#   ITE_INSTALL_VERSION        - pin a specific version
#   ITE_INSTALL_SKIP_PATH      - skip PATH modification

set -euo pipefail

# ── Configuration ────────────────────────────────────────────
ITE_MANIFEST_URL="${ITE_INSTALL_MANIFEST_URL:-https://ite.kiishi.space/releases/manifest.json}"
ITE_MANAGED_ROOT="${ITE_INSTALL_DIR:-$HOME/.ite}"
ITE_BIN_DIR="${ITE_MANAGED_ROOT}/bin"
ITE_EXECUTABLE="${ITE_BIN_DIR}/ite"

# ── Terminal helpers ─────────────────────────────────────────
BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; BLUE=""; MAGENTA=""; RESET=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD="\033[1m"; DIM="\033[2m"
    GREEN="\033[32m"; YELLOW="\033[33m"
    RED="\033[31m"; CYAN="\033[36m"
    BLUE="\033[34m"; MAGENTA="\033[35m"
    RESET="\033[0m"
fi

info()    { printf "  ${DIM}%b${RESET}\n" "$*"; }
success() { printf "  ${GREEN}✓${RESET} %b\n" "$*"; }
warn()    { printf "  ${YELLOW}!${RESET} %b\n" "$*" >&2; }
error()   { printf "  ${RED}✗${RESET} %b\n" "$*" >&2; }
heading() { printf "  ${BOLD}${CYAN}%b${RESET}\n" "$*"; }

# ── Spinner ──────────────────────────────────────────────────
# Runs while a background PID is alive, shows a braille spinner.
spinner() {
    local pid="$1"
    local msg="$2"
    local frames="⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏"
    while kill -0 "$pid" 2>/dev/null; do
        for f in $frames; do
            printf "\r  ${BOLD}${CYAN}%s${RESET} ${DIM}%s${RESET}" "$f" "$msg" >&2
            sleep 0.1
        done
    done
    wait "$pid"
    return $?
}

# ── ASCII Banner ─────────────────────────────────────────────
show_banner() {
    printf "${BOLD}${CYAN}"
    printf "  ██╗ ████████╗ ███████╗\n"
    printf "  ╚═╝ ╚══██╔══╝ ██╔════╝\n"
    printf "  ██╗    ██║    █████╗  \n"
    printf "  ██║    ██║    ██╔══╝  \n"
    printf "  ██║    ██║    ███████╗\n"
    printf "  ╚═╝    ╚═╝    ╚══════╝"
    printf "${RESET}\n"
    printf "\n"
    printf "\n"
}

# ── OS / Arch detection ──────────────────────────────────────
detect_target() {
    local os arch

    case "$(uname -s)" in
        Darwin)  os="darwin" ;;
        Linux)   os="linux" ;;
        *)
            error "Unsupported operating system: $(uname -s)"
            error "iTE supports macOS and Linux. Windows: use install.ps1"
            exit 1
            ;;
    esac

    case "$(uname -m)" in
        arm64|aarch64) arch="arm64" ;;
        x86_64|amd64)  arch="x64" ;;
        *)
            error "Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

# ── Dependency checks ────────────────────────────────────────
check_deps() {
    local missing=""
    for cmd in curl tar; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing="$missing $cmd"
        fi
    done
    if [ -n "$missing" ]; then
        error "Missing required tools:${missing}"
        error "Please install them and try again."
        exit 1
    fi
}

# ── Fetch manifest ───────────────────────────────────────────
fetch_manifest() {
    local manifest_json
    manifest_json=$(curl -fsSL --connect-timeout 10 --max-time 30 "$ITE_MANIFEST_URL" 2>/dev/null) || {
        error "Could not reach release server"
        error "URL: $ITE_MANIFEST_URL"
        error "Check your internet connection or try again later."
        exit 1
    }
    echo "$manifest_json"
}

# ── Check existing install ───────────────────────────────────
check_existing() {
    local target="$1"
    local version="$2"
    local sha256="$3"
    local stamp_file="${ITE_MANAGED_ROOT}/.sha256"

    if [ -f "$ITE_EXECUTABLE" ]; then
        local installed_version
        installed_version=$("$ITE_EXECUTABLE" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) || true
        if [ "$installed_version" = "$version" ]; then
            local installed_sha256=""
            if [ -f "$stamp_file" ]; then
                installed_sha256=$(head -1 "$stamp_file")
            fi
            if [ "$installed_sha256" = "$sha256" ]; then
                success "iTE v${version} is already installed"
                info "Location: ${ITE_EXECUTABLE}"
                ensure_path
                exit 0
            fi
            info "v${version} already installed, but build differs — refreshing"
        elif [ -n "$installed_version" ]; then
            info "Updating from v${installed_version} → v${version}"
        else
            info "Repairing install..."
        fi
    fi

    for alt in pipx uv; do
        if command -v "$alt" >/dev/null 2>&1; then
            if "$alt" list 2>/dev/null | grep -q "ite-agent"; then
                info "Existing ${alt} install detected — will not modify it"
            fi
        fi
    done
}

# ── Download and verify ──────────────────────────────────────
download_artifact() {
    local url="$1"
    local sha256_expected="$2"
    local archive_path="$3"
    local label="$4"

    printf "  ${DIM}Downloading${RESET} ${BOLD}${label}${RESET}\n" >&2

    curl -fsSL --connect-timeout 10 --max-time 600 --retry 2 --retry-delay 2 \
        -C - -o "$archive_path" \
        "$url" &
    local curl_pid=$!

    spinner "$curl_pid" "Downloading..."

    local exit_code=$?
    if [ "$exit_code" -ne 0 ]; then
        printf "\r  ${RED}✗${RESET} ${DIM}Download failed${RESET}\n" >&2
        rm -f "$archive_path"
        exit 1
    fi

    local size
    size=$(ls -lh "$archive_path" 2>/dev/null | awk '{print $5}')
    printf "\r  ${GREEN}✓${RESET} ${DIM}Downloaded${RESET} ${size}\n" >&2

    if [ -n "$sha256_expected" ] && command -v shasum >/dev/null 2>&1; then
        printf "  ${DIM}Verifying checksum...${RESET}" >&2
        local sha256_actual
        sha256_actual=$(shasum -a 256 "$archive_path" | awk '{print $1}')
        if [ "$sha256_actual" != "$sha256_expected" ]; then
            printf "\r  ${RED}✗${RESET} ${DIM}Checksum mismatch${RESET}\n" >&2
            error "Expected: $sha256_expected"
            error "Got:      $sha256_actual"
            rm -f "$archive_path"
            exit 1
        fi
        printf "\r  ${GREEN}✓${RESET} ${DIM}Checksum verified${RESET}\n" >&2
    elif [ -n "$sha256_expected" ] && command -v sha256sum >/dev/null 2>&1; then
        printf "  ${DIM}Verifying checksum...${RESET}" >&2
        local sha256_actual
        sha256_actual=$(sha256sum "$archive_path" | awk '{print $1}')
        if [ "$sha256_actual" != "$sha256_expected" ]; then
            printf "\r  ${RED}✗${RESET} ${DIM}Checksum mismatch${RESET}\n" >&2
            error "Expected: $sha256_expected"
            error "Got:      $sha256_actual"
            rm -f "$archive_path"
            exit 1
        fi
        printf "\r  ${GREEN}✓${RESET} ${DIM}Checksum verified${RESET}\n" >&2
    fi
}

# ── Install ──────────────────────────────────────────────────
install_artifact() {
    local archive_path="$1"
    local archive_type="$2"
    local executable_name="$3"
    local sha256="$4"

    mkdir -p "$ITE_BIN_DIR"

    local tmp_extract
    tmp_extract=$(mktemp -d /tmp/ite-install.XXXXXX)
    trap "rm -rf $tmp_extract" EXIT

    if [ "$archive_type" = "tar.gz" ]; then
        tar -xzf "$archive_path" -C "$tmp_extract"
    else
        error "Unsupported archive type: $archive_type"
        exit 1
    fi

    local extracted_dir
    extracted_dir=$(find "$tmp_extract" -maxdepth 1 -mindepth 1 -type d | head -1)

    if [ ! -d "$extracted_dir" ]; then
        error "Archive extraction produced unexpected layout"
        exit 1
    fi

    rm -rf "${ITE_BIN_DIR:?}/"*
    cp -R "$extracted_dir"/* "$ITE_BIN_DIR"/
    chmod +x "$ITE_EXECUTABLE" 2>/dev/null || true

    local installed_version
    installed_version=$("$ITE_EXECUTABLE" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) || true
    success "Installed iTE v${installed_version:-unknown}"
    info "Location: ${ITE_EXECUTABLE}"

    if [ -n "$sha256" ]; then
        echo "$sha256" > "${ITE_MANAGED_ROOT}/.sha256"
    fi
}

# ── PATH management ──────────────────────────────────────────
ensure_path() {
    if [ "${ITE_INSTALL_SKIP_PATH:-}" = "1" ]; then
        return
    fi

    if echo "$PATH" | tr ':' '\n' | grep -qxF "$ITE_BIN_DIR"; then
        return
    fi

    local shell_profile=""
    local shell_name
    shell_name=$(basename "${SHELL:-/bin/sh}")

    case "$shell_name" in
        zsh)
            if [ -f "$HOME/.zshrc" ]; then
                shell_profile="$HOME/.zshrc"
            elif [ -f "$HOME/.zprofile" ]; then
                shell_profile="$HOME/.zprofile"
            fi
            ;;
        bash)
            if [ -f "$HOME/.bash_profile" ]; then
                shell_profile="$HOME/.bash_profile"
            elif [ -f "$HOME/.bashrc" ]; then
                shell_profile="$HOME/.bashrc"
            elif [ -f "$HOME/.profile" ]; then
                shell_profile="$HOME/.profile"
            fi
            ;;
        *)
            if [ -f "$HOME/.profile" ]; then
                shell_profile="$HOME/.profile"
            fi
            ;;
    esac

    local path_line="export PATH=\"\$HOME/.ite/bin:\$PATH\""

    if [ -n "$shell_profile" ]; then
        if grep -qF ".ite/bin" "$shell_profile" 2>/dev/null; then
            return
        fi
        printf '\n# iTE\n%s\n' "$path_line" >> "$shell_profile"
        success "Added to PATH (${shell_profile})"
        info "Restart your terminal or run: source ${shell_profile}"
    else
        warn "Could not detect shell profile to update PATH."
        echo ""
        echo "  Add this to your shell profile:"
        echo "  ${BOLD}${path_line}${RESET}"
        echo ""
    fi
}

# ── Main ─────────────────────────────────────────────────────
main() {
    show_banner

    check_deps

    local target
    target=$(detect_target)

    local manifest_json
    manifest_json=$(fetch_manifest)

    # Parse manifest
    local version url sha256 archive_type executable_name
    if command -v python3 >/dev/null 2>&1; then
        local parsed_tmp
        parsed_tmp=$(mktemp)
        echo "$manifest_json" | python3 -c "
import json, sys
m = json.load(sys.stdin)
a = m['assets'].get('$target', {})
print(
    m.get('version', ''),
    a.get('url', ''),
    a.get('sha256', ''),
    a.get('archiveType', 'tar.gz'),
    a.get('executable', 'ite'),
    sep=chr(10))
" > "$parsed_tmp"
        {
            read -r version
            read -r url
            read -r sha256
            read -r archive_type
            read -r executable_name
        } < "$parsed_tmp"
        rm -f "$parsed_tmp"
    elif command -v jq >/dev/null 2>&1; then
        version=$(echo "$manifest_json" | jq -r '.version')
        url=$(echo "$manifest_json" | jq -r ".assets[\"$target\"].url")
        sha256=$(echo "$manifest_json" | jq -r ".assets[\"$target\"].sha256")
        archive_type=$(echo "$manifest_json" | jq -r ".assets[\"$target\"].archiveType")
        executable_name=$(echo "$manifest_json" | jq -r ".assets[\"$target\"].executable")
    else
        error "Need python3 or jq to parse the release manifest"
        exit 1
    fi

    if [ -z "$url" ] || [ "$url" = "null" ]; then
        error "No build available for: ${target}"
        error "Supported: darwin-arm64, darwin-x64, linux-x64"
        exit 1
    fi

    version="${ITE_INSTALL_VERSION:-$version}"

    success "Detected ${BOLD}${target}${RESET}"

    check_existing "$target" "$version" "$sha256"

    local archive_ext="tar.gz"
    [ "$archive_type" = "zip" ] && archive_ext="zip"
    local archive_name="ite-${version}-${target}.${archive_ext}"
    local archive_path="/tmp/${archive_name}"
    local label="iTE v${version} (${target})"

    rm -f "$archive_path"

    download_artifact "$url" "$sha256" "$archive_path" "$label"
    install_artifact "$archive_path" "$archive_type" "$executable_name" "$sha256"
    ensure_path

    rm -f "$archive_path"

    echo ""
    heading "Ready! Run: ${BOLD}ite${RESET}"
    echo ""
}

main "$@"
