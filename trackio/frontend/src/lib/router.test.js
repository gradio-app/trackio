import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { getPageFromPath, navigateTo } from "./router.js";

function setLocation(pathname, search = "") {
  globalThis.window.location = { pathname, search };
}

beforeEach(() => {
  globalThis.PopStateEvent = class PopStateEvent {
    constructor(type) {
      this.type = type;
    }
  };
  globalThis.window = {
    location: { pathname: "/", search: "" },
    history: {
      pushState(_state, _title, url) {
        const [pathname, search = ""] = url.split("?");
        globalThis.window.location = { pathname, search: search ? `?${search}` : "" };
      },
    },
    dispatchEvent() {},
    __trackio_base: "",
  };
});

afterEach(() => {
  delete globalThis.window;
  delete globalThis.PopStateEvent;
});

describe("getPageFromPath without a base prefix", () => {
  test("maps root and known segments to their pages", () => {
    setLocation("/");
    expect(getPageFromPath()).toBe("metrics");
    setLocation("/traces");
    expect(getPageFromPath()).toBe("traces");
    setLocation("/system");
    expect(getPageFromPath()).toBe("system");
  });

  test("falls back to metrics for unknown segments", () => {
    setLocation("/something-unknown");
    expect(getPageFromPath()).toBe("metrics");
  });
});

describe("getPageFromPath with a base prefix", () => {
  test("strips the base before resolving the page", () => {
    globalThis.window.__trackio_base = "/dashboard";
    setLocation("/dashboard");
    expect(getPageFromPath()).toBe("metrics");
    setLocation("/dashboard/traces");
    expect(getPageFromPath()).toBe("traces");
    setLocation("/dashboard/system");
    expect(getPageFromPath()).toBe("system");
  });
});

describe("navigateTo", () => {
  test("without a base prefix pushes a root-relative path", () => {
    setLocation("/");
    navigateTo("traces");
    expect(globalThis.window.location.pathname).toBe("/traces");
  });

  test("with a base prefix pushes a prefixed path", () => {
    globalThis.window.__trackio_base = "/dashboard";
    setLocation("/dashboard");
    navigateTo("traces");
    expect(globalThis.window.location.pathname).toBe("/dashboard/traces");
    expect(getPageFromPath()).toBe("traces");
  });

  test("preserves existing query params", () => {
    globalThis.window.__trackio_base = "/dashboard";
    setLocation("/dashboard", "?project=demo");
    navigateTo("runs");
    expect(globalThis.window.location.pathname).toBe("/dashboard/runs");
    expect(globalThis.window.location.search).toBe("?project=demo");
  });
});
