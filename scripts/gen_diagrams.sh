#!/usr/bin/env bash
#
# Render every Mermaid source in docs/diagrams/ to PNG.
#
# The .mmd files are the source of truth. The same content is embedded inline in
# hld.md and architecture.md so GitHub renders it without a build step; these PNGs
# exist because Submission_and_Evaluation_Guidelines.md §3 requires a committed
# docs/architecture-diagram.png.
#
# Requires: npm install -g @mermaid-js/mermaid-cli
#
# Re-running this script must produce no git diff. That is the check that the
# committed images match their sources.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAGRAM_DIR="$REPO_ROOT/docs/diagrams"
DOCS_DIR="$REPO_ROOT/docs"

if ! command -v mmdc >/dev/null 2>&1; then
    echo "error: mmdc not found. Install with:" >&2
    echo "  npm install -g @mermaid-js/mermaid-cli" >&2
    exit 1
fi

# CI runs as root in a container, where Chromium refuses to start without this.
PUPPETEER_CONFIG="$REPO_ROOT/scripts/puppeteer-config.json"
MMDC_ARGS=(--backgroundColor transparent --puppeteerConfigFile "$PUPPETEER_CONFIG")

render() {
    local src="$1" out="$2"
    echo "  $(basename "$src") -> ${out#"$REPO_ROOT/"}"
    mmdc --input "$src" --output "$out" "${MMDC_ARGS[@]}"
}

echo "Rendering Mermaid diagrams..."

# The primary architecture diagram lands at the path the guidelines mandate.
render "$DIAGRAM_DIR/architecture-diagram.mmd" "$DOCS_DIR/architecture-diagram.png"

# Everything else renders alongside its source.
for src in "$DIAGRAM_DIR"/*.mmd; do
    [ "$(basename "$src")" = "architecture-diagram.mmd" ] && continue
    render "$src" "${src%.mmd}.png"
done

echo "Done."
