(function () {
  "use strict";

  let MANIFEST = null;
  const PAGE_CACHE = {};
  const UNFURL_CACHE = {};
  const LIVE_RELOAD_MS = 1500;
  const FIGURE_FRAME_WINDOWS = new Set();
  let FIGURE_NAVIGATION_READY = false;

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
    /(https?:\/\/[^\s<>)\]"'`]+|trackio-local-dashboard:\/\/[^\s<>)\]"'`]+|trackio-artifact:\/\/[^\s<>)\]"'`]+|trackio-local-path:\/\/[^\s<>)\]"'`]+)/g;

  function renderMarkdown(md, container) {
    const cellRe = /(^|\n)---\n<!-- trackio-cell\n([\s\S]*?)\n-->\n([\s\S]*?)(?=\n---\n<!-- trackio-cell\n|\s*$)/g;
    const tokens = [];
    let pos = 0;
    let found = false;
    let match;
    while ((match = cellRe.exec(md))) {
      found = true;
      tokens.push({
        kind: "md",
        text: md.slice(pos, match.index + match[1].length),
      });
      tokens.push({
        kind: "cell",
        meta: parseCellMeta(match[2]),
        body: match[3],
      });
      pos = match.index + match[0].length;
    }
    tokens.push({ kind: "md", text: found ? md.slice(pos) : md });

    for (let i = 0; i < tokens.length; i++) {
      const t = tokens[i];
      if (t.kind === "md") {
        renderMarkdownPlain(t.text, container);
        continue;
      }
      if (t.consumed) continue;
      if (t.meta.type === "code") {
        const arts = [];
        for (let j = i + 1; j < tokens.length; j++) {
          const n = tokens[j];
          if (n.kind === "md") {
            if (n.text.trim() === "") continue;
            break;
          }
          if (n.meta.type === "artifact") {
            arts.push(n);
            n.consumed = true;
            continue;
          }
          break;
        }
        renderCell(t.meta, t.body, container, arts);
      } else {
        renderCell(t.meta, t.body, container);
      }
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
      if (/^trackio-local-path:\/\/\S+$/.test(joined)) return;
      if (joined.indexOf("📦 Artifact") !== -1) {
        const div = document.createElement("div");
        div.className = "artifact-chip";
        div.innerHTML = ARTIFACT_ICON_IMG + inline(joined.replace(/📦\s*/, ""));
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

  function renderCell(meta, body, container, artifacts) {
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
      renderCodeCell(body, bodyEl, artifacts);
    } else if (meta.type === "figure") {
      cell.dataset.resUrl = `trackio-figure://${(meta.title || "Figure").trim()}`;
      renderFigureCell(body, bodyEl, head);
    } else if (meta.type === "artifact") {
      renderMarkdownPlain(body, bodyEl);
      const chip = bodyEl.querySelector(".artifact-chip");
      const uri = body.match(
        /(trackio-artifact:\/\/\S+|trackio-local-path:\/\/\S+|https:\/\/huggingface\.co\/buckets\/[^\s<)]+#\S+)/
      );
      if (chip && uri) chip.dataset.resUrl = uri[1];
    } else if (meta.type === "dashboard") {
      const sp = body.match(/https:\/\/huggingface\.co\/spaces\/[^\s<>)"'`]+/);
      cell.dataset.resUrl = sp
        ? sp[0]
        : `trackio-local-dashboard://${(meta.dashboard_project || "").trim()}`;
      renderDashboardCell(meta, body, bodyEl, head);
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

  function fitFigureFrame(frame, wrap) {
    let doc;
    try {
      doc = frame.contentDocument;
    } catch (e) {
      return;
    }
    if (!doc || !doc.body) return;
    frame.style.transform = "none";
    frame.style.width = "100%";
    frame.style.height = "auto";
    frame.style.position = "";
    frame.style.left = "";
    frame.style.top = "";
    const avail = wrap.clientWidth;
    const isFullscreen =
      document.fullscreenElement === wrap ||
      document.webkitFullscreenElement === wrap;
    const availHeight = isFullscreen ? wrap.clientHeight : Infinity;
    const cw = Math.max(doc.body.scrollWidth, doc.documentElement.scrollWidth, 1);
    const ch = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight, 1);
    const scale = Math.min(avail / cw, availHeight / ch);
    if (avail && scale < 1 - 1e-3) {
      frame.style.width = `${cw}px`;
      frame.style.height = `${ch}px`;
      frame.style.transformOrigin = "top left";
      frame.style.transform = `scale(${scale})`;
      if (isFullscreen) {
        frame.style.position = "absolute";
        frame.style.left = `${Math.max(0, (avail - cw * scale) / 2)}px`;
        frame.style.top = `${Math.max(0, (availHeight - ch * scale) / 2)}px`;
        wrap.style.height = "100%";
      } else {
        wrap.style.height = `${Math.ceil(ch * scale)}px`;
      }
    } else {
      frame.style.width = "100%";
      frame.style.height = `${ch}px`;
      wrap.style.height = isFullscreen ? "100%" : `${ch}px`;
    }
  }

  function attachFigureFit(frame, wrap) {
    const refit = () => fitFigureFrame(frame, wrap);
    frame.addEventListener("load", refit);
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => refit());
      ro.observe(wrap);
    }
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
    registerFigureNavigation(frame);
    const figWrap = document.createElement("div");
    figWrap.className = "figure-fit";
    figWrap.appendChild(frame);
    attachFigureFit(frame, figWrap);
    if (head) {
      const metaEl = head.querySelector(".cell-meta");
      if (metaEl)
        metaEl.insertBefore(buildFullscreenControl(figWrap, frame), metaEl.firstChild);
    }
    if (!rawPart || !rawPart.text.trim()) {
      container.appendChild(figWrap);
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
      figWrap.hidden = showRaw;
      rawView.hidden = !showRaw;
    };
    figBtn.addEventListener("click", () => select(false));
    rawBtn.addEventListener("click", () => select(true));
    if (head) {
      head.insertBefore(sw, head.querySelector(".cell-meta"));
    } else {
      container.appendChild(sw);
    }
    container.appendChild(figWrap);
    container.appendChild(rawView);
  }

  // Poster embeds can send `{ type: "trackio-logbook:navigate", target: "..." }`
  // from their iframe. Only accept messages from figure frames we created, and
  // only route to pages that are present in this logbook's manifest.
  function registerFigureNavigation(frame) {
    const registerFrameWindow = () => {
      if (frame.contentWindow) FIGURE_FRAME_WINDOWS.add(frame.contentWindow);
    };
    // `srcdoc` replaces the initial about:blank document. Register after that
    // navigation as well, so messages come from the live figure document.
    frame.addEventListener("load", registerFrameWindow);
    registerFrameWindow();
    if (FIGURE_NAVIGATION_READY) return;
    FIGURE_NAVIGATION_READY = true;
    window.addEventListener("message", (event) => {
      if (!FIGURE_FRAME_WINDOWS.has(event.source)) return;
      const message = event.data;
      if (!message || message.type !== "trackio-logbook:navigate") return;
      const target = String(message.target || "").replace(/^#?\//, "");
      if (!target || !MANIFEST || !findNode(MANIFEST.root, target)) return;
      const hash = "#/" + target;
      if (location.hash === hash) scrollToHash();
      else location.hash = hash;
    });
  }

  const FULLSCREEN_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"/>' +
    '<path d="M3 8 8 3M16 3l5 5M21 16l-5 5M8 21l-5-5"/></svg>';

  // Figures are rendered in same-origin iframes, so fullscreen the fitted
  // wrapper rather than the iframe document. This uses the browser's native
  // fullscreen UI and preserves the figure's existing responsive sizing.
  function buildFullscreenControl(figWrap, frame) {
    const wrap = document.createElement("span");
    wrap.className = "cell-fullscreen";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cell-fullscreen-btn";
    btn.setAttribute("aria-label", "Open figure in fullscreen");
    btn.title = "Open figure in fullscreen";
    btn.innerHTML = FULLSCREEN_ICON;
    wrap.appendChild(btn);

    btn.addEventListener("click", async () => {
      const request = figWrap.requestFullscreen || figWrap.webkitRequestFullscreen;
      if (!request) return;
      try {
        await request.call(figWrap);
      } catch (_) {
        // Fullscreen can be disabled by the embedding browser or policy.
      }
    });
    document.addEventListener("fullscreenchange", () => {
      if (document.fullscreenElement === figWrap) fitFigureFrame(frame, figWrap);
    });
    return wrap;
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
        div.dataset.resUrl = url;
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

  function renderOutArtifact(info) {
    const remote = !info.local && !!info.url;
    const el = document.createElement(remote ? "a" : "div");
    el.className = "out-artifact";
    if (remote) {
      el.href = info.url;
      el.target = "_blank";
      el.rel = "noopener";
    }
    el.dataset.resUrl = info.resUrl;
    const parts = [info.type, info.size].filter(Boolean).map(esc);
    const state = remote
      ? `<span class="out-artifact-state open">Open ↗</span>`
      : `<span class="out-artifact-state">publish to share</span>`;
    const meta = parts.length ? `${parts.join(" · ")} · ${state}` : state;
    el.innerHTML =
      `<span class="out-artifact-ico">${ARTIFACT_ICON_IMG}</span>` +
      `<span class="out-artifact-name">${esc(info.name)}</span>` +
      `<span class="out-artifact-meta">${meta}</span>`;
    return el;
  }

  function renderCodeCell(body, container, artifacts) {
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
    let outBody = null;
    const ensureOut = () => {
      if (outputEl) return;
      outputEl = document.createElement("div");
      outputEl.className = "jp-out";
      outputEl.appendChild(jpGutter("Out"));
      outBody = document.createElement("div");
      outBody.className = "jp-out-body";
      outputEl.appendChild(outBody);
    };
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
        ensureOut();
        const pre = document.createElement("pre");
        pre.className = "jp-out-pre";
        const c = document.createElement("code");
        c.textContent = part.text;
        pre.appendChild(c);
        outBody.appendChild(pre);
        outputEl.appendChild(copySnippetBtn(part.text));
        embedTexts.push(part.text);
        return;
      }
      inputBody.appendChild(renderCode(part.text, part.lang, part.title));
    });
    if (artifacts && artifacts.length) {
      ensureOut();
      const artWrap = document.createElement("div");
      artWrap.className = "jp-artifacts";
      artifacts.forEach((a) => {
        artWrap.appendChild(
          renderOutArtifact(artifactInfoFromCell(a.meta, a.body))
        );
      });
      outBody.appendChild(artWrap);
    }
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
    det.dataset.resUrl = `trackio-script://${title}`;
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
        div.innerHTML = inline(item.replace("📦", "🪣"));
        container.appendChild(div);
      } else if (item.indexOf("trackio-local-dashboard://") !== -1) {
        ul = null;
        const uri = item.match(/trackio-local-dashboard:\/\/\S+/)?.[0] || "";
        const div = document.createElement("div");
        div.className = "artifact-chip";
        if (uri) div.dataset.resUrl = uri;
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
    ["dashboard", "Dashboards", "🎯"],
    ["model", "Models", "🤗"],
    ["dataset", "Datasets", "📊"],
    ["space", "Spaces", "🚀"],
    ["artifact", "Artifacts", "🪣"],
    ["paper", "Papers", "📄"],
    ["repo", "Code", "🐙"],
    ["job", "Jobs", "⚙️"],
    ["bucket", "Buckets", "🪣"],
  ];

  const RESOURCE_ICONS = Object.fromEntries(
    RESOURCE_SECTIONS.map(([kind, , icon]) => [kind, icon])
  );

  const ARTIFACT_ICON_IMG = `<img class="art-ico" src="./bucket-icon.svg" alt="" />`;
  const DASHBOARD_ICON_IMG = `<img class="art-ico" src="./trackio-logo-light.png" alt="" />`;

  const RESOURCE_DESC = {
    dashboard: "Dashboard",
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
        kind: "dashboard",
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
    if (url.startsWith("trackio-local-path://")) {
      return {
        kind: "artifact",
        id: url.slice("trackio-local-path://".length),
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
    } else if (item.kind === "space" || item.kind === "dashboard") {
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
  const RAIL_EXCLUDE_KINDS = new Set(["paper", "repo", "artifact", "dashboard"]);

  function railDashboardItem(it) {
    return {
      kind: "dashboard",
      id: it.id,
      url: it.local ? it.resUrl : it.url || it.resUrl,
      local: it.local,
      railLabel: "Dashboard",
    };
  }

  function promoteTrackioSpacesInRail(groups, dashResUrls, body, rail, token) {
    const spaceGroup = groups.get("space");
    if (!spaceGroup || !spaceGroup.size) return;
    spaceGroup.forEach((item, url) => {
      getJSON(`https://huggingface.co/api/spaces/${item.id}`)
        .then((d) => {
          if (rail.dataset.renderToken !== token) return;
          const tags = (d && d.tags) || [];
          if (!tags.some((t) => String(t).toLowerCase() === "trackio")) return;
          if (dashResUrls.has(url)) return;
          spaceGroup.delete(url);
          if (!spaceGroup.size) groups.delete("space");
          if (!groups.has("dashboard")) groups.set("dashboard", new Map());
          groups.get("dashboard").set(url, {
            kind: "dashboard",
            id: item.id,
            url: item.url,
            local: false,
            railLabel: "Dashboard",
          });
          dashResUrls.add(url);
          paintRail(groups, body, rail);
        })
        .catch(() => {});
    });
  }

  function renderRail(md, body, rail) {
    const token = String(++RAIL_TOKEN);
    rail.dataset.renderToken = token;
    const scanText = md.replace(
      /(`{3,4}|~{3,4})(html|raw)[^\n]*\n[\s\S]*?\n\1/g,
      " "
    );
    const groups = new Map();
    const dashMap = new Map();
    const dashResUrls = new Set();
    cellDashboardItems(md).forEach((it) => {
      if (dashMap.has(it.resUrl)) return;
      dashMap.set(it.resUrl, railDashboardItem(it));
      dashResUrls.add(it.resUrl);
    });
    if (dashMap.size) groups.set("dashboard", dashMap);
    extractUrls(scanText).forEach((url) => {
      const item = classifyResource(url);
      if (!item) return;
      if (RAIL_EXCLUDE_KINDS.has(item.kind)) return;
      if (dashResUrls.has(url)) return;
      if (!groups.has(item.kind)) groups.set(item.kind, new Map());
      groups.get(item.kind).set(item.url, item);
    });
    const artMap = new Map();
    cellArtifactItems(md).forEach((it) => {
      if (artMap.has(it.resUrl)) return;
      const label = it.type
        ? it.type.charAt(0).toUpperCase() + it.type.slice(1)
        : "Artifact";
      artMap.set(it.resUrl, {
        kind: "artifact",
        id: it.name,
        url: it.local ? it.resUrl : it.url || it.resUrl,
        local: it.local,
        railLabel: label,
        size: it.size,
      });
    });
    if (artMap.size) groups.set("artifact", artMap);
    paintRail(groups, body, rail);
    promoteTrackioSpacesInRail(groups, dashResUrls, body, rail, token);
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
        let desc;
        if (kind === "artifact") {
          const state = item.local ? "publish to share" : "Open ↗";
          desc = item.size ? `${item.size} · ${state}` : state;
        } else if (kind === "dashboard") {
          desc = item.local ? "publish to share" : "Open ↗";
        } else {
          desc = item.local ? "publish to share" : RESOURCE_DESC[kind];
        }
        const kindLabel = item.railLabel || label.replace(/s$/, "");
        const iconHtml =
          kind === "artifact"
            ? ARTIFACT_ICON_IMG
            : kind === "dashboard"
              ? DASHBOARD_ICON_IMG
              : `<span>${icon}</span>`;
        el.innerHTML =
          `<div class="rail-kind">${iconHtml}${esc(kindLabel)}</div>` +
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

  function dashboardSubdomainFromUrl(url) {
    return spaceIdFromUrl(url).toLowerCase().replace(/[^a-z0-9-]/g, "-");
  }

  function dashboardOpenLink(head, url) {
    if (!head || !url) return;
    const meta = head.querySelector(".cell-meta");
    if (!meta) return;
    let link = meta.querySelector(".cell-open");
    if (!link) {
      link = document.createElement("a");
      link.className = "cell-open";
      link.target = "_blank";
      link.rel = "noopener";
      meta.insertBefore(link, meta.firstChild);
    }
    link.href = url;
    link.textContent = "Open ↗";
  }

  function dashboardFrame(src) {
    const iframe = document.createElement("iframe");
    iframe.className = "dashboard-frame";
    iframe.src = src;
    iframe.loading = "lazy";
    iframe.allow = "clipboard-read; clipboard-write; fullscreen";
    return iframe;
  }

  function renderDashboardCell(meta, body, container, head) {
    const project = meta.dashboard_project || "";
    const holder = document.createElement("div");
    holder.className = "dashboard-shell";
    container.appendChild(holder);
    const space = body.match(/https:\/\/huggingface\.co\/spaces\/[^\s<>)"'`]+/);
    if (space) {
      const url = space[0];
      dashboardOpenLink(head, url);
      holder.appendChild(
        dashboardFrame(
          `https://${dashboardSubdomainFromUrl(url)}.hf.space/?sidebar=hidden&hide_empty_tabs=true`
        )
      );
      return;
    }
    if (!isLocalPreview()) {
      holder.className = "artifact-chip";
      holder.dataset.resUrl = `trackio-local-dashboard://${project}`;
      holder.innerHTML =
        "🎯 <strong>Local Trackio dashboard</strong> — publish the logbook to share it";
      return;
    }
    const open = "/dashboard/?project=" + encodeURIComponent(project);
    dashboardOpenLink(head, open);
    holder.appendChild(
      dashboardFrame(open + "&sidebar=hidden&hide_empty_tabs=true"),
    );
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
      a.className = "depth-" + depth;
      a.dataset.slug = node.slug;
      const mark = document.createElement("span");
      mark.className = "tree-mark";
      mark.textContent = "§";
      a.appendChild(mark);
      a.appendChild(document.createTextNode(" " + node.title));
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
    const list = document.createElement("div");
    list.className = "pinned-notes-list";
    cells.forEach(({ meta, body }) => {
      const cell = renderCell(meta, body, list);
      cell.classList.add("pinned-copy");
    });
    deck.appendChild(list);
    const anchor =
      container.querySelector(".logbook-stats") ||
      container.querySelector(".agent-hint");
    container.insertBefore(deck, anchor ? anchor.nextSibling : container.firstChild);
    container.closest(".book-intro").classList.add("has-pinned-notes");
  }

  function removeIndexProse(body) {
    const h1 = Array.from(body.children).find((el) => el.tagName === "H1");
    if (!h1) return;
    let current = h1.nextElementSibling;
    while (current && current.tagName !== "H2") {
      const next = current.nextElementSibling;
      current.remove();
      current = next;
    }
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
        removeIndexProse(body);
        removePageDirectory(body);
        const hint = buildAgentHint();
        const h1 = body.querySelector("h1");
        if (h1 && h1.parentNode === body) {
          body.insertBefore(hint, h1.nextSibling);
        } else {
          body.prepend(hint);
        }
        hint.after(buildLogbookStats(markdown));
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
    if (bookIntroBody) {
      const section = bookIntroBody.closest(".book-intro");
      const hasExtra = Array.from(bookIntroBody.children).some(
        (el) =>
          el.tagName !== "H1" &&
          !el.classList.contains("agent-hint") &&
          !el.classList.contains("logbook-stats") &&
          !el.classList.contains("pinned-notes")
      );
      if (section && !section.classList.contains("has-pinned-notes") && !hasExtra) {
        section.classList.add("book-intro-tight");
      }
    }
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

  let STATS_TOKEN = 0;
  let STATS_LISTENERS = false;

  function fmtBytes(n) {
    if (n == null || isNaN(n)) return null;
    if (n < 1000) return `${n} B`;
    const units = ["kB", "MB", "GB", "TB"];
    let v = n;
    let i = -1;
    do {
      v /= 1000;
      i++;
    } while (v >= 1000 && i < units.length - 1);
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
  }

  function spaceIdFromUrl(url) {
    return url.split("/spaces/")[1].split(/[?#]/)[0].replace(/\/$/, "");
  }

  const LB_CELL_RE = /(^|\n)---\n<!-- trackio-cell\n([\s\S]*?)\n-->\n([\s\S]*?)(?=\n---\n<!-- trackio-cell\n|\s*$)/g;

  function cellDashboardItems(md) {
    const re = new RegExp(LB_CELL_RE.source, "g");
    const items = [];
    let m;
    while ((m = re.exec(md))) {
      const meta = parseCellMeta(m[2]);
      if (meta.type !== "dashboard") continue;
      const body = m[3];
      const project = meta.dashboard_project || "";
      const sp = body.match(/https:\/\/huggingface\.co\/spaces\/[^\s<>)"'`]+/);
      const local = !sp;
      const url = sp ? sp[0] : "";
      const resUrl = local ? `trackio-local-dashboard://${project}` : url;
      items.push({
        id: local ? project : spaceIdFromUrl(url),
        local,
        url,
        resUrl,
      });
    }
    return items;
  }

  function artifactInfoFromCell(meta, body) {
    const name = meta.artifact || meta.path || "";
    let size = null;
    const sm = body.match(/·\s*([\d.]+\s*[kMGT]?B)\b/);
    if (sm) size = sm[1].trim();
    if (!size && meta.size != null) size = fmtBytes(meta.size);
    const bucket = body.match(/https:\/\/huggingface\.co\/buckets\/[^\s<>)"'`]+/);
    const artUri = body.match(/trackio-artifact:\/\/\S+/);
    const pathUri = body.match(/trackio-local-path:\/\/\S+/);
    const url = bucket ? bucket[0] : "";
    const local = !bucket;
    const resUrl =
      url || (artUri ? artUri[0] : pathUri ? pathUri[0] : `trackio-artifact://${name}`);
    return {
      name,
      type: meta.artifact_type || "",
      size,
      local,
      isPathRef: !!meta.path,
      url,
      resUrl,
    };
  }

  function cellArtifactItems(md) {
    const re = new RegExp(LB_CELL_RE.source, "g");
    const items = [];
    let m;
    while ((m = re.exec(md))) {
      const meta = parseCellMeta(m[2]);
      const body = m[3];
      const order = meta.created_at || "";
      if (meta.type === "artifact") {
        const info = artifactInfoFromCell(meta, body);
        if (info.name) items.push({ ...info, order });
      }
    }
    return items;
  }

  function collectLogbookResources(markdownList) {
    const re = new RegExp(LB_CELL_RE.source, "g");
    const dashboards = new Map();
    markdownList.forEach((md) => {
      let m;
      while ((m = re.exec(md))) {
        const meta = parseCellMeta(m[2]);
        const body = m[3];
        if (meta.type !== "dashboard") continue;
        const project = meta.dashboard_project || "";
        const space = body.match(/https:\/\/huggingface\.co\/spaces\/[^\s<>)"'`]+/);
        const local = !space;
        const url = space ? space[0] : "";
        const key = local ? `local:${project}` : `space:${spaceIdFromUrl(url)}`;
        const resUrl = local ? `trackio-local-dashboard://${project}` : url;
        if (!dashboards.has(key))
          dashboards.set(key, { project, local, url, resUrl });
      }
    });
    const artifacts = new Map();
    markdownList.forEach((md) => {
      cellArtifactItems(md).forEach((it) => {
        const key = `${it.type}:${it.name}`;
        const prev = artifacts.get(key);
        if (!prev || it.order >= prev.order) artifacts.set(key, it);
      });
    });
    return {
      dashboards: Array.from(dashboards.values()).sort((a, b) =>
        a.project.localeCompare(b.project)
      ),
      artifacts: Array.from(artifacts.values()).sort((a, b) =>
        a.name.localeCompare(b.name)
      ),
    };
  }

  function closeStatPopovers() {
    document
      .querySelectorAll(".stat-popover")
      .forEach((p) => (p.hidden = true));
    document
      .querySelectorAll(".stat-tile.open")
      .forEach((t) => t.classList.remove("open"));
  }

  function ensureStatListeners() {
    if (STATS_LISTENERS) return;
    STATS_LISTENERS = true;
    document.addEventListener("click", closeStatPopovers);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeStatPopovers();
    });
  }

  function stateHtml(remote, url) {
    return remote
      ? `<a class="stat-row-state open" href="${esc(url)}" target="_blank" rel="noopener" title="Open in a new tab">Open ↗</a>`
      : `<span class="stat-row-state">publish to share</span>`;
  }

  function scrollToResource(resUrl) {
    closeStatPopovers();
    if (!resUrl) return;
    const el = document.querySelector(
      `#page .page-body [data-res-url="${CSS.escape(resUrl)}"]:not(.stat-row)`
    );
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("res-flash");
    setTimeout(() => el.classList.remove("res-flash"), 1500);
  }

  function dashRowHtml(d) {
    const inner =
      `<span class="stat-row-ico">${DASHBOARD_ICON_IMG}</span>` +
      `<div class="stat-row-main"><div class="stat-row-title">${esc(d.project)}</div>` +
      `<div class="stat-row-meta">${stateHtml(!d.local, d.url)}</div></div>`;
    return `<div class="stat-row" data-res-url="${esc(d.resUrl)}" title="Jump to it in the logbook">${inner}</div>`;
  }

  function artRowHtml(a) {
    const remote = !a.local && !!a.url;
    const parts = [a.type, a.size].filter(Boolean).map(esc);
    const meta = parts.length
      ? `${parts.join(" · ")} · ${stateHtml(remote, a.url)}`
      : stateHtml(remote, a.url);
    const inner =
      `<span class="stat-row-ico">${ARTIFACT_ICON_IMG}</span>` +
      `<div class="stat-row-main"><div class="stat-row-title">${esc(a.name)}</div>` +
      `<div class="stat-row-meta">${meta}</div></div>`;
    return `<div class="stat-row" data-res-url="${esc(a.resUrl)}" title="Jump to it in the logbook">${inner}</div>`;
  }

  function statTile(icon, alt, singular, plural, head, rowFn) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "stat-tile";
    const render = (items) => {
      const count = items.length;
      const label = count === 1 ? singular : plural;
      const caret = count > 0 ? `<span class="stat-caret">▾</span>` : "";
      tile.innerHTML =
        `<img class="stat-icon" src="${icon}" alt="${esc(alt)}" />` +
        `<div class="stat-text"><div class="stat-num">${count}</div>` +
        `<div class="stat-label">${esc(label)}</div></div>` +
        caret;
      tile.disabled = count === 0;
      if (count > 0) {
        const pop = document.createElement("div");
        pop.className = "stat-popover";
        pop.hidden = true;
        pop.innerHTML =
          `<div class="stat-pop-head">${esc(head)}</div>` +
          items.map(rowFn).join("");
        pop.addEventListener("click", (e) => {
          if (e.target.closest("a.stat-row-state")) {
            e.stopPropagation();
            return;
          }
          e.stopPropagation();
          const row = e.target.closest(".stat-row");
          if (row) scrollToResource(row.dataset.resUrl);
        });
        tile.appendChild(pop);
      }
    };
    tile.addEventListener("click", (e) => {
      if (tile.disabled) return;
      e.stopPropagation();
      const pop = tile.querySelector(".stat-popover");
      if (!pop) return;
      const isOpen = !pop.hidden;
      closeStatPopovers();
      if (!isOpen) {
        pop.hidden = false;
        tile.classList.add("open");
      }
    });
    return { tile, render };
  }

  function buildLogbookStats(markdownList) {
    const token = ++STATS_TOKEN;
    ensureStatListeners();
    const { dashboards, artifacts } = collectLogbookResources(markdownList);

    const el = document.createElement("div");
    el.className = "logbook-stats";
    const dash = statTile(
      "./trackio-logo-light.png",
      "Trackio",
      "Trackio Dashboard",
      "Trackio Dashboards",
      "Dashboards created in this logbook",
      dashRowHtml
    );
    const art = statTile(
      "./bucket-icon.svg",
      "Bucket",
      "Artifact",
      "Artifacts",
      "Artifacts created in this logbook",
      artRowHtml
    );
    dash.render(dashboards);
    art.render(artifacts);
    el.appendChild(dash.tile);
    el.appendChild(art.tile);

    const scanText = markdownList
      .map((md) =>
        md.replace(/(`{3,4}|~{3,4})(html|raw)[^\n]*\n[\s\S]*?\n\1/g, " ")
      )
      .join("\n");
    const seen = new Set(
      dashboards.map((d) =>
        d.local ? `local:${d.project}` : `space:${spaceIdFromUrl(d.url)}`
      )
    );
    const remoteSpaces = new Map();
    extractUrls(scanText).forEach((url) => {
      const item = classifyResource(url);
      if (item && item.kind === "space" && !item.local) {
        remoteSpaces.set(item.url, item);
      }
    });
    remoteSpaces.forEach((s) => {
      const key = `space:${s.id}`;
      if (seen.has(key)) return;
      getJSON(`https://huggingface.co/api/spaces/${s.id}`)
        .then((d) => {
          if (STATS_TOKEN !== token) return;
          const tags = (d && d.tags) || [];
          if (
            !seen.has(key) &&
            tags.some((t) => String(t).toLowerCase() === "trackio")
          ) {
            seen.add(key);
            dashboards.push({
              project: s.id,
              local: false,
              url: s.url,
              resUrl: s.url,
            });
            dashboards.sort((a, b) => a.project.localeCompare(b.project));
            dash.render(dashboards);
          }
        })
        .catch(() => {});
    });
    return el;
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

  function navigateToLogbookSlug(target) {
    const slug = String(target || "").replace(/^#?\//, "").trim();
    if (!slug || !findNode(MANIFEST.root, slug)) return;
    const hash = "#/" + slug;
    if (location.hash === hash) {
      scrollToHash({ behavior: "smooth" });
    } else {
      location.hash = hash;
    }
  }

  function setupFigureNavigation() {
    window.addEventListener("message", (event) => {
      const data = event.data;
      if (!data || data.type !== "trackio-logbook:navigate") return;
      // Only accept messages from one of this logbook's sandboxed figure
      // iframes, rather than from an arbitrary same-origin page.
      const isFigureFrame = Array.from(
        document.querySelectorAll("iframe.figure-frame")
      ).some((frame) => frame.contentWindow === event.source);
      if (!isFigureFrame) return;
      navigateToLogbookSlug(data.target);
    });
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
        document.getElementById("book-head").setAttribute("aria-label", MANIFEST.title);
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
    document.getElementById("book-head").setAttribute("aria-label", MANIFEST.title);
    document.getElementById("book-head").addEventListener("click", () => {
      const target = "#/" + MANIFEST.root.slug;
      if (location.hash === target) scrollToHash();
      else location.hash = target;
    });
    buildTree();
    setupConnect();
    setupResourceHover();
    setupFigureNavigation();
    window.addEventListener("hashchange", () => scrollToHash());
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    await renderLogbook();
    startLiveReload();
  }

  init();
})();
