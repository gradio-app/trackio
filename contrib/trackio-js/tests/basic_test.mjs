import test from "node:test";
import assert from "node:assert/strict";
import { Client } from "../dist/index.js"; // or src with ts-node if you prefer

test("constructs with defaults", () => {
  const c = new Client();
  assert.ok(c);
});

test("flush with empty buffer is no-op", async () => {
  const c = new Client();
  await c.flush(); // should not throw
});