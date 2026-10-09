import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, tick } from "svelte";
import Runs from "./Runs.svelte";
import RunsTestHarness from "./RunsTestHarness.svelte";
import { deleteRun, getProjectSummary, getRunSummary, getRunArtifactCounts } from "../lib/api.js";

vi.mock("../lib/api.js", () => ({
  deleteRun: vi.fn(),
  getProjectSummary: vi.fn(),
  getRunSummary: vi.fn(),
  getRunArtifactCounts: vi.fn(),
  renameRun: vi.fn(),
}));

let component;
let target;
let records;
const selectAll = () => target.querySelector('[aria-label="Select all visible runs"]');
const rows = () => [...target.querySelectorAll('tbody input[type="checkbox"]')];
const deleteButton = () => target.querySelector(".bulk-delete");

async function render(props = {}) {
  component = mount(Runs, { target, props: { project: "demo", ...props } });
  await vi.waitFor(() => expect(rows()).toHaveLength(records.length));
}

async function click(element) {
  element.click();
  await tick();
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("confirm", vi.fn(() => true));
  target = document.createElement("div");
  document.body.appendChild(target);
  records = [{ id: "a", name: "same" }, { id: "b", name: "same" }, { id: "c", name: "control" }];
  getProjectSummary.mockImplementation(async () => ({ runs: [...records] }));
  getRunSummary.mockResolvedValue({ num_logs: 3, last_step: 2 });
  getRunArtifactCounts.mockResolvedValue([]);
  deleteRun.mockImplementation(async (_project, run) => {
    records = records.filter((record) => record.id !== run.id);
    return true;
  });
});

afterEach(async () => {
  if (component) await unmount(component);
  component = null;
  target.remove();
  vi.unstubAllGlobals();
});

describe("bulk run deletion", () => {
  it("selects all, clears all, and identifies duplicate names by id", async () => {
    const onRunsChanged = vi.fn();
    await render({ onRunsChanged });
    expect(deleteButton().disabled).toBe(true);
    await click(selectAll());
    expect(rows().every((row) => row.checked)).toBe(true);
    await click(selectAll());
    expect(rows().some((row) => row.checked)).toBe(false);
    await click(rows()[0]);
    expect(selectAll().indeterminate).toBe(true);
    await click(deleteButton());
    await vi.waitFor(() => expect(onRunsChanged).toHaveBeenCalledOnce());
    expect(deleteRun).toHaveBeenCalledOnce();
    expect(deleteRun.mock.calls[0][1].id).toBe("a");
    expect(records.map((run) => run.id)).toEqual(["b", "c"]);
  });

  it("deletes only filtered rows with a single confirmation", async () => {
    component = mount(Runs, { target, props: { project: "demo", filterText: "same" } });
    await vi.waitFor(() => expect(rows()).toHaveLength(2));
    await click(selectAll());
    await click(deleteButton());
    await vi.waitFor(() => expect(deleteRun).toHaveBeenCalledTimes(2));
    expect(confirm).toHaveBeenCalledExactlyOnceWith("Delete 2 selected runs? This cannot be undone.");
    expect(records).toEqual([{ id: "c", name: "control" }]);
  });

  it("cancels without deleting or clearing selection", async () => {
    confirm.mockReturnValue(false);
    await render();
    await click(selectAll());
    await click(deleteButton());
    expect(deleteRun).not.toHaveBeenCalled();
    expect(rows().every((row) => row.checked)).toBe(true);
  });

  it("disables mutations while deleting and reports partial failures", async () => {
    let complete;
    deleteRun.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    deleteRun.mockResolvedValueOnce(false);
    deleteRun.mockRejectedValueOnce(new Error("unavailable"));
    const onRunsChanged = vi.fn();
    await render({ onRunsChanged });
    await click(selectAll());
    await click(deleteButton());
    expect(deleteButton().disabled).toBe(true);
    expect(rows().every((row) => row.disabled)).toBe(true);
    complete(true);
    await vi.waitFor(() => expect(onRunsChanged).toHaveBeenCalledOnce());
    expect(target.querySelector('[role="alert"]').textContent).toContain("Could not delete 2 of 3 runs");
    expect(rows().map((row) => row.checked)).toEqual([false, true, true]);
    expect(deleteButton().disabled).toBe(false);
  });

  it("excludes previously selected rows hidden by a changed filter", async () => {
    component = mount(RunsTestHarness, { target });
    await vi.waitFor(() => expect(rows()).toHaveLength(3));
    await click(selectAll());
    await click([...target.querySelectorAll("button")].find((button) => button.textContent === "Filter control"));
    expect(rows()).toHaveLength(1);
    await click(deleteButton());
    await vi.waitFor(() => expect(deleteRun).toHaveBeenCalledOnce());
    expect(deleteRun.mock.calls[0][1].id).toBe("c");
  });

  it("keeps an in-flight batch in its original project and clears the new selection", async () => {
    let complete;
    deleteRun.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    const onRunsChanged = vi.fn();
    component = mount(RunsTestHarness, { target, props: { onRunsChanged } });
    await vi.waitFor(() => expect(rows()).toHaveLength(3));
    await click(selectAll());
    await click(deleteButton());
    await click([...target.querySelectorAll("button")].find((button) => button.textContent === "Switch project"));
    await vi.waitFor(() => expect(rows()).toHaveLength(3));
    expect(rows().some((row) => row.checked)).toBe(false);
    complete(true);
    await vi.waitFor(() => expect(deleteRun).toHaveBeenCalledTimes(3));
    expect(deleteRun.mock.calls.every(([project]) => project === "demo")).toBe(true);
    expect(onRunsChanged).not.toHaveBeenCalled();
  });

  it("respects read-only access", async () => {
    await render({ runMutationAllowed: false });
    expect(selectAll().disabled).toBe(true);
    expect(rows().every((row) => row.disabled)).toBe(true);
    await click(deleteButton());
    expect(confirm).not.toHaveBeenCalled();
    expect(deleteRun).not.toHaveBeenCalled();
  });
});
