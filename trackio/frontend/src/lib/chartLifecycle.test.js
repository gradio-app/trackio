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

  test("finalizes a stale render that finishes after a newer render", async () => {
    const manager = createVegaViewManager();
    const slow = deferred();
    const stale = fakeResult();
    const latest = fakeResult();

    const slowReplace = manager.replace(() => slow.promise);
    await manager.replace(async () => latest);
    slow.resolve(stale);

    expect(await slowReplace).toBeNull();
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

  test("does not clear a newer render that shares a stale render's element", async () => {
    const manager = createVegaViewManager();
    const slow = deferred();
    const stale = fakeResult();
    const latest = fakeResult();
    const element = { replaceChildren: vi.fn() };

    const slowReplace = manager.replace(() => slow.promise, element);
    await manager.replace(async () => latest, element);
    slow.resolve(stale);
    await slowReplace;

    expect(stale.view.finalize).toHaveBeenCalledOnce();
    expect(element.replaceChildren).not.toHaveBeenCalled();
    expect(manager.current).toBe(latest.view);
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
