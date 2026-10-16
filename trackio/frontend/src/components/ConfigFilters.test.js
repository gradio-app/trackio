import { expect, it, vi } from "vitest";
import { mount, tick, unmount } from "svelte";
import ConfigFilters from "./ConfigFilters.svelte";
import ConfigFiltersTestHarness from "./ConfigFiltersTestHarness.svelte";
import { configFilterKeys } from "../lib/runFilters.js";
vi.mock("../lib/runFilters.js", async (importOriginal) => {
  const original = await importOriginal();
  return { ...original, configFilterKeys: vi.fn(original.configFilterKeys) };
});

it("applies draft groups, preserves active filters on cancel, and clears the summary", async () => {
  const target = document.createElement("div");
  document.body.appendChild(target);
  const component = mount(ConfigFilters, { target, props: { configs: { a: { batch_size: 32 } }, matchCount: 0 } });
  await tick();
  const dialog = target.querySelector("dialog");
  dialog.showModal = vi.fn(() => { dialog.open = true; });
  dialog.close = vi.fn(() => { dialog.open = false; });
  const click = async (text) => {
    [...target.querySelectorAll("button")].find((button) => button.textContent === text).click();
    await tick();
  };
  const setRule = async (index, value) => {
    const select = target.querySelectorAll('[aria-label="Configuration key"]')[index];
    select.value = '["batch_size"]';
    select.dispatchEvent(new Event("change"));
    const input = target.querySelectorAll("input")[index];
    input.value = value;
    input.dispatchEvent(new Event("input"));
    await tick();
  };
  try {
    expect(dialog.open).toBe(false);
    await click("Config filters");
    await click("+ Add filter");
    await setRule(0, "32");
    await click("+ AND");
    await setRule(1, "64");
    await click("+ OR group");
    await setRule(2, "128");
    expect(target.querySelector(".active-filters")).toBeNull();
    await click("Apply filters");
    expect(dialog.open).toBe(false);
    expect(target.querySelector(".active-filters").textContent).toContain('AND batch_size = "64"');
    expect(target.querySelector(".active-filters").textContent).toContain('OR');
    expect(target.querySelector('[role="status"]').textContent).toContain("No runs match");
    await click("Config filters (3)");
    await setRule(0, "999");
    await click("Cancel");
    expect(target.querySelector(".active-filters").textContent).not.toContain("999");
    await click("Config filters (3)");
    expect(target.querySelector("input").value).toBe("32");
    await click("×");
    await click("Config filters (3)");
    target.querySelector('[aria-label="Remove condition"]').click();
    await tick();
    await click("Apply filters");
    expect(target.querySelector(".filter-heading").textContent).toContain("(2)");
    await click("Clear");
    expect(target.querySelector(".active-filters")).toBeNull();
    expect(target.querySelector('[role="status"]')).toBeNull();
  } finally {
    await unmount(component);
    target.remove();
  }
});

it("does not rediscover keys on polls after Apply, Cancel, or Escape", async () => {
  const target = document.createElement("div");
  document.body.appendChild(target);
  const component = mount(ConfigFiltersTestHarness, { target });
  await tick();
  const dialog = target.querySelector("dialog");
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; dialog.dispatchEvent(new Event("close")); };
  const click = async (text) => {
    [...target.querySelectorAll("button")].find((button) => button.textContent === text).click();
    await tick();
  };
  try {
    for (const action of ["Apply filters", "Cancel", "Escape"]) {
      await click("Config filters");
      await click("+ Add filter");
      expect(target.querySelectorAll("option").length).toBeGreaterThan(0);
      if (action === "Escape") { dialog.close(); await tick(); }
      else await click(action);
      configFilterKeys.mockClear();
      await click("Poll configs");
      expect(configFilterKeys).not.toHaveBeenCalled();
      expect(target.querySelectorAll("option")).toHaveLength(0);
    }
  } finally {
    await unmount(component);
    target.remove();
  }
});
