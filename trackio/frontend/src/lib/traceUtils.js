function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function firstNumber(...values) {
  for (const value of values) {
    const number = finiteNumber(value);
    if (number !== null) return number;
  }
  return null;
}

function parseTimestamp(value) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

function parseJsonValue(value) {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

export function spanDurationMs(span) {
  const explicit = firstNumber(span?.duration_ms, span?.durationMs);
  if (explicit !== null) return Math.max(0, explicit);
  const start = parseTimestamp(span?.start_time || span?.startTime);
  const end = parseTimestamp(span?.end_time || span?.endTime);
  if (start === null || end === null) return null;
  return Math.max(0, end - start);
}

export function spanUsage(span) {
  const usage = span?.usage || {};
  const inputTokens = firstNumber(
    usage.input_tokens,
    usage.prompt_tokens,
    span?.input_tokens,
  );
  const outputTokens = firstNumber(
    usage.output_tokens,
    usage.completion_tokens,
    span?.output_tokens,
  );
  const suppliedTotal = firstNumber(usage.total_tokens, span?.total_tokens);
  const totalTokens =
    suppliedTotal ??
    (inputTokens !== null || outputTokens !== null
      ? (inputTokens || 0) + (outputTokens || 0)
      : null);
  return { inputTokens, outputTokens, totalTokens };
}

export function spanCostUsd(span) {
  return firstNumber(span?.cost_usd, span?.costUsd);
}

function toolResultByCallId(messages) {
  const results = new Map();
  for (const message of messages || []) {
    if (String(message?.role || "").toLowerCase() !== "tool") continue;
    const callId = message.tool_call_id || message.toolCallId;
    if (callId) results.set(String(callId), message);
  }
  return results;
}

export function messageToolSpans(messages) {
  const results = toolResultByCallId(messages);
  const spans = [];
  for (const [messageIndex, message] of (messages || []).entries()) {
    const calls = [...(message?.tool_calls || message?.toolCalls || [])];
    if (message?.function_call) {
      calls.push({ function: message.function_call });
    }
    for (const [callIndex, call] of calls.entries()) {
      const fn = call?.function || call || {};
      const id = String(call?.id || `message-tool-${messageIndex}-${callIndex}`);
      const result = results.get(id);
      spans.push({
        id,
        parent_id: null,
        name: fn.name || call?.name || "tool",
        kind: "tool",
        input: parseJsonValue(fn.arguments ?? call?.arguments ?? null),
        output: parseJsonValue(result?.content ?? null),
        status: result ? (result.isError ? "error" : "success") : null,
        derived_from_messages: true,
      });
    }
  }
  return spans;
}

export function traceSpans(trace) {
  if (Array.isArray(trace?.spans) && trace.spans.length) return trace.spans;
  return messageToolSpans(trace?.messages || []);
}

function normalizedSpan(span, index, usedIds) {
  const requestedId = String(span?.id || `span-${index + 1}`);
  let treeId = requestedId;
  let suffix = 2;
  while (usedIds.has(treeId)) {
    treeId = `${requestedId}-${suffix}`;
    suffix += 1;
  }
  usedIds.add(treeId);
  return {
    ...span,
    id: requestedId,
    _treeId: treeId,
    _index: index,
    parent_id: span?.parent_id ?? span?.parentId ?? null,
    name: span?.name || span?.kind || `Span ${index + 1}`,
    kind: String(span?.kind || "span").toLowerCase(),
  };
}

function compareSpans(left, right) {
  const leftStart = parseTimestamp(left.start_time || left.startTime);
  const rightStart = parseTimestamp(right.start_time || right.startTime);
  if (leftStart !== null && rightStart !== null && leftStart !== rightStart) {
    return leftStart - rightStart;
  }
  return left._index - right._index;
}

export function flattenSpanTree(spans, collapsedIds = new Set()) {
  const usedIds = new Set();
  const normalized = (spans || []).map((span, index) =>
    normalizedSpan(span, index, usedIds),
  );
  const firstByPublicId = new Map();
  for (const span of normalized) {
    if (!firstByPublicId.has(span.id)) firstByPublicId.set(span.id, span);
  }
  const children = new Map(normalized.map((span) => [span._treeId, []]));
  const roots = [];
  for (const span of normalized) {
    const parent = span.parent_id ? firstByPublicId.get(String(span.parent_id)) : null;
    if (!parent || parent._treeId === span._treeId) {
      roots.push(span);
    } else {
      children.get(parent._treeId).push(span);
    }
  }
  roots.sort(compareSpans);
  for (const childSpans of children.values()) childSpans.sort(compareSpans);

  const rows = [];
  const visited = new Set();
  function hideDescendants(span) {
    for (const child of children.get(span._treeId) || []) {
      if (visited.has(child._treeId)) continue;
      visited.add(child._treeId);
      hideDescendants(child);
    }
  }
  function visit(span, depth) {
    if (visited.has(span._treeId)) return;
    visited.add(span._treeId);
    const childSpans = children.get(span._treeId) || [];
    rows.push({ ...span, depth, hasChildren: childSpans.length > 0 });
    if (collapsedIds.has(span._treeId)) {
      hideDescendants(span);
      return;
    }
    for (const child of childSpans) visit(child, depth + 1);
  }
  for (const root of roots) visit(root, 0);
  for (const span of normalized) visit(span, 0);
  return rows;
}

export function traceSummary(trace) {
  const spans = traceSpans(trace);
  let earliest = null;
  let latest = null;
  let costUsd = 0;
  let hasCost = false;
  let inputTokens = 0;
  let outputTokens = 0;
  let totalTokens = 0;
  let hasUsage = false;
  let hasError = false;
  let maxDurationMs = null;

  for (const span of spans) {
    const start = parseTimestamp(span?.start_time || span?.startTime);
    const end = parseTimestamp(span?.end_time || span?.endTime);
    if (start !== null) earliest = earliest === null ? start : Math.min(earliest, start);
    if (end !== null) latest = latest === null ? end : Math.max(latest, end);
    const duration = spanDurationMs(span);
    if (duration !== null) {
      maxDurationMs =
        maxDurationMs === null ? duration : Math.max(maxDurationMs, duration);
    }
    const cost = spanCostUsd(span);
    if (cost !== null) {
      costUsd += cost;
      hasCost = true;
    }
    const usage = spanUsage(span);
    if (usage.totalTokens !== null) {
      inputTokens += usage.inputTokens || 0;
      outputTokens += usage.outputTokens || 0;
      totalTokens += usage.totalTokens;
      hasUsage = true;
    }
    if (
      ["error", "failed"].includes(String(span?.status || "").toLowerCase()) ||
      span?.error
    ) {
      hasError = true;
    }
  }

  const metadata = trace?.metadata || {};
  const derivedDuration =
    earliest !== null && latest !== null ? Math.max(0, latest - earliest) : null;
  const durationMs =
    derivedDuration ??
    maxDurationMs ??
    firstNumber(metadata.duration_ms, metadata.latency_ms);
  const metadataCost = firstNumber(metadata.cost_usd);
  const allSucceeded =
    spans.length > 0 &&
    spans.every((span) => String(span?.status || "").toLowerCase() === "success");
  const status = hasError
    ? "error"
    : metadata.status || (allSucceeded ? "success" : null);

  return {
    durationMs,
    costUsd: hasCost ? costUsd : metadataCost,
    inputTokens: hasUsage ? inputTokens : null,
    outputTokens: hasUsage ? outputTokens : null,
    totalTokens: hasUsage ? totalTokens : null,
    status,
    spanCount: spans.length,
  };
}

export function formatDuration(ms) {
  const value = finiteNumber(ms);
  if (value === null) return "—";
  if (value < 1) return `${Math.round(value * 1000)}µs`;
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatCost(cost) {
  const value = finiteNumber(cost);
  if (value === null) return "—";
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokens(tokens) {
  const value = finiteNumber(tokens);
  return value === null ? "—" : Math.round(value).toLocaleString();
}
