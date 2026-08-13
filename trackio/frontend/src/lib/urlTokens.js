export function applyUrlTokens() {
  const params = new URLSearchParams(window.location.search);
  let changed = false;
  const writeToken = params.get("write_token");
  if (writeToken) {
    const maxAge = 60 * 60 * 24 * 7;
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `trackio_write_token=${encodeURIComponent(writeToken)}; path=/; max-age=${maxAge}; SameSite=Lax${secure}`;
    params.delete("write_token");
    changed = true;
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
