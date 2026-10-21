"""Build one runtime-loader-compatible JS file; SDK/React stay external."""
from pathlib import Path
root = Path(__file__).parent
core = (root/'source-bridge.mjs').read_text().replace('export function createSourceBridge', 'function createSourceBridge',1)
entry = (root/'plugin.entry.js').read_text()
(root/'plugin.js').write_text(entry.replace('/* INLINE_SOURCE_BRIDGE */',core))
