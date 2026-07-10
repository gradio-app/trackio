(function () {
  "use strict";

  let MANIFEST = null;
  const PAGE_CACHE = {};
  const UNFURL_CACHE = {};
  const LIVE_RELOAD_MS = 1500;

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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
      const item = /^https?:/.test(url) ? classifyResource(url) : null;
      const data = item
        ? ` class="res-link" data-res-url="${esc(item.url)}"`
        : "";
      return `<a href="${safe}"${attrs}${data}>${txt}</a>`;
    });
    t = t.replace(/(^|[\s(])(https?:\/\/[^\s<>)"'`]+)/g, (m, pre, url) => {
      let rest = "";
      const cut = url.search(/&quot;|&#39;|&lt;|&gt;/);
      if (cut !== -1) {
        rest = url.slice(cut);
        url = url.slice(0, cut);
      }
      const trailing = (url.match(/[.,;:!?`]+$/) || [""])[0];
      const clean = trailing ? url.slice(0, -trailing.length) : url;
      if (!clean) return m;
      const item = classifyResource(clean);
      if (item) return `${pre}${resChipHtml(item)}${trailing}${rest}`;
      return `${pre}<a href="${clean}" target="_blank" rel="noopener">${clean}</a>${trailing}${rest}`;
    });
    return t;
  }

  function resChipHtml(item) {
    return (
      `<a class="res-chip" href="${esc(item.url)}" target="_blank" ` +
      `rel="noopener" data-res-url="${esc(item.url)}">` +
      `<span class="res-chip-ico">${RESOURCE_ICONS[item.kind]}</span>` +
      `${esc(item.id)}</a>`
    );
  }

  const URL_ONLY = /^(https?:\/\/[^\s]+)$/;
  const DETECTED_URL =
    /(https?:\/\/[^\s<>)\]"'`]+|trackio-local-dashboard:\/\/[^\s<>)\]"'`]+|trackio-artifact:\/\/[^\s<>)\]"'`]+)/g;

  function renderMarkdown(md, container) {
    const cellRe = /(^|\n)---\n<!-- trackio-cell\n([\s\S]*?)\n-->\n([\s\S]*?)(?=\n---\n<!-- trackio-cell\n|\s*$)/g;
    let pos = 0;
    let found = false;
    let match;
    while ((match = cellRe.exec(md))) {
      found = true;
      renderMarkdownPlain(md.slice(pos, match.index + match[1].length), container);
      const meta = parseCellMeta(match[2]);
      renderCell(meta, match[3], container);
      pos = match.index + match[0].length;
    }
    if (found) {
      renderMarkdownPlain(md.slice(pos), container);
    } else {
      renderMarkdownPlain(md, container);
    }
  }

  function parseCellMeta(raw) {
    try {
      return JSON.parse(raw);
    } catch (e) {
      return { type: "markdown", title: "Note" };
    }
  }

  function renderMarkdownPlain(md, container) {
    const lines = md.replace(/<!--[\s\S]*?-->/g, "").split("\n");
    let i = 0;
    let para = [];

    function flushPara() {
      if (!para.length) return;
      const joined = para.join(" ").trim();
      para = [];
      if (!joined) return;
      if (/^trackio-artifact:\/\/\S+$/.test(joined)) return;
      if (joined.indexOf("📦 Artifact") !== -1) {
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML = inline(joined);
        container.appendChild(div);
        return;
      }
      if (URL_ONLY.test(joined) || IMG_PATH.test(joined)) {
        const el = renderStandaloneUrl(joined);
        if (el) container.appendChild(el);
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
      const fence = trimmed.match(/^(`{3,}|~{3,})(.*)$/);
      if (fence) {
        flushPara();
        const marker = fence[1][0];
        const closeRe = new RegExp("^" + marker + "{" + fence[1].length + ",}\\s*$");
        const info = fence[2].trim();
        const buf = [];
        i++;
        while (i < lines.length && !closeRe.test(lines[i].trim())) {
          buf.push(lines[i]);
          i++;
        }
        i++;
        const lang = (info.split(/\s+/)[0] || "").toLowerCase();
        const tm = info.match(/title=(\S+)/);
        container.appendChild(
          renderCode(buf.join("\n"), lang, tm ? tm[1] : null)
        );
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

  function renderCell(meta, body, container) {
    const cell = document.createElement("section");
    cell.className = `cell ${meta.type || "markdown"}`;
    if (meta.id) cell.dataset.cellId = meta.id;
    if (isPinned(meta)) cell.classList.add("pinned-source");

    const head = document.createElement("div");
    head.className = "cell-head";
    const rawTitle = (meta.title || "").trim();
    const title = rawTitle && rawTitle.toLowerCase() !== "untitled" ? esc(rawTitle) : "";
    const when = meta.created_at ? `<span>${esc(formatTime(meta.created_at))}</span>` : "";
    head.innerHTML =
      (title ? `<div class="cell-title">${title}</div>` : "") +
      `<div class="cell-meta">${when}</div>`;
    if (!title) head.classList.add("no-title");
    cell.appendChild(head);

    const bodyEl = document.createElement("div");
    bodyEl.className = "cell-body";
    if (meta.type === "code") {
      renderCodeCell(body, bodyEl);
    } else if (meta.type === "figure") {
      renderFigureCell(body, bodyEl, head);
    } else if (meta.type === "artifact") {
      renderMarkdownPlain(body, bodyEl);
      const chip = bodyEl.querySelector(".artifact-chip");
      const uri = body.match(
        /(trackio-artifact:\/\/\S+|https:\/\/huggingface\.co\/buckets\/[^\s<)]+#\S+)/
      );
      if (chip && uri) chip.dataset.resUrl = uri[1];
    } else if (meta.type === "dashboard") {
      renderDashboardCell(meta, body, bodyEl);
    } else {
      const cleaned = stripDuplicateTitle(body, meta.title);
      renderMarkdownPlain(cleaned, bodyEl);
      renderDetectedEmbeds(cleaned, bodyEl);
    }
    cell.appendChild(bodyEl);
    container.appendChild(cell);
    return cell;
  }

  function isPinned(meta) {
    return Boolean(meta && (meta.pinned === true || meta.pinned === "true"));
  }

  function stripDuplicateTitle(body, title) {
    if (!title) return body;
    const m = body.match(/^\s*#{1,6}\s+([^\n]+)\n?/);
    if (!m) return body;
    const norm = (s) =>
      s
        .toLowerCase()
        .replace(/[*_`#]/g, "")
        .replace(/\s+/g, " ")
        .trim();
    return norm(m[1]) === norm(title) ? body.slice(m[0].length) : body;
  }

  function formatTime(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function parseFences(text) {
    const fenceRe = /(`{3,4}|~{3,4})([^\n]*)\n([\s\S]*?)\n\1/g;
    const parts = [];
    let pos = 0;
    let match;
    while ((match = fenceRe.exec(text))) {
      if (match.index > pos) {
        parts.push({ kind: "text", text: text.slice(pos, match.index) });
      }
      const info = match[2].trim();
      const lang = (info.split(/\s+/)[0] || "").toLowerCase();
      const titleMatch = info.match(/title=(\S+)/);
      parts.push({
        kind: lang === "result" || lang === "output" ? "output" : "code",
        lang,
        title: titleMatch ? titleMatch[1] : null,
        text: match[3],
      });
      pos = match.index + match[0].length;
    }
    if (pos < text.length) parts.push({ kind: "text", text: text.slice(pos) });
    return parts;
  }

  function renderFigureCell(text, container, head) {
    const parts = parseFences(text);
    const htmlPart = parts.find((part) => part.lang === "html");
    const rawPart = parts.find((part) => part.lang === "raw");
    if (!htmlPart || !htmlPart.text.trim()) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No figure HTML.";
      container.appendChild(empty);
      return;
    }
    const frame = document.createElement("iframe");
    frame.className = "figure-frame";
    frame.sandbox = "allow-scripts allow-same-origin";
    frame.loading = "lazy";
    frame.srcdoc = htmlPart.text;
    if (!rawPart || !rawPart.text.trim()) {
      container.appendChild(frame);
      return;
    }
    const sw = document.createElement("div");
    sw.className = "fig-switch";
    const thumb = document.createElement("span");
    thumb.className = "fig-switch-thumb";
    const figBtn = document.createElement("button");
    figBtn.type = "button";
    figBtn.className = "active";
    figBtn.textContent = "Figure";
    const rawBtn = document.createElement("button");
    rawBtn.type = "button";
    rawBtn.textContent = "Raw";
    sw.appendChild(thumb);
    sw.appendChild(figBtn);
    sw.appendChild(rawBtn);
    const rawView = document.createElement("div");
    rawView.className = "figure-raw";
    rawView.hidden = true;
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = rawPart.text;
    pre.appendChild(code);
    rawView.appendChild(pre);
    rawView.appendChild(copySnippetBtn(rawPart.text));
    const select = (showRaw) => {
      sw.classList.toggle("raw", showRaw);
      figBtn.classList.toggle("active", !showRaw);
      rawBtn.classList.toggle("active", showRaw);
      frame.hidden = showRaw;
      rawView.hidden = !showRaw;
    };
    figBtn.addEventListener("click", () => select(false));
    rawBtn.addEventListener("click", () => select(true));
    if (head) {
      head.insertBefore(sw, head.querySelector(".cell-meta"));
    } else {
      container.appendChild(sw);
    }
    container.appendChild(frame);
    container.appendChild(rawView);
  }

  function extractUrls(text) {
    const seen = new Set();
    const urls = [];
    let match;
    while ((match = DETECTED_URL.exec(text))) {
      const url = match[1].replace(/[.,;:!?'"`]+$/, "");
      if (!seen.has(url)) {
        seen.add(url);
        urls.push(url);
      }
    }
    DETECTED_URL.lastIndex = 0;
    return urls;
  }

  const IMG_URL = /(\.(png|jpe?g|gif|svg|webp)(\?|$)|\/artifact_blob\/)/i;

  function renderDetectedEmbeds(text, container) {
    extractUrls(text).forEach((url) => {
      if (url.startsWith("trackio-local-dashboard://")) {
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML =
          "🎯 <strong>Local Trackio dashboard</strong> — publish the logbook to share it";
        container.appendChild(div);
      } else if (IMG_URL.test(url)) {
        container.appendChild(renderImage(url));
      } else if (/huggingface\.co\/spaces\//.test(url)) {
        maybeEmbedTrackioSpace(url, container);
      }
    });
  }

  function renderStandaloneUrl(url) {
    if (IMG_URL.test(url) || IMG_PATH.test(url)) return renderImage(url);
    const item = classifyResource(url);
    if (item) {
      const marker = document.createElement("span");
      marker.className = "resource-anchor";
      marker.dataset.resUrl = item.url;
      marker.setAttribute("aria-hidden", "true");
      return marker;
    }
    const p = document.createElement("p");
    p.innerHTML = inline(url);
    return p;
  }

  function renderImage(url) {
    const a = document.createElement("a");
    a.className = "unfurl image";
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = url;
    img.alt = "artifact image";
    a.appendChild(img);
    return a;
  }

  function maybeEmbedTrackioSpace(url, container) {
    const id = url.split("/spaces/")[1].split(/[?#]/)[0].replace(/\/$/, "");
    const holder = document.createElement("div");
    container.appendChild(holder);
    getJSON(`https://huggingface.co/api/spaces/${id}`).then((d) => {
      const tags = (d && d.tags) || [];
      if (tags.some((t) => String(t).toLowerCase() === "trackio")) {
        renderTrackioSpaceEmbed(holder, url, id);
      } else {
        holder.remove();
      }
    });
  }

  function jpGutter(label) {
    const g = document.createElement("div");
    g.className = "jp-gutter";
    g.textContent = label;
    return g;
  }

  function renderCodeCell(body, container) {
    const parts = parseFences(body);
    const block = document.createElement("div");
    block.className = "jp";
    const input = document.createElement("div");
    input.className = "jp-in";
    const inputBody = document.createElement("div");
    inputBody.className = "jp-in-body";
    input.appendChild(jpGutter("In"));
    input.appendChild(inputBody);
    let metaEl = null;
    let outputEl = null;
    const embedTexts = [];
    parts.forEach((part) => {
      if (part.kind === "text") {
        const text = part.text.trim();
        if (!text) return;
        if (/^exit\s+\S+(\s|·)/.test(text)) {
          metaEl = document.createElement("div");
          metaEl.className = "jp-meta";
          metaEl.textContent = text.replace(
            /\s*·\s*[A-Z][a-z]{2} \d{1,2}, \d{4}.*$/,
            ""
          );
        } else {
          renderMarkdownPlain(text, container);
          embedTexts.push(text);
        }
        return;
      }
      if (part.kind === "output") {
        outputEl = document.createElement("div");
        outputEl.className = "jp-out";
        outputEl.appendChild(jpGutter("Out"));
        const pre = document.createElement("pre");
        pre.className = "jp-out-pre";
        const c = document.createElement("code");
        c.textContent = part.text;
        pre.appendChild(c);
        outputEl.appendChild(pre);
        outputEl.appendChild(copySnippetBtn(part.text));
        embedTexts.push(part.text);
        return;
      }
      inputBody.appendChild(renderCode(part.text, part.lang, part.title));
    });
    if (inputBody.childNodes.length > 0) block.appendChild(input);
    if (metaEl) block.appendChild(metaEl);
    if (outputEl) block.appendChild(outputEl);
    if (block.childNodes.length) container.appendChild(block);
    embedTexts.forEach((text) => renderDetectedEmbeds(text, container));
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
      if (header.length > 1 && nonEmpty === 1 && cells[0]) {
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

  const HL_RULES = {
    python: [
      ["comment", /#[^\n]*/],
      ["string", /'''[\s\S]*?'''|"""[\s\S]*?"""|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/],
      [
        "keyword",
        /\b(?:def|class|return|if|elif|else|for|while|import|from|as|with|try|except|finally|raise|in|not|and|or|is|None|True|False|lambda|yield|global|nonlocal|assert|pass|break|continue|async|await|print)\b/,
      ],
      ["number", /\b\d[\d_.eE+-]*\b/],
    ],
    bash: [
      ["comment", /#[^\n]*/],
      ["string", /'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/],
      ["keyword", /\b(?:if|then|else|fi|for|in|do|done|while|case|esac|function|export|source|echo|cd|return|local)\b/],
      ["number", /(?<=\s)-{1,2}[a-zA-Z][\w-]*/],
    ],
    json: [
      ["string", /"(?:\\.|[^"\\])*"/],
      ["keyword", /\b(?:true|false|null)\b/],
      ["number", /-?\b\d[\d.eE+-]*\b/],
    ],
    yaml: [
      ["comment", /#[^\n]*/],
      ["string", /'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/],
      ["keyword", /\b(?:true|false|null|yes|no)\b/],
      ["number", /-?\b\d[\d.eE+-]*\b/],
    ],
  };
  HL_RULES.javascript = HL_RULES.python;
  HL_RULES.typescript = HL_RULES.python;
  HL_RULES.sql = [
    ["comment", /--[^\n]*/],
    ["string", /'(?:\\.|[^'\\])*'/],
    [
      "keyword",
      /\b(?:SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|LIMIT|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|AS|AND|OR|NOT|NULL|COUNT|DISTINCT|IN)\b/i,
    ],
    ["number", /\b\d[\d.]*\b/],
  ];

  function highlightCode(code, lang) {
    const rules = HL_RULES[lang];
    if (!rules) return esc(code);
    const combined = new RegExp(rules.map((r) => "(" + r[1].source + ")").join("|"), "g");
    let out = "";
    let last = 0;
    let m;
    while ((m = combined.exec(code))) {
      if (m[0] === "") {
        combined.lastIndex++;
        continue;
      }
      out += esc(code.slice(last, m.index));
      let gi = 1;
      while (gi < m.length && m[gi] === undefined) gi++;
      out += `<span class="tok-${rules[gi - 1][0]}">${esc(m[0])}</span>`;
      last = m.index + m[0].length;
    }
    out += esc(code.slice(last));
    return out;
  }

  function copySnippetBtn(text) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-snippet";
    btn.title = "Copy";
    btn.textContent = "⧉";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      copyText(text, btn, "⧉");
    });
    return btn;
  }

  function renderCode(code, lang, title) {
    const pre = document.createElement("pre");
    pre.className = "hl";
    const c = document.createElement("code");
    c.innerHTML = highlightCode(code, lang);
    pre.appendChild(c);
    if (!title) {
      const wrap = document.createElement("div");
      wrap.className = "snippet";
      wrap.appendChild(pre);
      wrap.appendChild(copySnippetBtn(code));
      return wrap;
    }
    const det = document.createElement("details");
    det.className = "code-accordion";
    const sum = document.createElement("summary");
    sum.innerHTML =
      `<span class="code-ico">&lt;/&gt;</span>` +
      `<span class="code-name">${esc(title)}</span>`;
    sum
      .querySelector(".code-name")
      .addEventListener("click", (e) => e.preventDefault());
    det.appendChild(sum);
    const wrap = document.createElement("div");
    wrap.className = "snippet";
    wrap.appendChild(pre);
    wrap.appendChild(copySnippetBtn(code));
    det.appendChild(wrap);
    return det;
  }

  const IMG_PATH = /^[^\s]+\.(png|jpe?g|gif|svg|webp)$/i;

  function renderList(items, container) {
    let ul = null;
    items.forEach((item) => {
      if (URL_ONLY.test(item) || IMG_PATH.test(item)) {
        const el = renderStandaloneUrl(item);
        if (el) {
          ul = null;
          container.appendChild(el);
        }
      } else if (item.indexOf("📦 Artifact") !== -1) {
        ul = null;
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML = inline(item);
        container.appendChild(div);
      } else if (item.indexOf("trackio-local-dashboard://") !== -1) {
        ul = null;
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML =
          "🎯 <strong>Local dashboard</strong> — publish the logbook to share it";
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

  /* -------------------- resources rail -------------------- */

  function fmt(n) {
    if (n == null) return null;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }

  const RESOURCE_SECTIONS = [
    ["model", "Models", "🤗"],
    ["dataset", "Datasets", "📊"],
    ["space", "Spaces", "🚀"],
    ["artifact", "Artifacts", "📦"],
    ["paper", "Papers", "📄"],
    ["repo", "Code", "🐙"],
    ["job", "Jobs", "⚙️"],
    ["bucket", "Buckets", "🪣"],
  ];

  const RESOURCE_ICONS = Object.fromEntries(
    RESOURCE_SECTIONS.map(([kind, , icon]) => [kind, icon])
  );

  const RESOURCE_DESC = {
    model: "Model",
    dataset: "Dataset",
    space: "Space",
    artifact: "Artifact — in Bucket",
    paper: "Paper",
    repo: "Repository",
    job: "Job — status & logs",
    bucket: "Bucket — artifacts & data",
  };

  const HF_NON_MODEL_PREFIX =
    /^(datasets|spaces|jobs|buckets|papers|blog|docs|api|posts|collections|organizations|settings|new|join|login|pricing|tasks|learn|chat|models)(\/|$)/;

  function hfId(url, marker) {
    return url.split(marker)[1].split(/[?#]/)[0].replace(/\/$/, "");
  }

  function classifyResource(url) {
    if (IMG_URL.test(url)) {
      return null;
    }
    let m;
    if (url.startsWith("trackio-local-dashboard://")) {
      return {
        kind: "space",
        id: url.slice("trackio-local-dashboard://".length),
        url,
        local: true,
      };
    }
    if (url.startsWith("trackio-artifact://")) {
      return {
        kind: "artifact",
        id: url.slice("trackio-artifact://".length),
        url,
        local: true,
      };
    }
    if ((m = url.match(/huggingface\.co\/buckets\/[^#\s]+#(.+)/))) {
      return { kind: "artifact", id: decodeURIComponent(m[1]), url };
    }
    if (/huggingface\.co\/datasets\/[^/]+\/[^/]+/.test(url)) {
      return { kind: "dataset", id: hfId(url, "/datasets/"), url };
    }
    if (/huggingface\.co\/spaces\/[^/]+\/[^/]+/.test(url)) {
      return { kind: "space", id: hfId(url, "/spaces/"), url };
    }
    if (/huggingface\.co\/jobs\//.test(url)) {
      const parts = hfId(url, "/jobs/").split("/");
      const jid = parts[1] || "";
      return {
        kind: "job",
        id: parts[0] + (jid ? ` · ${jid.slice(0, 12)}${jid.length > 12 ? "…" : ""}` : ""),
        url,
      };
    }
    if (/huggingface\.co\/buckets\//.test(url)) {
      return { kind: "bucket", id: hfId(url, "/buckets/"), url };
    }
    if (/huggingface\.co\/papers\//.test(url)) {
      return { kind: "paper", id: `Paper ${hfId(url, "/papers/")}`, url };
    }
    if ((m = url.match(/arxiv\.org\/(?:abs|pdf)\/([^?#\s]+)/))) {
      return { kind: "paper", id: `arXiv:${m[1].replace(/\.pdf$/, "")}`, url };
    }
    if ((m = url.match(/github\.com\/([^/?#]+\/[^/?#]+)/))) {
      return { kind: "repo", id: m[1], url };
    }
    if ((m = url.match(/huggingface\.co\/([^?#]+)/))) {
      const rest = m[1].replace(/\/$/, "");
      if (/^[^/]+\/[^/]+$/.test(rest) && !HF_NON_MODEL_PREFIX.test(rest)) {
        return { kind: "model", id: rest, url };
      }
    }
    return null;
  }

  async function fillRailMeta(item, el) {
    if (item.local) return;
    const meta = el.querySelector(".rail-meta");
    const set = (parts) => {
      const text = parts.filter(Boolean).join(" · ");
      if (text) meta.textContent = text;
    };
    if (item.kind === "model") {
      const d = await getJSON(`https://huggingface.co/api/models/${item.id}`);
      if (d) set([d.pipeline_tag, `↓ ${fmt(d.downloads)}`, `♥ ${fmt(d.likes)}`]);
    } else if (item.kind === "dataset") {
      const d = await getJSON(`https://huggingface.co/api/datasets/${item.id}`);
      if (d) set([`↓ ${fmt(d.downloads)}`, `♥ ${fmt(d.likes)}`]);
    } else if (item.kind === "space") {
      const d = await getJSON(`https://huggingface.co/api/spaces/${item.id}`);
      if (d) set([d.sdk, `♥ ${fmt(d.likes)}`]);
    } else if (item.kind === "repo") {
      const d = await getJSON(`https://api.github.com/repos/${item.id}`);
      if (d) set([`★ ${fmt(d.stargazers_count)}`, d.language]);
    } else if (item.kind === "paper") {
      const m = item.id.match(/^(?:arXiv:|Paper )(.+)$/);
      if (!m) return;
      const arxivId = m[1].replace(/v\d+$/, "");
      const d = await getJSON(`https://huggingface.co/api/papers/${arxivId}`);
      if (d && d.id) {
        if (el.href) el.href = `https://huggingface.co/papers/${d.id}`;
        const title =
          d.title && d.title.length > 70 ? `${d.title.slice(0, 69)}…` : d.title;
        set([title, d.upvotes ? `▲ ${fmt(d.upvotes)}` : null]);
      }
    }
  }

  const BARE_ID_SKIP_DIRS = new Set([
    "scripts",
    "configs",
    "config",
    "results",
    "figures",
    "data",
    "datasets",
    "src",
    "tests",
    "test",
    "examples",
    "pages",
    "assets",
    "docs",
    "outputs",
    "output",
    "checkpoints",
    "models",
    "utils",
    "lib",
    "bin",
    "tmp",
    "node_modules",
    "dist",
    "build",
  ]);
  const FILE_EXT_RE =
    /\.(py|pyc|js|ts|jsx|tsx|json|jsonl|yaml|yml|csv|tsv|md|txt|sh|bash|html|css|png|jpe?g|svg|gif|webp|ipynb|toml|cfg|ini|lock|pdf|whl|gz|zip|tar|pt|pth|bin|safetensors|db|sqlite)$/i;

  async function detectBareModelIds(text, groups) {
    const stripped = text.replace(DETECTED_URL, " ");
    DETECTED_URL.lastIndex = 0;
    const seen = new Set();
    const candidates = [];
    const re = /(^|[\s"'`(=[])([A-Za-z0-9][\w.-]*\/[A-Za-z0-9][\w.-]*)/g;
    let m;
    while ((m = re.exec(stripped)) && candidates.length < 15) {
      const id = m[2].replace(/[.:,]+$/, "");
      if (seen.has(id)) continue;
      seen.add(id);
      if (FILE_EXT_RE.test(id)) continue;
      if (BARE_ID_SKIP_DIRS.has(id.split("/")[0].toLowerCase())) continue;
      candidates.push(id);
    }
    const results = await Promise.all(
      candidates.map((id) => getJSON(`https://huggingface.co/api/models/${id}`))
    );
    let added = false;
    const confirmed = [];
    results.forEach((d, i) => {
      if (!d || !d.id) return;
      const id = candidates[i];
      confirmed.push(id);
      const url = `https://huggingface.co/${id}`;
      if (!groups.has("model")) groups.set("model", new Map());
      if (!groups.get("model").has(url)) {
        groups.get("model").set(url, { kind: "model", id, url });
        added = true;
      }
    });
    return { added, confirmed };
  }

  function chipifyBareIds(ids, container) {
    if (!ids.length) return;
    const escaped = ids.map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp("(" + escaped.join("|") + ")");
    const splitter = new RegExp(pattern.source, "g");
    container
      .querySelectorAll(".cell.markdown .cell-body")
      .forEach((body) => {
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
          acceptNode(node) {
            if (!pattern.test(node.nodeValue)) return NodeFilter.FILTER_REJECT;
            for (
              let el = node.parentElement;
              el && el !== body;
              el = el.parentElement
            ) {
              if (["A", "CODE", "PRE", "BUTTON"].indexOf(el.tagName) !== -1) {
                return NodeFilter.FILTER_REJECT;
              }
            }
            return NodeFilter.FILTER_ACCEPT;
          },
        });
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach((node) => {
          const frag = document.createDocumentFragment();
          node.nodeValue.split(splitter).forEach((part) => {
            if (ids.indexOf(part) !== -1) {
              const holder = document.createElement("span");
              holder.innerHTML = resChipHtml({
                kind: "model",
                id: part,
                url: `https://huggingface.co/${part}`,
              });
              frag.appendChild(holder.firstChild);
            } else if (part) {
              frag.appendChild(document.createTextNode(part));
            }
          });
          node.parentNode.replaceChild(frag, node);
        });
      });
  }

  let RAIL_TOKEN = 0;

  function renderRail(md, body, rail) {
    const token = String(++RAIL_TOKEN);
    rail.dataset.renderToken = token;
    const scanText = md.replace(
      /(`{3,4}|~{3,4})(html|raw)[^\n]*\n[\s\S]*?\n\1/g,
      " "
    );
    const groups = new Map();
    extractUrls(scanText).forEach((url) => {
      const item = classifyResource(url);
      if (!item) return;
      if (!groups.has(item.kind)) groups.set(item.kind, new Map());
      groups.get(item.kind).set(item.url, item);
    });
    paintRail(groups, body, rail);
    detectBareModelIds(scanText, groups)
      .then((result) => {
        if (rail.dataset.renderToken !== token) return;
        chipifyBareIds(result.confirmed, body);
        if (result.added) paintRail(groups, body, rail);
      })
      .catch(() => {});
  }

  function paintRail(groups, body, rail) {
    rail.innerHTML = "";
    RESOURCE_SECTIONS.forEach(([kind, label, icon]) => {
      const group = groups.get(kind);
      if (!group || !group.size) return;
      group.forEach((item) => {
        const el = document.createElement(item.local ? "div" : "a");
        el.className = item.local ? "rail-item rail-local" : "rail-item";
        if (!item.local) {
          el.href = item.url;
          el.target = "_blank";
          el.rel = "noopener";
        }
        el.dataset.resUrl = item.url;
        const desc = item.local
          ? "local · publish to share"
          : RESOURCE_DESC[kind];
        el.innerHTML =
          `<div class="rail-kind"><span>${icon}</span>${esc(label.replace(/s$/, ""))}</div>` +
          `<div class="rail-title">${esc(item.id)}</div>` +
          `<div class="rail-meta">${esc(desc)}</div>`;
        rail.appendChild(el);
        fillRailMeta(item, el)
          .catch(() => {})
          .finally(() => scheduleRailPosition(body, rail));
      });
    });
    rail.hidden = !rail.childElementCount;
    scheduleRailPosition(body, rail);
  }

  function resourceAnchor(body, url) {
    return body.querySelector(`[data-res-url="${CSS.escape(url)}"]`);
  }

  function positionRail(body, rail) {
    if (rail.hidden || !rail.isConnected) return;
    const bodyRect = body.getBoundingClientRect();
    const items = Array.from(rail.querySelectorAll(".rail-item")).map((el, index) => {
      const anchor = resourceAnchor(body, el.dataset.resUrl);
      return {
        el,
        index,
        desired: anchor
          ? Math.max(0, anchor.getBoundingClientRect().top - bodyRect.top)
          : 0,
      };
    });
    items.sort((a, b) => a.desired - b.desired || a.index - b.index);
    let cursor = 0;
    items.forEach(({ el, desired }) => {
      const top = Math.max(desired, cursor);
      el.style.top = `${top}px`;
      cursor = top + el.offsetHeight + 10;
    });
    rail.style.minHeight = `${Math.max(body.offsetHeight, cursor)}px`;
  }

  function scheduleRailPosition(body, rail) {
    cancelAnimationFrame(Number(rail.dataset.positionFrame || 0));
    rail.dataset.positionFrame = String(
      requestAnimationFrame(() => positionRail(body, rail))
    );
  }

  function renderTrackioSpaceEmbed(el, url, id) {
    const sub = id.toLowerCase().replace(/[^a-z0-9-]/g, "-");
    el.className = "trackio-embed unfurl embed";
    el.innerHTML =
      `<div class="embed-head">` +
      `<span class="unfurl-kind">🎯 Trackio dashboard</span>` +
      `<a class="embed-title" href="${esc(url)}" target="_blank" rel="noopener">${esc(id)}</a>` +
      `<a class="embed-open" href="${esc(url)}" target="_blank" rel="noopener">Open ↗</a>` +
      `</div>` +
      `<iframe class="embed-frame" src="https://${sub}.hf.space/?sidebar=hidden&navbar=hidden" loading="lazy" ` +
      `allow="clipboard-read; clipboard-write; fullscreen"></iframe>`;
  }

  let DASHBOARD_INFO = null;
  function fetchDashboardInfo() {
    if (!DASHBOARD_INFO) {
      DASHBOARD_INFO = fetch("./dashboard-info.json", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
    }
    return DASHBOARD_INFO;
  }

  function renderLocalDashboardEmbed(el, baseUrl, project) {
    const open = baseUrl.replace(/\/$/, "") + "/?project=" + encodeURIComponent(project);
    const src = open + "&sidebar=hidden&navbar=hidden";
    el.className = "trackio-embed unfurl embed";
    el.innerHTML =
      `<div class="embed-head">` +
      `<span class="unfurl-kind">🎯 Trackio dashboard</span>` +
      `<a class="embed-title" href="${esc(open)}" target="_blank" rel="noopener">${esc(project)}</a>` +
      `<a class="embed-open" href="${esc(open)}" target="_blank" rel="noopener">Open ↗</a>` +
      `</div>` +
      `<iframe class="embed-frame" src="${esc(src)}" loading="lazy" ` +
      `allow="clipboard-read; clipboard-write; fullscreen"></iframe>`;
  }

  function renderDashboardCell(meta, body, container) {
    const project = meta.dashboard_project || "";
    const holder = document.createElement("div");
    container.appendChild(holder);
    const space = body.match(/https:\/\/huggingface\.co\/spaces\/[^\s<>)"'`]+/);
    if (space) {
      const id = space[0].split("/spaces/")[1].split(/[?#]/)[0].replace(/\/$/, "");
      renderTrackioSpaceEmbed(holder, space[0], id);
      return;
    }
    const chip = () => {
      holder.className = "artifact-chip";
      holder.innerHTML =
        "🎯 <strong>Local Trackio dashboard</strong> — publish the logbook to share it";
    };
    if (!isLocalPreview()) {
      chip();
      return;
    }
    fetchDashboardInfo().then((info) => {
      if (info && info.url) renderLocalDashboardEmbed(holder, info.url, project);
      else chip();
    });
  }

  const CACHE_PREFIX = "trackio-logbook:";
  const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
  const CACHE_MISS_TTL_MS = 60 * 60 * 1000;

  function cacheGet(url) {
    try {
      const raw = localStorage.getItem(CACHE_PREFIX + url);
      if (!raw) return undefined;
      const entry = JSON.parse(raw);
      const ttl = entry.d === null ? CACHE_MISS_TTL_MS : CACHE_TTL_MS;
      if (Date.now() - entry.t > ttl) {
        localStorage.removeItem(CACHE_PREFIX + url);
        return undefined;
      }
      return entry.d;
    } catch (e) {
      return undefined;
    }
  }

  function cacheSet(url, data) {
    try {
      localStorage.setItem(
        CACHE_PREFIX + url,
        JSON.stringify({ t: Date.now(), d: data })
      );
    } catch (e) {}
  }

  async function getJSON(url) {
    if (UNFURL_CACHE[url] !== undefined) return UNFURL_CACHE[url];
    const cached = cacheGet(url);
    if (cached !== undefined) {
      UNFURL_CACHE[url] = cached;
      return cached;
    }
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      UNFURL_CACHE[url] = j;
      cacheSet(url, j);
      return j;
    } catch (e) {
      UNFURL_CACHE[url] = null;
      cacheSet(url, null);
      return null;
    }
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

  function clearPageCache() {
    Object.keys(PAGE_CACHE).forEach((key) => {
      delete PAGE_CACHE[key];
    });
  }

  function isLocalPreview() {
    return ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
  }

  async function fetchManifest() {
    const suffix = isLocalPreview() ? `?t=${Date.now()}` : "";
    return await (await fetch("./logbook.json" + suffix, { cache: "no-store" })).json();
  }

  async function fetchPage(node) {
    if (PAGE_CACHE[node.file]) return PAGE_CACHE[node.file];
    try {
      const suffix = isLocalPreview()
        ? `?rev=${encodeURIComponent(MANIFEST.revision || "")}`
        : "";
      const r = await fetch("./" + node.file + suffix, { cache: "no-store" });
      PAGE_CACHE[node.file] = await r.text();
    } catch (e) {
      PAGE_CACHE[node.file] = "# " + node.title + "\n\n_Could not load section._";
    }
    return PAGE_CACHE[node.file];
  }

  function allNodes() {
    const nodes = [];
    flattenTree(MANIFEST.root, 0, nodes);
    return nodes.map(({ node }) => node);
  }

  function collectPinnedCells(markdown, nodes) {
    const cells = [];
    markdown.forEach((text, index) => {
      const cellRe = /(^|\n)---\n<!-- trackio-cell\n([\s\S]*?)\n-->\n([\s\S]*?)(?=\n---\n<!-- trackio-cell\n|\s*$)/g;
      let match;
      let cellIndex = 0;
      while ((match = cellRe.exec(text))) {
        const meta = parseCellMeta(match[2]);
        if (isPinned(meta)) {
          cells.push({
            meta,
            body: match[3],
            node: nodes[index],
            index: cells.length,
            order: meta.pinned_at || meta.created_at || "",
            cellIndex,
          });
        }
        cellIndex++;
      }
    });
    return cells.sort(
      (a, b) =>
        a.order.localeCompare(b.order) ||
        a.index - b.index ||
        a.cellIndex - b.cellIndex
    );
  }

  function renderPinnedNotes(cells, container) {
    if (!cells.length) return;
    const deck = document.createElement("section");
    deck.className = "pinned-notes";
    const heading = document.createElement("div");
    heading.className = "pinned-notes-heading";
    heading.innerHTML = "<h2>Pinned notes</h2>";
    deck.appendChild(heading);

    const list = document.createElement("div");
    list.className = "pinned-notes-list";
    cells.forEach(({ meta, body }) => {
      const cell = renderCell(meta, body, list);
      cell.classList.add("pinned-copy");
    });
    deck.appendChild(list);
    const anchor = container.querySelector(".agent-hint");
    container.insertBefore(deck, anchor ? anchor.nextSibling : container.firstChild);
    container.closest(".book-intro").classList.add("has-pinned-notes");
  }

  function removePageDirectory(body) {
    const heading = Array.from(body.children).find(
      (el) => el.tagName === "H2" && el.textContent.trim().toLowerCase() === "pages"
    );
    if (!heading) return;
    let current = heading;
    while (current) {
      const next = current.nextElementSibling;
      current.remove();
      if (next && ["H1", "H2"].includes(next.tagName)) break;
      current = next;
    }
  }

  const RAIL_OBSERVERS = [];

  async function renderLogbook(opts = {}) {
    const scrollY = window.scrollY;
    const page = document.getElementById("page");
    RAIL_OBSERVERS.splice(0).forEach((observer) => observer.disconnect());
    page.innerHTML = "";
    const nodes = allNodes();
    const markdown = await Promise.all(nodes.map(fetchPage));
    const pinnedCells = collectPinnedCells(markdown, nodes);
    let bookIntroBody = null;
    nodes.forEach((node, index) => {
      const section = document.createElement("section");
      section.className = "page-section";
      section.id = "/" + node.slug;
      section.dataset.slug = node.slug;

      const layout = document.createElement("div");
      layout.className = "page-layout";
      const body = document.createElement("div");
      body.className = "page-body";
      const rail = document.createElement("aside");
      rail.className = "context-rail";
      rail.setAttribute("aria-label", `Resources for ${node.title}`);

      renderMarkdown(markdown[index], body);
      if (node.slug === MANIFEST.root.slug) {
        section.classList.add("book-intro");
        removePageDirectory(body);
        const hint = buildAgentHint();
        const h1 = body.querySelector("h1");
        if (h1 && h1.parentNode === body) {
          body.insertBefore(hint, h1.nextSibling);
        } else {
          body.prepend(hint);
        }
        bookIntroBody = body;
      }
      layout.appendChild(body);
      layout.appendChild(rail);
      section.appendChild(layout);
      page.appendChild(section);
      renderRail(markdown[index], body, rail);
      if (window.ResizeObserver) {
        const observer = new ResizeObserver(() => scheduleRailPosition(body, rail));
        observer.observe(body);
        observer.observe(rail);
        RAIL_OBSERVERS.push(observer);
      }
    });
    if (bookIntroBody) renderPinnedNotes(pinnedCells, bookIntroBody);
    requestAnimationFrame(() => {
      if (opts.preserveScroll) {
        window.scrollTo(0, scrollY);
      } else {
        scrollToHash({ behavior: "auto" });
      }
      updateActiveSection();
    });
  }

  function setupResourceHover() {
    document.addEventListener("mouseover", (e) => {
      const el = e.target.closest && e.target.closest("[data-res-url]");
      if (!el || el.classList.contains("rail-item")) return;
      const url = el.getAttribute("data-res-url");
      const section = el.closest(".page-section");
      const scope = section || document;
      scope.querySelectorAll(".context-rail [data-res-url]").forEach((n) => {
        n.classList.toggle("res-hl", n.getAttribute("data-res-url") === url);
      });
    });
    document.addEventListener("mouseout", (e) => {
      const el = e.target.closest && e.target.closest("[data-res-url]");
      if (!el || el.classList.contains("rail-item")) return;
      document.querySelectorAll(".context-rail .res-hl").forEach((n) => {
        n.classList.remove("res-hl");
      });
    });
  }

  function buildAgentHint() {
    const onSpaces =
      /\.hf\.space$/.test(location.hostname) ||
      /(^|\.)huggingface\.co$/.test(location.hostname);
    let source = "";
    if (onSpaces && MANIFEST.space_id) {
      source = ` ${MANIFEST.space_id}`;
    } else if (/^https?:$/.test(location.protocol)) {
      source = ` ${location.origin}/`;
    }
    const command = `trackio logbook read${source}`;
    const tokens = MANIFEST.agent_view_tokens;
    const div = document.createElement("div");
    div.className = "agent-hint";
    const label = document.createElement("span");
    label.className = "agent-hint-label";
    label.textContent = "Read from the CLI:";
    const code = document.createElement("code");
    code.textContent = command;
    const copy = document.createElement("button");
    copy.className = "copy";
    copy.type = "button";
    copy.title = "Copy";
    copy.textContent = "⧉";
    copy.addEventListener("click", () => copyText(command, copy, "⧉"));
    const note = document.createElement("span");
    note.className = "agent-hint-note";
    note.textContent =
      "compact view for agents" + (tokens ? ` · ~${fmt(tokens)} tokens` : "");
    div.appendChild(label);
    div.appendChild(code);
    div.appendChild(copy);
    div.appendChild(note);
    return div;
  }

  function currentSlug() {
    const slug = (location.hash || "").replace(/^#\//, "") || MANIFEST.root.slug;
    return findNode(MANIFEST.root, slug) ? slug : MANIFEST.root.slug;
  }

  function scrollToHash(opts = {}) {
    const slug = currentSlug();
    if (!location.hash) {
      window.scrollTo({ top: 0, behavior: opts.behavior || "auto" });
      highlight(slug);
      return;
    }
    const section = document.getElementById("/" + slug);
    if (section) section.scrollIntoView({ behavior: opts.behavior || "smooth" });
    highlight(slug);
  }

  let SCROLL_FRAME = 0;
  function updateActiveSection() {
    cancelAnimationFrame(SCROLL_FRAME);
    SCROLL_FRAME = requestAnimationFrame(() => {
      const sections = Array.from(document.querySelectorAll(".page-section"));
      if (!sections.length) return;
      const marker = Math.min(window.innerHeight * 0.28, 180);
      let active = sections[0];
      sections.forEach((section) => {
        if (section.getBoundingClientRect().top <= marker) active = section;
      });
      if (
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 2
      ) {
        active = sections[sections.length - 1];
      }
      highlight(active.dataset.slug);
    });
  }

  function startLiveReload() {
    if (!isLocalPreview()) return;
    setInterval(async () => {
      try {
        const next = await fetchManifest();
        if (!next || next.revision === MANIFEST.revision) return;
        MANIFEST = next;
        clearPageCache();
        document.title = MANIFEST.title + " · Trackio Logbook";
        document.getElementById("book-title").textContent = MANIFEST.title;
        buildTree();
        renderLogbook({ preserveScroll: true });
      } catch (e) {}
    }, LIVE_RELOAD_MS);
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
      "Start with `trackio logbook read`; use `trackio logbook read page \"...\"` " +
      "for a page-level view, then fetch relevant details with " +
      "`trackio logbook read cell cell_<id>`. If I've given you " +
      'write access to the Space, add findings with `trackio logbook cell markdown "..." ' +
      '--page "..."` and they will sync back automatically.';

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
    MANIFEST = await fetchManifest();
    document.title = MANIFEST.title + " · Trackio Logbook";
    document.getElementById("book-title").textContent = MANIFEST.title;
    document.getElementById("book-head").addEventListener("click", () => {
      const target = "#/" + MANIFEST.root.slug;
      if (location.hash === target) scrollToHash();
      else location.hash = target;
    });
    buildTree();
    setupConnect();
    setupResourceHover();
    window.addEventListener("hashchange", () => scrollToHash());
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    await renderLogbook();
    startLiveReload();
  }

  init();
})();
