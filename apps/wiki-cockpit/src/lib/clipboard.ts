// One clipboard primitive for every "Copy" button in the cockpit. Tries the
// async clipboard API first, then falls back to a hidden textarea +
// execCommand for environments where the API is missing or blocked
// (plain http, permission denied). Returns whether the text made it out —
// callers decide what feedback (if any) to show.
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fall through to the legacy path.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
