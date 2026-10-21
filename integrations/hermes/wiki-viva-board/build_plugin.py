"""Build one runtime-loader-compatible JS file; SDK/React stay external."""
from pathlib import Path
root = Path(__file__).parent
native = (root/'native-session.mjs').read_text().replace('export function createNativeSessionAccess', 'function createNativeSessionAccess',1)
core = (root/'source-bridge.mjs').read_text().replace("import {createNativeSessionAccess} from './native-session.mjs';\n",'').replace('export function createSourceBridge', 'function createSourceBridge',1)
core = native + '\n' + core
entry = (root/'plugin.entry.js').read_text()
(root/'plugin.js').write_text(entry.replace('/* INLINE_SOURCE_BRIDGE */',core))
