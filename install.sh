#!/usr/bin/env bash
set -euo pipefail

# Claude Ads Installer
# Wraps everything in main() to prevent partial execution on network failure
#
# Usage:
#   curl -fsSL https://github.com/bendervintimilla/skills-AI-marketing-tool/raw/main/install.sh | bash
#   bash install.sh          # pulls from GitHub
#   bash install.sh --local  # deploys from this directory (development mode)

main() {
    SKILL_DIR="${HOME}/.claude/skills/ads"
    AGENT_DIR="${HOME}/.claude/agents"
    REPO_URL="https://github.com/bendervintimilla/skills-AI-marketing-tool"
    LOCAL_MODE=false

    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --local) LOCAL_MODE=true ;;
            --help|-h)
                echo "Usage: bash install.sh [--local]"
                echo "  --local  Deploy from current directory instead of cloning GitHub"
                exit 0
                ;;
        esac
    done

    echo "════════════════════════════════════════"
    echo "║   Claude Ads - Installer             ║"
    echo "║   Claude Code Paid Ads Skill         ║"
    echo "════════════════════════════════════════"
    echo ""

    if $LOCAL_MODE; then
        # Resolve source directory: script location or current dir
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        SOURCE_DIR="${SCRIPT_DIR}"
        echo "→ Local mode: deploying from ${SOURCE_DIR}"
    else
        # Check prerequisites for remote mode
        command -v git >/dev/null 2>&1 || { echo "✗ Git is required but not installed."; exit 1; }
        echo "✓ Git detected"
    fi

    # Create directories
    mkdir -p "${SKILL_DIR}/references"
    mkdir -p "${AGENT_DIR}"

    if $LOCAL_MODE; then
        SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    else
        # Clone from GitHub
        TEMP_DIR=$(mktemp -d)
        trap 'rm -rf "${TEMP_DIR}"' EXIT
        echo "↓ Downloading Claude Ads..."
        git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}/claude-ads" 2>/dev/null
        SOURCE_DIR="${TEMP_DIR}/claude-ads"
    fi

    # Copy main skill + references
    echo "→ Installing skill files..."
    cp "${SOURCE_DIR}/ads/SKILL.md" "${SKILL_DIR}/SKILL.md"
    cp "${SOURCE_DIR}/ads/references/"*.md "${SKILL_DIR}/references/"

    # Copy sub-skills
    echo "→ Installing sub-skills..."
    for skill_dir in "${SOURCE_DIR}/skills"/*/; do
        skill_name=$(basename "${skill_dir}")
        target="${HOME}/.claude/skills/${skill_name}"
        mkdir -p "${target}"
        cp "${skill_dir}SKILL.md" "${target}/SKILL.md"

        # Copy assets (industry templates) if they exist
        if [ -d "${skill_dir}assets" ]; then
            mkdir -p "${target}/assets"
            cp "${skill_dir}assets/"*.md "${target}/assets/"
        fi
    done

    # Copy agents
    echo "→ Installing subagents..."
    cp "${SOURCE_DIR}/agents/"*.md "${AGENT_DIR}/" 2>/dev/null || true

    # Copy scripts (optional Python tools)
    SCRIPTS_DIR="${HOME}/.claude/skills/ads/scripts"
    if [ -d "${SOURCE_DIR}/scripts" ]; then
        echo "→ Installing Python scripts..."
        mkdir -p "${SCRIPTS_DIR}"
        cp "${SOURCE_DIR}/scripts/"*.py "${SCRIPTS_DIR}/"
        cp "${SOURCE_DIR}/requirements.txt" "${SKILL_DIR}/requirements.txt"
    fi

    # Install Python dependencies
    echo ""
    echo "→ Installing Python dependencies..."
    if command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1; then
        PIP_CMD="pip3"
        command -v pip3 >/dev/null 2>&1 || PIP_CMD="pip"
        ${PIP_CMD} install -q -r "${SKILL_DIR}/requirements.txt" 2>/dev/null \
            || { echo "  ⚠ Standard pip install failed, trying --break-system-packages..." >&2; \
                 ${PIP_CMD} install --break-system-packages -q -r "${SKILL_DIR}/requirements.txt" 2>/dev/null; } \
            && echo "  ✓ Python dependencies installed" \
            || echo "  ⚠ pip install failed. Run manually: pip3 install -r ${SKILL_DIR}/requirements.txt"
    else
        echo "  ⚠ pip not found. Install deps manually: pip3 install -r ${SKILL_DIR}/requirements.txt"
    fi

    # Check optional API keys
    echo ""
    if [ -n "${GOOGLE_API_KEY:-}" ]; then
        echo "  ✓ GOOGLE_API_KEY detected (image generation ready)"
    else
        echo "  ⚠ GOOGLE_API_KEY not set. Image generation (/ads generate, /ads photoshoot) requires it."
        echo "    Get a key: https://aistudio.google.com/app/apikey"
        echo "    Then add to shell: export GOOGLE_API_KEY=\"your-key\""
    fi

    if [ -n "${META_ACCESS_TOKEN:-}" ]; then
        echo "  ✓ META_ACCESS_TOKEN detected (Meta Ads data fetch ready)"
    else
        echo "  ⚠ META_ACCESS_TOKEN not set. Required for /ads meta and /ads instagram live data."
        echo "    Get token: https://developers.facebook.com/tools/explorer/"
    fi

    if [ -n "${GOOGLE_ADS_DEVELOPER_TOKEN:-}" ]; then
        echo "  ✓ GOOGLE_ADS_DEVELOPER_TOKEN detected (Google Ads ready)"
    else
        echo "  ⚠ GOOGLE_ADS_DEVELOPER_TOKEN not set. Required for /ads google live data."
        echo "    Apply: https://developers.google.com/google-ads/api/docs/get-started/dev-token"
    fi

    echo ""
    echo "✓ Claude Ads installed successfully!"
    echo ""
    echo "  Installed:"
    echo "    • 1 main skill (ads orchestrator)"
    echo "    • $(ls "${HOME}/.claude/skills" | grep "^ads-" | wc -l | tr -d ' ') sub-skills (platform + functional + creative)"
    echo "    • 10 agents (6 audit + 4 creative)"
    echo "    • 25 reference files"
    echo "    • $(ls "${SCRIPTS_DIR}"/*.py 2>/dev/null | wc -l | tr -d ' ') Python scripts"
    echo ""
    echo "Usage:"
    echo "  1. Start Claude Code:  claude"
    echo "  2. Run commands:       /ads audit"
    echo "                         /ads plan saas"
    echo "                         /ads google"
    echo "                         /ads instagram"
    echo "                         /ads budget"
    echo ""
    echo "To uninstall: curl -fsSL ${REPO_URL}/raw/main/uninstall.sh | bash"
    echo "To update:    bash install.sh${LOCAL_MODE:+ --local}"
}

main "$@"
