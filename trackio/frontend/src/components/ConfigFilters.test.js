import { expect, it } from "vitest";
import { mount, tick, unmount } from "svelte";
import ConfigFilters from "./ConfigFilters.svelte";

it("builds and removes AND/OR conditions in a collapsed control", async () => {
  const target = document.createElement("div");
  document.body.appendChild(target);
  const component = mount(ConfigFilters, { target, props: { configs: { a: { batch_size: 32 } } } });
  const click = async (text) => {
    [...target.querySelectorAll("button")].find((button) => button.textContent === text).click();
    await tick();
  };
  try {
    expect(target.querySelector("details").open).toBe(false);
    await click("+ Add filter");
    const select = target.querySelector("select");
    select.value = '["batch_size"]';
    select.dispatchEvent(new Event("change"));
    await tick();
    expect(target.querySelector("summary").textContent).toContain("(1)");
    await click("+ AND");
    await click("+ OR group");
    expect(target.querySelectorAll("input")).toHaveLength(3);
    expect([...target.querySelectorAll(".join")].map((el) => el.textContent)).toEqual(["AND", "OR"]);
    await click("×");
    expect(target.querySelectorAll("input")).toHaveLength(2);
    await click("Clear");
    expect(target.querySelectorAll("input")).toHaveLength(0);
  } finally {
    await unmount(component);
    target.remove();
  }
});
