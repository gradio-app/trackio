(function () {
  "use strict";

  let MANIFEST = null;
  const PAGE_CACHE = {};
  const UNFURL_CACHE = {};

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function flattenTree(node, depth, acc) {
    acc.push({ node: node, depth: depth });
    (node.children || []).forEach((c) => flattenTree(c, depth + 1, acc));
    return acc;
  }

  function findNode(node, slug) {
    if (node.slug === slug) return node;
    for (const c of node.children || []) {
      const hit = findNode(c, slug);
      if (hit) return hit;
    }
    return null;
  }

  /* -------------------- minimal markdown -------------------- */

  function inline(text) {
    let t = esc(text);
    t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
    t = t.replace(/\*\*([^*]+)\*\*/g, (_, c) => `<strong>${c}</strong>`);
    t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, txt, url) => {
      const safe = esc(url);
      const attrs = /^https?:/.test(url) ? ' target="_blank" rel="noopener"' : "";
      return `<a href="${safe}"${attrs}>${txt}</a>`;
    });
    t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (m, pre, url) => {
      return `${pre}<a href="${url}" target="_blank" rel="noopener">${url}</a>`;
    });
    return t;
  }

  const URL_ONLY = /^(https?:\/\/[^\s]+)$/;

  function renderMarkdown(md, container) {
    const lines = md.replace(/<!--[\s\S]*?-->/g, "").split("\n");
    let i = 0;
    let para = [];

    function flushPara() {
      if (!para.length) return;
      const joined = para.join(" ").trim();
      para = [];
      if (!joined) return;
      if (URL_ONLY.test(joined) || IMG_PATH.test(joined)) {
        container.appendChild(unfurl(joined));
        return;
      }
      const p = document.createElement("p");
      p.innerHTML = inline(joined);
      container.appendChild(p);
    }

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      if (trimmed === "") {
        flushPara();
        i++;
        continue;
      }
      if (trimmed.startsWith("```")) {
        flushPara();
        const buf = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          buf.push(lines[i]);
          i++;
        }
        i++;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = buf.join("\n");
        pre.appendChild(code);
        container.appendChild(pre);
        continue;
      }
      if (trimmed === "---") {
        flushPara();
        container.appendChild(document.createElement("hr"));
        i++;
        continue;
      }
      const h = trimmed.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        flushPara();
        const el = document.createElement("h" + h[1].length);
        el.innerHTML = inline(h[2]);
        container.appendChild(el);
        i++;
        continue;
      }
      if (
        trimmed.startsWith("|") &&
        i + 1 < lines.length &&
        /^\|?[\s:|-]*-{2,}[\s:|-]*\|?$/.test(lines[i + 1].trim())
      ) {
        flushPara();
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          rows.push(parseRow(lines[i].trim()));
          i++;
        }
        renderTable(rows, container);
        continue;
      }
      if (trimmed.startsWith("> ")) {
        flushPara();
        const bq = document.createElement("blockquote");
        bq.innerHTML = inline(trimmed.slice(2));
        container.appendChild(bq);
        i++;
        continue;
      }
      if (/^`[^`]+`$/.test(trimmed)) {
        flushPara();
        const el = document.createElement("div");
        el.className = "ts";
        el.textContent = trimmed.replace(/`/g, "");
        container.appendChild(el);
        i++;
        continue;
      }
      if (trimmed.startsWith("- ")) {
        flushPara();
        const items = [];
        while (i < lines.length && lines[i].trim().startsWith("- ")) {
          items.push(lines[i].trim().slice(2).trim());
          i++;
        }
        renderList(items, container);
        continue;
      }
      para.push(trimmed);
      i++;
    }
    flushPara();
  }

  function parseRow(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
  }

  const TRUTHY = ["x", "✓", "✔", "yes", "done", "true", "[x]"];
  const CHIP_COLORS = [
    ["#e7f0ff", "#2158d0"],
    ["#fde8ec", "#c62a4b"],
    ["#e6f7ee", "#1a8a55"],
    ["#fdf0e0", "#b26a12"],
    ["#efe9ff", "#5b3bd6"],
    ["#e6f6f8", "#127b88"],
  ];

  function chipColor(name) {
    let h = 0;
    for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return CHIP_COLORS[h % CHIP_COLORS.length];
  }

  const STATUS_MAP = {
    "": ["Planned", "gray"],
    planned: ["Planned", "gray"],
    todo: ["Planned", "gray"],
    "to do": ["Planned", "gray"],
    backlog: ["Planned", "gray"],
    "in progress": ["In progress", "amber"],
    "in-progress": ["In progress", "amber"],
    wip: ["In progress", "amber"],
    running: ["In progress", "amber"],
    active: ["In progress", "amber"],
    done: ["Done", "green"],
    complete: ["Done", "green"],
    completed: ["Done", "green"],
    blocked: ["Blocked", "red"],
    failed: ["Failed", "red"],
    abandoned: ["Abandoned", "gray"],
  };

  function statusBadge(val) {
    const [label, tone] = STATUS_MAP[val.toLowerCase()] || [val || "—", "gray"];
    return `<span class="badge ${tone}">${esc(label)}</span>`;
  }

  function renderTable(rows, container) {
    if (rows.length < 2) return;
    const header = rows[0];
    const body = rows.slice(2);
    const roles = header.map((h) => {
      const t = h.toLowerCase();
      if (t.includes("status") || t.includes("state")) return "status";
      if (t.includes("progress") || t.includes("complete") || t.includes("done"))
        return "check";
      if (t === "who" || t.includes("assign") || t.includes("owner")) return "who";
      return "text";
    });
    const table = document.createElement("table");
    table.className = "board";
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    header.forEach((h, c) => {
      const th = document.createElement("th");
      th.textContent = h;
      if (roles[c] === "check") th.className = "col-check";
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    body.forEach((cells) => {
      const nonEmpty = cells.filter((x) => x !== "").length;
      if (nonEmpty === 1 && cells[0]) {
        const tr = document.createElement("tr");
        tr.className = "section-row";
        const td = document.createElement("td");
        td.colSpan = header.length;
        td.innerHTML = inline(cells[0]);
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      const tr = document.createElement("tr");
      header.forEach((_, c) => {
        const td = document.createElement("td");
        const val = (cells[c] || "").trim();
        if (roles[c] === "status") {
          td.className = "col-status";
          td.innerHTML = statusBadge(val);
        } else if (roles[c] === "check") {
          td.className = "col-check";
          const on = TRUTHY.indexOf(val.toLowerCase()) !== -1;
          td.innerHTML = `<span class="box ${on ? "on" : ""}">${on ? "✓" : ""}</span>`;
        } else if (roles[c] === "who") {
          if (!val || /^to assign$/i.test(val)) {
            td.innerHTML = `<span class="who-chip muted">${esc(val || "—")}</span>`;
          } else {
            const [bg, fg] = chipColor(val);
            td.innerHTML = `<span class="who-chip" style="background:${bg};color:${fg}">${esc(val)}</span>`;
          }
        } else {
          td.innerHTML = inline(val);
        }
        tr.appendChild(td);
      });
      const link = tr.querySelector('a[href^="#/"]');
      if (link) {
        tr.classList.add("linked-row");
        tr.addEventListener("click", (e) => {
          if (e.target.tagName !== "A") location.hash = link.getAttribute("href");
        });
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    const wrap = document.createElement("div");
    wrap.className = "board-wrap";
    wrap.appendChild(table);
    container.appendChild(wrap);
  }

  const IMG_PATH = /^[^\s]+\.(png|jpe?g|gif|svg|webp)$/i;

  function renderList(items, container) {
    let ul = null;
    items.forEach((item) => {
      if (URL_ONLY.test(item) || IMG_PATH.test(item)) {
        ul = null;
        container.appendChild(unfurl(item));
      } else if (item.indexOf("📦 Artifact") !== -1) {
        ul = null;
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML = inline(item);
        container.appendChild(div);
      } else {
        if (!ul) {
          ul = document.createElement("ul");
          container.appendChild(ul);
        }
        const li = document.createElement("li");
        li.innerHTML = inline(item);
        ul.appendChild(li);
      }
    });
  }

  /* -------------------- unfurl providers -------------------- */

  function card(url, kind, icon, title, desc, chips) {
    const a = document.createElement("a");
    a.className = "unfurl";
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    const chipHtml = (chips || [])
      .filter(Boolean)
      .map((c) => `<span class="chip">${esc(c)}</span>`)
      .join("");
    a.innerHTML =
      `<div class="unfurl-body">` +
      `<div class="unfurl-ico">${icon}</div>` +
      `<div class="unfurl-main">` +
      `<div class="unfurl-kind">${esc(kind)}</div>` +
      `<div class="unfurl-title">${esc(title)}</div>` +
      (desc ? `<div class="unfurl-desc">${esc(desc)}</div>` : "") +
      (chipHtml ? `<div class="unfurl-meta">${chipHtml}</div>` : "") +
      `</div></div>` +
      `<div class="unfurl-raw">${esc(url)}</div>`;
    return a;
  }

  function fmt(n) {
    if (n == null) return null;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }

  const providers = [
    {
      test: (u) => /\.(png|jpe?g|gif|svg|webp)(\?|$)/i.test(u) || /\/artifact_blob\//.test(u),
      render: (u, el) => {
        el.className = "unfurl image";
        el.href = u;
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = u;
        img.alt = "artifact image";
        el.appendChild(img);
      },
    },
    {
      test: (u) => /huggingface\.co\/datasets\//.test(u),
      render: async (u, el) => {
        const id = u.split("/datasets/")[1].split(/[?#]/)[0].replace(/\/$/, "");
        base(el, u, "HF Dataset", "📊", id, "Hugging Face dataset");
        const d = await getJSON(`https://huggingface.co/api/datasets/${id}`);
        if (d)
          fill(el, id, d.cardData?.pretty_name || id, [
            `↓ ${fmt(d.downloads)}`,
            `♥ ${fmt(d.likes)}`,
            ...(d.tags || []).filter((t) => !t.includes(":")).slice(0, 3),
          ]);
      },
    },
    {
      test: (u) => /huggingface\.co\/spaces\//.test(u),
      render: async (u, el) => {
        const id = u.split("/spaces/")[1].split(/[?#]/)[0].replace(/\/$/, "");
        base(el, u, "HF Space", "🚀", id, "Interactive Space / dashboard");
        const d = await getJSON(`https://huggingface.co/api/spaces/${id}`);
        if (d)
          fill(el, id, null, [d.sdk, `♥ ${fmt(d.likes)}`, ...(d.tags || []).slice(0, 2)]);
      },
    },
    {
      test: (u) => /arxiv\.org\/(abs|pdf)\//.test(u),
      render: (u, el) => {
        const id = u.split(/\/(abs|pdf)\//)[2].replace(/\.pdf$/, "");
        base(el, u, "arXiv", "📄", `arXiv:${id}`, "Preprint");
      },
    },
    {
      test: (u) => /github\.com\/[^/]+\/[^/]+/.test(u),
      render: async (u, el) => {
        const m = u.match(/github\.com\/([^/]+)\/([^/?#]+)/);
        const id = `${m[1]}/${m[2]}`;
        base(el, u, "GitHub", "🐙", id, "Repository");
        const d = await getJSON(`https://api.github.com/repos/${id}`);
        if (d)
          fill(el, id, d.description, [
            `★ ${fmt(d.stargazers_count)}`,
            d.language,
          ]);
      },
    },
    {
      test: (u) => /huggingface\.co\/[^/]+\/[^/]+/.test(u),
      render: async (u, el) => {
        const id = u.split("huggingface.co/")[1].split(/[?#]/)[0].replace(/\/$/, "");
        base(el, u, "HF Model", "🤗", id, "Model on the Hugging Face Hub");
        const d = await getJSON(`https://huggingface.co/api/models/${id}`);
        if (d)
          fill(el, id, d.pipeline_tag ? `Task: ${d.pipeline_tag}` : null, [
            `↓ ${fmt(d.downloads)}`,
            `♥ ${fmt(d.likes)}`,
            ...(d.tags || []).filter((t) => !t.includes(":")).slice(0, 2),
          ]);
      },
    },
  ];

  function base(el, url, kind, icon, title, desc) {
    el.className = "unfurl";
    el.href = url;
    el.innerHTML =
      `<div class="unfurl-body"><div class="unfurl-ico">${icon}</div>` +
      `<div class="unfurl-main"><div class="unfurl-kind">${esc(kind)}</div>` +
      `<div class="unfurl-title">${esc(title)}</div>` +
      `<div class="unfurl-desc">${esc(desc)}</div>` +
      `<div class="unfurl-meta"></div></div></div>` +
      `<div class="unfurl-raw">${esc(url)}</div>`;
  }

  function fill(el, title, desc, chips) {
    if (title) el.querySelector(".unfurl-title").textContent = title;
    const d = el.querySelector(".unfurl-desc");
    if (desc) d.textContent = desc;
    const meta = el.querySelector(".unfurl-meta");
    meta.innerHTML = (chips || [])
      .filter(Boolean)
      .map((c) => `<span class="chip">${esc(c)}</span>`)
      .join("");
  }

  async function getJSON(url) {
    if (UNFURL_CACHE[url] !== undefined) return UNFURL_CACHE[url];
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      UNFURL_CACHE[url] = j;
      return j;
    } catch (e) {
      UNFURL_CACHE[url] = null;
      return null;
    }
  }

  function unfurl(url) {
    const el = document.createElement("a");
    el.className = "unfurl";
    el.href = url;
    el.target = "_blank";
    el.rel = "noopener";
    const provider = providers.find((p) => p.test(url));
    if (provider) {
      const out = provider.render(url, el);
      if (out && typeof out.then === "function") out.catch(() => {});
    } else {
      let host = url;
      try {
        host = new URL(url).hostname.replace(/^www\./, "");
      } catch (e) {}
      base(el, url, "Link", "🔗", host, url);
    }
    return el;
  }

  /* -------------------- routing / render -------------------- */

  function buildTree() {
    const tree = document.getElementById("tree");
    tree.innerHTML = "";
    const nodes = [];
    (MANIFEST.root.children || []).forEach((c) => flattenTree(c, 0, nodes));
    nodes.forEach(({ node, depth }) => {
      const a = document.createElement("a");
      a.href = "#/" + node.slug;
      a.textContent = node.title;
      a.className = "depth-" + depth;
      a.dataset.slug = node.slug;
      tree.appendChild(a);
    });
  }

  function highlight(slug) {
    document
      .querySelectorAll("#tree a")
      .forEach((a) => a.classList.toggle("active", a.dataset.slug === slug));
    document
      .getElementById("book-head")
      .classList.toggle("active", slug === MANIFEST.root.slug);
  }

  async function loadPage(slug) {
    const node = findNode(MANIFEST.root, slug) || MANIFEST.root;
    const page = document.getElementById("page");
    page.innerHTML = "";
    if (!PAGE_CACHE[node.file]) {
      try {
        const r = await fetch("./" + node.file);
        PAGE_CACHE[node.file] = await r.text();
      } catch (e) {
        PAGE_CACHE[node.file] = "# " + node.title + "\n\n_Could not load page._";
      }
    }
    renderMarkdown(PAGE_CACHE[node.file], page);
    highlight(node.slug);
    document.getElementById("content").scrollTo(0, 0);
    window.scrollTo(0, 0);
  }

  function route() {
    const slug = (location.hash || "").replace(/^#\//, "") || MANIFEST.root.slug;
    loadPage(slug);
  }

  function setupConnect() {
    const space = MANIFEST.space_id;
    if (!space) return;
    const steps = [
      { t: "Install Trackio, if you don't have it yet.", c: "uv tool install trackio" },
      { t: "Add the Trackio skill for your agent, then reload it.", c: "trackio skills add" },
      { t: "Connect to this logbook.", c: `trackio logbook open ${space}` },
    ];
    const ol = document.getElementById("connect-steps");
    steps.forEach((s, i) => {
      const li = document.createElement("li");
      const title = document.createElement("div");
      title.className = "step-title";
      title.textContent = `${i + 1}. ${s.t}`;
      const block = document.createElement("div");
      block.className = "codeblock";
      const code = document.createElement("code");
      code.textContent = s.c;
      const copy = document.createElement("button");
      copy.className = "copy";
      copy.type = "button";
      copy.title = "Copy";
      copy.textContent = "⧉";
      copy.addEventListener("click", () => copyText(s.c, copy, "⧉"));
      block.appendChild(code);
      block.appendChild(copy);
      li.appendChild(title);
      li.appendChild(block);
      ol.appendChild(li);
    });

    const agentPrompt =
      `Read and help maintain this Trackio experiment logbook ("${MANIFEST.title}").\n\n` +
      "1. If you don't have Trackio, install it:  uv tool install trackio\n" +
      "2. Add the Trackio skill for your agent:   trackio skills add   (then reload)\n" +
      `3. Connect to this logbook:                trackio logbook open ${space}\n\n` +
      "You'll get a compact, token-efficient copy you can read. If I've given you " +
      'write access to the Space, add findings with `trackio logbook note "..." ' +
      '--experiment "..."` and they will sync back automatically.';

    const foot = document.getElementById("sidebar-foot");
    foot.hidden = false;
    const modal = document.getElementById("modal");
    const open = () => (modal.hidden = false);
    const close = () => (modal.hidden = true);
    document.getElementById("connect-btn").addEventListener("click", open);
    document.getElementById("modal-close").addEventListener("click", close);
    modal.querySelector(".modal-backdrop").addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
    const agentBtn = document.getElementById("copy-agent");
    agentBtn.addEventListener("click", () =>
      copyText(agentPrompt, agentBtn, "Copy for agent")
    );
  }

  function copyText(text, btn, restore) {
    const done = () => {
      const prev = btn.textContent;
      btn.textContent = restore === "⧉" ? "✓" : "Copied!";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = restore;
        btn.classList.remove("copied");
      }, 1400);
      void prev;
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (e) {}
      document.body.removeChild(ta);
      done();
    }
  }

  async function init() {
    MANIFEST = await (await fetch("./logbook.json")).json();
    document.title = MANIFEST.title + " · Trackio Logbook";
    document.getElementById("book-title").textContent = MANIFEST.title;
    document.getElementById("book-head").addEventListener("click", () => {
      location.hash = "#/" + MANIFEST.root.slug;
    });
    buildTree();
    setupConnect();
    window.addEventListener("hashchange", route);
    route();
  }

  init();
})();
