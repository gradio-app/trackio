const WRITE_TOKEN_KEY = "trackio_write_token";

function setWriteTokenCookie(token) {
  const maxAge = token ? 60 * 60 * 24 * 7 : 0;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `trackio_write_token=${encodeURIComponent(token)}; path=/; max-age=${maxAge}; SameSite=Lax${secure}`;
}

export function getSavedWriteToken() {
  try {
    return localStorage.getItem(WRITE_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function saveWriteToken(token) {
  try {
    if (token) localStorage.setItem(WRITE_TOKEN_KEY, token);
    else localStorage.removeItem(WRITE_TOKEN_KEY);
  } catch {}
  setWriteTokenCookie(token);
}

export function applyUrlTokens() {
  const params = new URLSearchParams(window.location.search);
  let changed = false;
  const writeToken = params.get("write_token");
  if (writeToken) {
    saveWriteToken(writeToken);
    params.delete("write_token");
    changed = true;
  } else {
    const savedToken = getSavedWriteToken();
    if (savedToken) setWriteTokenCookie(savedToken);
  }
  const oauthSession = params.get("oauth_session");
  if (oauthSession) {
    sessionStorage.setItem("trackio_oauth_session", oauthSession);
    params.delete("oauth_session");
    changed = true;
  }
  if (changed) {
    const query = params.toString();
    const path = window.location.pathname + (query ? `?${query}` : "");
    window.history.replaceState({}, "", path);
  }
}
