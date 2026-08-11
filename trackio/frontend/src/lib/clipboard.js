/**
 * Copies text to the clipboard, falling back to a hidden textarea with
 * `document.execCommand("copy")` where the async Clipboard API is
 * unavailable or rejects.
 * @param {string} value
 * @returns {Promise<boolean>} whether the copy succeeded
 */
export async function copyTextToClipboard(value) {
  if (typeof value !== "string" || value === "") {
    return false;
  }
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      try {
        return document.execCommand("copy");
      } finally {
        document.body.removeChild(textarea);
      }
    } catch {
      return false;
    }
  }
}
