import { afterEach, describe, expect, test, vi } from "vitest";
import {
  createVegaViewManager,
  observeNearViewport,
} from "./chartLifecycle.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function fakeResult() {
  return { view: { finalize: vi.fn() } };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createVegaViewManager", () => {
  test("finalizes the previous view when replacing it", async () => {
    const manager = createVegaViewManager();
    const first = fakeResult();
    const second = fakeResult();

    await manager.replace(async () => first);
    await manager.replace(async () => second);

    expect(first.view.finalize).toHaveBeenCalledOnce();
    expect(second.view.finalize).not.toHaveBeenCalled();
    expect(manager.current).toBe(second.view);
  });

  test("waits for an active render before starting its replacement", async () => {
    const manager = createVegaViewManager();
    const slow = deferred();
    const stale = fakeResult();
    const latest = fakeResult();
    const createLatest = vi.fn(async () => latest);

    const slowReplace = manager.replace(() => slow.promise);
    const latestReplace = manager.replace(createLatest);

    expect(createLatest).not.toHaveBeenCalled();
    slow.resolve(stale);

    expect(await slowReplace).toBeNull();
    expect(await latestReplace).toBe(latest);
    expect(createLatest).toHaveBeenCalledOnce();
    expect(stale.view.finalize).toHaveBeenCalledOnce();
    expect(latest.view.finalize).not.toHaveBeenCalled();
    expect(manager.current).toBe(latest.view);
  });

  test("finalizes an in-flight render after the manager is cleared", async () => {
    const manager = createVegaViewManager();
    const pending = deferred();
    const stale = fakeResult();

    const replacement = manager.replace(() => pending.promise);
    manager.clear();
    pending.resolve(stale);

    expect(await replacement).toBeNull();
    expect(stale.view.finalize).toHaveBeenCalledOnce();
    expect(manager.current).toBeNull();
  });

  test("removes the canvas from the active chart when clearing it", async () => {
    const manager = createVegaViewManager();
    const result = fakeResult();
    const element = { replaceChildren: vi.fn() };

    await manager.replace(async () => result, element);
    manager.clear();

    expect(result.view.finalize).toHaveBeenCalledOnce();
    expect(element.replaceChildren).toHaveBeenCalledOnce();
  });

  test("keeps only the newest queued replacement", async () => {
    const manager = createVegaViewManager();
    const slow = deferred();
    const stale = fakeResult();
    const middle = fakeResult();
    const latest = fakeResult();
    const createMiddle = vi.fn(async () => middle);
    const createLatest = vi.fn(async () => latest);

    const slowReplace = manager.replace(() => slow.promise);
    const middleReplace = manager.replace(createMiddle);
    const latestReplace = manager.replace(createLatest);

    expect(await middleReplace).toBeNull();
    expect(createMiddle).not.toHaveBeenCalled();
    slow.resolve(stale);

    expect(await slowReplace).toBeNull();
    expect(await latestReplace).toBe(latest);
    expect(stale.view.finalize).toHaveBeenCalledOnce();
    expect(middle.view.finalize).not.toHaveBeenCalled();
    expect(createLatest).toHaveBeenCalledOnce();
    expect(manager.current).toBe(latest.view);
  });

  test("preserves chart height while its canvas is cleared", async () => {
    const manager = createVegaViewManager();
    const result = fakeResult();
    const removeProperty = vi.fn(function () {
      this.height = "";
    });
    const element = {
      getBoundingClientRect: () => ({ height: 312 }),
      replaceChildren: vi.fn(),
      style: { height: "", removeProperty },
    };

    await manager.replace(async () => result, element);
    manager.clear();

    expect(element.style.height).toBe("312px");

    const replacement = fakeResult();
    await manager.replace(async () => replacement, element);

    expect(element.style.height).toBe("");
    expect(removeProperty).toHaveBeenCalledTimes(2);
  });

  test("does not start new renders after teardown", async () => {
    const manager = createVegaViewManager();
    const result = fakeResult();
    const create = vi.fn(async () => result);

    await manager.replace(create);
    manager.destroy();

    expect(result.view.finalize).toHaveBeenCalledOnce();
    expect(await manager.replace(create)).toBeNull();
    expect(create).toHaveBeenCalledOnce();
  });
});

describe("observeNearViewport", () => {
  test("reports intersections and disconnects the observer", () => {
    let callback;
    const observe = vi.fn();
    const disconnect = vi.fn();
    const IntersectionObserverMock = vi.fn((next) => {
      callback = next;
      return { observe, disconnect };
    });
    vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);
    const onChange = vi.fn();
    const element = {};

    const cleanup = observeNearViewport(element, onChange);
    callback([{ isIntersecting: true }]);
    callback([{ isIntersecting: false }]);
    cleanup();

    expect(IntersectionObserverMock).toHaveBeenCalledWith(expect.any(Function), {
      rootMargin: "600px 0px",
    });
    expect(observe).toHaveBeenCalledWith(element);
    expect(onChange).toHaveBeenNthCalledWith(1, true);
    expect(onChange).toHaveBeenNthCalledWith(2, false);
    expect(disconnect).toHaveBeenCalledOnce();
  });

  test("renders eagerly when IntersectionObserver is unavailable", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const onChange = vi.fn();

    observeNearViewport({}, onChange)();

    expect(onChange).toHaveBeenCalledWith(true);
  });
});
