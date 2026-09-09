import { afterEach, describe, expect, test, vi } from "vitest";
import { createPollingTask } from "./hostPolling.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function waitForAbort(signal) {
  return new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason));
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("createPollingTask", () => {
  test("does not overlap polling tasks", async () => {
    const pollingTask = createPollingTask();
    const pending = deferred();
    const task = vi.fn(() => pending.promise);

    const first = pollingTask.run(task);

    expect(await pollingTask.run(task)).toBe(false);
    expect(task).toHaveBeenCalledOnce();

    pending.resolve();

    expect(await first).toBe(true);
    expect(await pollingTask.run(async () => {})).toBe(true);
  });

  test("aborts a polling task after its timeout", async () => {
    vi.useFakeTimers();
    const pollingTask = createPollingTask(1000);
    const run = pollingTask.run(waitForAbort);
    const aborted = expect(run).rejects.toMatchObject({ name: "AbortError" });

    await vi.advanceTimersByTimeAsync(1000);

    await aborted;
    expect(await pollingTask.run(async () => {})).toBe(true);
  });

  test("cancels an active polling task", async () => {
    const pollingTask = createPollingTask();
    const run = pollingTask.run(waitForAbort);
    const aborted = expect(run).rejects.toMatchObject({ name: "AbortError" });

    pollingTask.cancel();

    await aborted;
  });
});
