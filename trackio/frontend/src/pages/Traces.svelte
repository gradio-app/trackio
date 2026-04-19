<script>
  let {
    project = null,
    selectedRuns = [],
    traceModel = $bindable("All models"),
    traceMinReward = $bindable(0),
  } = $props();

  const baseTraces = [
    {
      id: "tr-aa42e8eb647e",
      request: "What is the capital of Australia?",
      preview: "The capital of Australia is Sydney.",
      step: 2000,
      reward: 0.08,
      modelVersion: "step-2000",
      state: "Error",
      timestamp: "19 hours ago",
      latency: "0.001s",
      groupId: "g-42",
      messages: [
        { role: "system", content: "Answer directly and avoid unsupported claims." },
        { role: "user", content: "What is the capital of Australia?" },
        { role: "assistant", content: "The capital of Australia is Sydney." },
      ],
    },
    {
      id: "tr-43c40a48387b",
      request: "What is 17 * 19?",
      preview: "17 * 19 = 17 * 20 - 17 = 340 - 17 = 323.",
      step: 1800,
      reward: 0.12,
      modelVersion: "step-1800",
      state: "Error",
      timestamp: "19 hours ago",
      latency: "0.002s",
      groupId: "g-17",
      messages: [
        { role: "system", content: "You are a concise math tutor. Show the reasoning cleanly." },
        { role: "user", content: "What is 17 * 19?" },
        { role: "assistant", content: "17 * 19 = 17 * 20 - 17 = 340 - 17 = 323." },
      ],
    },
    {
      id: "tr-f9344cacf94b",
      request: "How many minutes are in 3.5 days?",
      preview: "There are 5,040 minutes in 3.5 days.",
      step: 2000,
      reward: 0.31,
      modelVersion: "step-2000",
      state: "Success",
      timestamp: "19 hours ago",
      latency: "0.001s",
      groupId: "g-17",
      messages: [
        { role: "system", content: "Route calculations through the calculator tool when possible." },
        { role: "user", content: "How many minutes are in 3.5 days?" },
        { role: "tool", content: "calculator(days=3.5, unit='minutes') -> 5040" },
        { role: "assistant", content: "There are 5,040 minutes in 3.5 days." },
      ],
    },
    {
      id: "tr-c819cdf800a9",
      request: "What is the capital of Australia?",
      preview: "The capital of Australia is Canberra.",
      step: 2150,
      reward: 0.91,
      modelVersion: "step-2150",
      state: "Success",
      timestamp: "19 hours ago",
      latency: "0.001s",
      groupId: "g-42",
      messages: [
        { role: "system", content: "Answer directly and avoid unsupported claims." },
        { role: "user", content: "What is the capital of Australia?" },
        { role: "assistant", content: "The capital of Australia is Canberra." },
      ],
    },
    {
      id: "tr-8f397c1eeeda",
      request: "Write a Fibonacci function",
      preview: "def fib(n): seq = [] ... return seq",
      step: 2300,
      reward: 0.77,
      modelVersion: "step-2300",
      state: "Success",
      timestamp: "19 hours ago",
      latency: "0.002s",
      groupId: "g-98",
      messages: [
        { role: "system", content: "Return runnable Python when the user asks for code." },
        { role: "user", content: "Write a function that returns the Fibonacci sequence up to n." },
        {
          role: "assistant",
          content:
            "def fib(n):\n    seq = []\n    a, b = 0, 1\n    while a <= n:\n        seq.append(a)\n        a, b = b, a + b\n    return seq",
        },
      ],
    },
    {
      id: "tr-eabe8cb67dad",
      request: "Explain why leaves change color in the fall.",
      preview: "Leaves change color because chlorophyll breaks down as daylight shortens...",
      step: 2450,
      reward: 0.24,
      modelVersion: "step-2450",
      state: "Error",
      timestamp: "19 hours ago",
      latency: "0.001s",
      groupId: "g-98",
      messages: [
        { role: "system", content: "Answer in one sentence only." },
        { role: "user", content: "Explain why leaves change color in the fall." },
        {
          role: "assistant",
          content:
            "Leaves change color because chlorophyll breaks down as daylight shortens, revealing pigments like carotenoids and anthocyanins, and this process also depends on sugar levels, temperature swings, and species-specific chemistry.",
        },
      ],
    },
    {
      id: "tr-5b2efd0671bd",
      request: "Explain why leaves change color in the fall.",
      preview: "Leaves change color in fall because chlorophyll fades and other pigments become visible.",
      step: 2600,
      reward: 0.88,
      modelVersion: "step-2600",
      state: "Success",
      timestamp: "19 hours ago",
      latency: "0.001s",
      groupId: "g-98",
      messages: [
        { role: "system", content: "Answer in one sentence only." },
        { role: "user", content: "Explain why leaves change color in the fall." },
        {
          role: "assistant",
          content: "Leaves change color in fall because chlorophyll fades and other pigments become visible.",
        },
      ],
    },
    {
      id: "tr-91ecf34c9812",
      request: "Summarize the launch checklist for a model evaluation run.",
      preview: "- Freeze the dataset snapshot - Record the model and prompt version ...",
      step: 2800,
      reward: 0.95,
      modelVersion: "step-2800",
      state: "Success",
      timestamp: "19 hours ago",
      latency: "0.002s",
      groupId: "g-121",
      messages: [
        { role: "system", content: "Use markdown bullets when summarizing requirements." },
        { role: "user", content: "Summarize the launch checklist for a model evaluation run." },
        {
          role: "assistant",
          content:
            "- Freeze the dataset snapshot\n- Record the model and prompt version\n- Verify scoring scripts\n- Store outputs and metrics for review",
        },
      ],
    },
  ];

  let search = $state("");
  let sortBy = $state("request-time");
  let expandedTraceId = $state(null);

  let activeRunLabel = $derived(
    selectedRuns.length > 0 ? selectedRuns[0].name : "search_traces_test"
  );

  let traces = $derived(baseTraces.map((trace) => ({ ...trace, run: activeRunLabel })));

  let filteredTraces = $derived.by(() => {
    const needle = search.trim().toLowerCase();
    const matches = traces.filter((trace) => {
      const matchesModel =
        traceModel === "All models" || trace.modelVersion === traceModel;
      const matchesReward = trace.reward >= traceMinReward;
      const haystack = [
        trace.id,
        trace.request,
        trace.preview,
        trace.modelVersion,
        trace.state,
        trace.run,
        ...trace.messages.map((message) => message.content),
      ]
        .join(" ")
        .toLowerCase();
      return matchesModel && matchesReward && (!needle || haystack.includes(needle));
    });

    return matches.sort((left, right) => {
      switch (sortBy) {
        case "reward-asc":
          return left.reward - right.reward;
        case "reward-desc":
          return right.reward - left.reward;
        case "step-asc":
          return left.step - right.step;
        case "step-desc":
          return right.step - left.step;
        case "request-time":
        default:
          return right.step - left.step;
      }
    });
  });

  $effect(() => {
    filteredTraces;
    if (expandedTraceId && !filteredTraces.find((trace) => trace.id === expandedTraceId)) {
      expandedTraceId = null;
    }
  });

  function toggleTrace(traceId) {
    expandedTraceId = expandedTraceId === traceId ? null : traceId;
  }

  function stateClass(state) {
    return state.toLowerCase() === "error" ? "error" : "success";
  }
</script>

<div class="traces-page">
  <div class="toolbar">
    <div class="search-wrap">
      <input type="text" bind:value={search} placeholder="Search traces by request" />
    </div>

    <label class="sort-wrap">
      <span>Sort:</span>
      <select bind:value={sortBy}>
        <option value="request-time">Request time</option>
        <option value="step-desc">Step descending</option>
        <option value="step-asc">Step ascending</option>
        <option value="reward-desc">Reward descending</option>
        <option value="reward-asc">Reward ascending</option>
      </select>
    </label>

    <div class="count">{filteredTraces.length} of {traces.length}</div>
  </div>

  {#if filteredTraces.length === 0}
    <div class="empty-state">
      <h2>No traces match the current filters</h2>
      <p>Adjust the sidebar filters or search query to show more mock traces.</p>
    </div>
  {:else}
    <div class="traces-table-wrap">
      <table class="traces-table">
        <thead>
          <tr>
            <th>Trace ID</th>
            <th>Request</th>
            <th>Step</th>
            <th>Reward</th>
            <th>Model</th>
            <th>Request time</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {#each filteredTraces as trace}
            <tr class="trace-row" onclick={() => toggleTrace(trace.id)}>
              <td class="trace-id-cell">
                <span class="trace-id">{trace.id}</span>
              </td>
              <td class="request-cell">
                <div class="request">{trace.request}</div>
                <div class="preview">{trace.preview}</div>
              </td>
              <td>{trace.step}</td>
              <td>{trace.reward.toFixed(2)}</td>
              <td>{trace.modelVersion}</td>
              <td>{trace.timestamp}</td>
              <td>
                <span class="state {stateClass(trace.state)}">{trace.state}</span>
              </td>
            </tr>
            {#if expandedTraceId === trace.id}
              <tr class="expanded-row">
                <td colspan="7">
                  <div class="trace-detail">
                    <div class="detail-meta">
                      <span>Project: {project || "demo-project"}</span>
                      <span>Run: {trace.run}</span>
                      <span>Latency: {trace.latency}</span>
                      <span>Group: {trace.groupId}</span>
                    </div>

                    <div class="conversation">
                      {#each trace.messages as message}
                        <div class="message">
                          <div class="message-role">{message.role}</div>
                          <pre class="message-content">{message.content}</pre>
                        </div>
                      {/each}
                    </div>
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .traces-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
    background: var(--background-fill-primary, white);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .search-wrap {
    flex: 1;
  }
  .search-wrap input,
  .sort-wrap select {
    width: 100%;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    padding: 10px 12px;
    font-family: inherit;
  }
  .sort-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    white-space: nowrap;
  }
  .count {
    margin-left: auto;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 14px;
    white-space: nowrap;
  }
  .traces-table-wrap {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
  }
  .traces-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  .traces-table th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: var(--background-fill-primary, white);
  }
  .traces-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
    vertical-align: top;
  }
  .trace-row {
    cursor: pointer;
  }
  .trace-row:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .trace-id {
    display: inline-block;
    background: var(--background-fill-secondary, #f3f4f6);
    color: #334155;
    border-radius: var(--radius-md, 6px);
    padding: 6px 10px;
    font-size: 13px;
  }
  .request {
    font-weight: 500;
    margin-bottom: 4px;
  }
  .preview {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    line-height: 1.45;
  }
  .state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
  }
  .state::before {
    content: "";
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: currentColor;
  }
  .state.error {
    color: #b91c1c;
  }
  .state.success {
    color: #4b5563;
  }
  .expanded-row td {
    padding: 0;
    background: var(--background-fill-secondary, #fafafa);
  }
  .trace-detail {
    padding: 16px 18px 18px;
  }
  .detail-meta {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    margin-bottom: 14px;
  }
  .conversation {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .message {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    padding: 12px;
  }
  .message-role {
    margin-bottom: 8px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .message-content {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    color: var(--body-text-color, #1f2937);
    line-height: 1.5;
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  @media (max-width: 1100px) {
    .toolbar {
      flex-wrap: wrap;
    }
    .count {
      margin-left: 0;
    }
  }
</style>
