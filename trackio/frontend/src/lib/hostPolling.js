let rateLimitCooldownUntil = 0;

export function isHfSpaceHost() {
  if (typeof window === "undefined") return false;
  return (window.location.hostname || "")
    .toLowerCase()
    .endsWith(".hf.space");
}

export function registerRateLimitHit() {
  const until = Date.now() + 12000;
  rateLimitCooldownUntil = Math.max(rateLimitCooldownUntil, until);
}

export function isRateLimitCooldownActive() {
  return Date.now() < rateLimitCooldownUntil;
}

export function getAppPollIntervalMs() {
  return isHfSpaceHost() ? 2500 : 1000;
}

export function getMetricsPollIntervalMs() {
  return isHfSpaceHost() ? 3500 : 1000;
}

export function isTabHidden() {
  return typeof document !== "undefined" && document.hidden;
}
