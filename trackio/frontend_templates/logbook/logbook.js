(function () {
  "use strict";

  let MANIFEST = null;
  const PAGE_CACHE = {};
  const UNFURL_CACHE = {};
  const DATA_CACHE = {};
  const LIVE_RELOAD_MS = 1500;
  const FIGURE_FRAME_WINDOWS = new Set();
  let FIGURE_NAVIGATION_READY = false;
  let CURRENT_VIEW = null;
  let RENDER_SEQUENCE = 0;

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
      if (chip && meta.path) {
        const ico = chip.querySelector(".art-ico");
        if (ico) ico.outerHTML = FILE_ICON;
      }
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
      const hash = "#/view/code/" + target;
      if (location.hash === hash) scrollToHash();
      else location.hash = hash;
    });
  }

  const FULLSCREEN_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"/>' +
    '<path d="M3 8 8 3M16 3l5 5M21 16l-5 5M8 21l-5-5"/></svg>';

  const PIN_ICON =
    '<svg class="pin-ico" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 ' +
    '1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/></svg>';

  const FILE_ICON =
    '<svg class="art-file-ico" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M6 3.5h8l4 4V20H6zM14 3.5V8h4"/></svg>';

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
    const icon = info.isPathRef ? FILE_ICON : ARTIFACT_ICON_IMG;
    el.innerHTML =
      `<span class="out-artifact-ico">${icon}</span>` +
      `<span class="out-artifact-name">${esc(info.name)}</span>` +
      `<span class="out-artifact-meta">${meta}</span>`;
    return el;
  }

  function isShellCommand(part) {
    return (
      part.kind === "code" &&
      part.lang === "bash" &&
      !part.title &&
      /^\s*\$\s/.test(part.text)
    );
  }

  function renderCommandLine(text) {
    const command = text.trim().replace(/^\$\s*/, "");
    const el = document.createElement("div");
    el.className = "jp-cmd";
    const prompt = document.createElement("span");
    prompt.className = "jp-cmd-prompt";
    prompt.textContent = "$";
    const code = document.createElement("code");
    code.textContent = command;
    el.appendChild(prompt);
    el.appendChild(code);
    el.appendChild(copySnippetBtn(command));
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
      if (isShellCommand(part)) {
        inputBody.appendChild(renderCommandLine(part.text));
      } else {
        inputBody.appendChild(
          renderCode(part.text, part.lang, part.title, Boolean(part.title))
        );
      }
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

  function renderCode(code, lang, title, open) {
    const pre = document.createElement("pre");
    pre.className = "hl";
    const c = document.createElement("code");
    c.innerHTML = highlightCode(code, lang);
    pre.appendChild(c);
    if (!title || open) {
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

  /* -------------------- resource classification -------------------- */

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
    const label = document.createElement("div");
    label.className = "tree-label";
    label.textContent = "Pages";
    tree.appendChild(label);
    const nodes = [];
    (MANIFEST.root.children || []).forEach((c) => flattenTree(c, 0, nodes));
    nodes.forEach(({ node, depth }) => {
      const a = document.createElement("a");
      a.href = "#/view/code/" + node.slug;
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

  function highlightTraceSession(sessionId) {
    document.querySelectorAll("#tree a").forEach((link) => {
      link.classList.toggle("active", link.dataset.sessionId === sessionId);
    });
  }

  function buildTraceTree(activeSessionId) {
    const tree = document.getElementById("tree");
    tree.innerHTML = "";
    const sessions = MANIFEST.traces || [];
    if (!sessions.length) return;
    const label = document.createElement("div");
    label.className = "tree-label";
    label.textContent = "Sessions";
    tree.appendChild(label);
    sessions.forEach((session) => {
      const link = document.createElement("a");
      link.href = "#" + traceSessionAnchor(session.id);
      link.dataset.sessionId = session.id;
      link.textContent = session.title || session.id;
      link.title = session.title || session.id;
      tree.appendChild(link);
    });
    highlightTraceSession(activeSessionId || sessions[0].id);
  }

  function renderSidebar(route) {
    if (route.view === "trace") {
      highlight(null);
      buildTraceTree(route.sessionId);
      return;
    }
    if (route.view === "workspace") {
      document.getElementById("tree").innerHTML = "";
      highlight(null);
      return;
    }
    buildTree();
    highlight(route.slug);
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
    Object.keys(DATA_CACHE).forEach((key) => {
      delete DATA_CACHE[key];
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

  async function fetchData(file, cacheResult = true) {
    if (cacheResult && DATA_CACHE[file]) return DATA_CACHE[file];
    const suffix = isLocalPreview()
      ? `?rev=${encodeURIComponent(MANIFEST.revision || "")}`
      : "";
    const response = await fetch("./" + file + suffix, { cache: "no-store" });
    if (!response.ok) throw new Error(`Could not load ${file}`);
    const data = await response.json();
    if (cacheResult) DATA_CACHE[file] = data;
    return data;
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
      const title = cell.querySelector(".cell-title");
      if (title) title.insertAdjacentHTML("afterbegin", PIN_ICON);
    });
    deck.appendChild(list);
    const anchor =
      container.querySelector(".agent-hint") ||
      Array.from(container.children).find((el) => el.tagName === "H1");
    container.insertBefore(deck, anchor ? anchor.nextSibling : container.firstChild);
    const owner = container.closest(".page-section");
    if (owner) owner.classList.add("has-pinned-notes");
  }

  function isIndexPaperLink(el) {
    if (!el || el.tagName !== "P") return false;
    return Array.from(el.querySelectorAll("a[href]")).some((a) => {
      const href = a.getAttribute("href") || "";
      return (
        /huggingface\.co\/papers\//.test(href) ||
        /openreview\.net\//.test(href) ||
        /arxiv\.org\//.test(href)
      );
    });
  }

  function removeIndexProse(body) {
    const h1 = Array.from(body.children).find((el) => el.tagName === "H1");
    if (!h1) return;
    let current = h1.nextElementSibling;
    while (current && current.tagName !== "H2") {
      const next = current.nextElementSibling;
      if (isIndexPaperLink(current)) {
        current.classList.add("index-paper-link");
      } else {
        current.remove();
      }
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

  async function renderLogbook(opts = {}) {
    const scrollY = window.scrollY;
    const page = document.getElementById("page");
    page.innerHTML = "";
    const nodes = allNodes();
    const markdown = await Promise.all(nodes.map(fetchPage));
    if (opts.renderId && opts.renderId !== RENDER_SEQUENCE) return;
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

      renderMarkdown(markdown[index], body);
      if (node.slug === MANIFEST.root.slug) {
        section.classList.add("book-intro");
        removeIndexProse(body);
        removePageDirectory(body);
        const h1 = body.querySelector("h1");
        if (h1 && h1.parentNode === body) h1.remove();
        bookIntroBody = body;
      }
      layout.appendChild(body);
      section.appendChild(layout);
      page.appendChild(section);
    });
    const pinnedSlugs = Array.from(
      new Set(pinnedCells.map((cell) => cell.node && cell.node.slug).filter(Boolean))
    );
    const pinnedTarget =
      pinnedSlugs.length === 1
        ? Array.from(page.querySelectorAll(".page-section"))
            .find((section) => section.dataset.slug === pinnedSlugs[0])
            ?.querySelector(".page-body")
        : bookIntroBody;
    if (pinnedTarget) renderPinnedNotes(pinnedCells, pinnedTarget);
    // Pinned cells are promoted into one deck. Remove their source render so
    // summaries, posters, and notes do not appear twice in the continuous view.
    page
      .querySelectorAll(".pinned-source:not(.pinned-copy)")
      .forEach((cell) => cell.remove());
    if (bookIntroBody) {
      const section = bookIntroBody.closest(".book-intro");
      const hasExtra = Array.from(bookIntroBody.children).some(
        (el) =>
          el.tagName !== "H1" &&
          !el.classList.contains("agent-hint") &&
          !el.classList.contains("index-paper-link") &&
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

  const VIEW_ROUTE = { trace: "#/view/trace", workspace: "#/view/workspace" };
  const VIEW_TOKENS = {
    code: "agent_view_tokens",
    trace: "trace_view_tokens",
    workspace: "workspace_view_tokens",
  };

  function readTarget(view) {
    const onSpaces =
      /\.hf\.space$/.test(location.hostname) ||
      /(^|\.)huggingface\.co$/.test(location.hostname);
    let base = "";
    if (onSpaces && MANIFEST.space_id) base = MANIFEST.space_id;
    else if (/^https?:$/.test(location.protocol))
      base = `${location.origin}${location.pathname}`;
    if (!base) return "";
    return base + (VIEW_ROUTE[view] || "");
  }

  function renderLogbookHeader(view) {
    const title = document.getElementById("logbook-title");
    if (title) title.textContent = MANIFEST.title;
    const cli = document.getElementById("logbook-cli");
    if (!cli) return;
    cli.innerHTML = "";
    cli.appendChild(buildAgentHint(view));
    const destination = buildHubDestinationLink(view);
    if (destination) cli.appendChild(destination);
  }

  function hubDestination(view) {
    if (view === "trace" && MANIFEST.trace_dataset) {
      return {
        label: "View Hugging Face dataset:",
        url: MANIFEST.trace_dataset,
        fallback: "Agent Traces dataset",
      };
    }
    if (view === "workspace") {
      const bucketId = (MANIFEST.workspace || {}).bucket_id;
      const url =
        MANIFEST.workspace_bucket ||
        (bucketId ? `https://huggingface.co/buckets/${bucketId}` : "");
      if (url) {
        return {
          label: "View Hugging Face Bucket:",
          url,
          fallback: "Workspace Bucket",
        };
      }
    }
    return null;
  }

  function buildHubDestinationLink(view) {
    const destination = hubDestination(view);
    if (!destination || !destination.url.startsWith("https://huggingface.co/")) {
      return null;
    }
    const row = document.createElement("div");
    row.className = "hub-destination";
    const label = document.createElement("span");
    label.textContent = destination.label;
    const link = document.createElement("a");
    link.href = destination.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent =
      destination.url
        .replace(/^https:\/\/huggingface\.co\/(?:datasets|buckets)\//, "")
        .replace(/\/$/, "") || destination.fallback;
    link.title = destination.url;
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M14 5h5v5M19 5l-8 8M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5");
    icon.appendChild(path);
    link.appendChild(icon);
    row.appendChild(label);
    row.appendChild(link);
    return row;
  }

  function buildAgentHint(view) {
    const target = readTarget(view);
    const command = `trackio logbook read${target ? ` ${target}` : ""}`;
    const tokens = MANIFEST[VIEW_TOKENS[view] || VIEW_TOKENS.code];
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

  function routeState() {
    const raw = (location.hash || "").replace(/^#\/?/, "");
    if (!raw) return { view: "code", slug: MANIFEST.root.slug };
    const parts = raw.split("/");
    if (parts[0] !== "view") {
      const slug = findNode(MANIFEST.root, raw) ? raw : MANIFEST.root.slug;
      return { view: "code", slug };
    }
    if (parts[1] === "trace") {
      return { view: "trace", sessionId: parts.slice(2).join("/") || null };
    }
    if (parts[1] === "workspace") return { view: "workspace" };
    const candidate = parts.slice(2).join("/") || MANIFEST.root.slug;
    return {
      view: "code",
      slug: findNode(MANIFEST.root, candidate) ? candidate : MANIFEST.root.slug,
    };
  }

  function updateViewTabs(route = routeState()) {
    document.querySelectorAll("#view-tabs a").forEach((tab) => {
      const view = tab.dataset.view;
      tab.classList.toggle("active", view === route.view);
      tab.setAttribute("aria-current", view === route.view ? "page" : "false");
      if (view === "code") {
        const slug = route.view === "code" ? route.slug : MANIFEST.root.slug;
        tab.href = `#/view/code/${slug}`;
      } else if (view === "trace") {
        tab.href = "#/view/trace";
      }
    });
  }

  function setActiveView(route) {
    CURRENT_VIEW = route.view;
    document.body.dataset.view = route.view;
    updateViewTabs(route);
    renderLogbookHeader(route.view);
    renderSidebar(route);
  }

  function formatDuration(ms) {
    if (ms == null || isNaN(ms)) return "—";
    const total = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours) return `${hours}h ${minutes}m ${seconds}s`;
    if (minutes) return `${minutes}m ${seconds}s`;
    return `${seconds}s`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (isNaN(date.getTime())) return value;
    return date.toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function emptyView(title, text, command) {
    const empty = document.createElement("div");
    empty.className = "view-empty";
    const heading = document.createElement("h2");
    heading.textContent = title;
    const body = document.createElement("p");
    body.textContent = text;
    empty.appendChild(heading);
    empty.appendChild(body);
    if (command) {
      const code = document.createElement("code");
      code.textContent = command;
      empty.appendChild(code);
    }
    return empty;
  }

  function traceEventLabel(event) {
    if (event.kind === "reasoning") return "Thought";
    if (event.kind === "tool_call") return event.tool_name || event.title || "Tool";
    if (event.kind === "tool_result") return "Tool output";
    return event.title || event.kind || "Event";
  }

  function appendTraceResult(entry, result) {
    if (!entry || !result || !result.output) return;
    const card = entry.querySelector(".trace-card");
    if (!card) return;
    const details = document.createElement("details");
    details.className = "trace-output";
    const summary = document.createElement("summary");
    summary.textContent = result.status === "error" ? "Error output" : "Output";
    const output = document.createElement("pre");
    output.textContent = result.output;
    details.appendChild(summary);
    details.appendChild(output);
    card.appendChild(details);
  }

  function traceEventCard(event, result) {
    const entry = document.createElement("div");
    entry.className = `trace-entry trace-${event.kind || "status"}`;
    entry.style.setProperty("--trace-depth", Math.min(Number(event.depth) || 0, 4));

    const rail = document.createElement("div");
    rail.className = "trace-rail";
    const number = document.createElement("span");
    number.className = "trace-number";
    number.textContent = `#${event.sequence || ""}`;
    const dot = document.createElement("span");
    dot.className = "trace-dot";
    const elapsed = document.createElement("span");
    elapsed.className = "trace-elapsed";
    elapsed.textContent = formatDuration(event.elapsed_ms);
    rail.appendChild(number);
    rail.appendChild(dot);
    rail.appendChild(elapsed);

    const card = document.createElement("article");
    card.className = "trace-card";
    const head = document.createElement("header");
    const kind = document.createElement("span");
    kind.className = "trace-kind";
    kind.textContent = traceEventLabel(event);
    head.appendChild(kind);
    if (event.turn) {
      const turn = document.createElement("span");
      turn.className = "trace-turn";
      turn.textContent = `turn ${event.turn}`;
      head.appendChild(turn);
    }
    card.appendChild(head);

    const bodyText = event.text || event.input || event.output;
    if (bodyText) {
      const body = document.createElement(
        event.kind === "tool_call" || event.kind === "tool_result" ? "pre" : "div"
      );
      body.className = "trace-body";
      body.textContent = bodyText;
      card.appendChild(body);
    }
    if (event.status) {
      const status = document.createElement("span");
      status.className = `trace-status-badge trace-status-badge-${event.status}`;
      status.textContent = String(event.status).replace(/_/g, " ");
      head.appendChild(status);
    }
    entry.appendChild(rail);
    entry.appendChild(card);
    appendTraceResult(entry, result);
    return entry;
  }

  function traceSessionAnchor(id) {
    return "/view/trace/" + id;
  }

  function buildTraceSession(session, index) {
    const sec = document.createElement("section");
    sec.className = "trace-session";
    sec.id = traceSessionAnchor(session.id);
    sec.dataset.sessionId = session.id;

    const title = document.createElement("h2");
    title.className = "trace-session-title";
    title.textContent = session.title || session.id;
    sec.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "trace-meta";
    [
      ["Started", formatDate(index.started_at)],
      ["Ended", formatDate(index.ended_at)],
      ["Duration", formatDuration(index.duration_ms)],
      ["Events", String(index.event_count || 0)],
    ].forEach(([label, value]) => {
      const item = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = label;
      item.appendChild(strong);
      item.appendChild(document.createTextNode(` ${value}`));
      meta.appendChild(item);
    });
    if (index.model) {
      const model = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = "Model";
      model.appendChild(strong);
      model.appendChild(document.createTextNode(` ${index.model}`));
      meta.appendChild(model);
    }
    if (index.source_available === false) {
      const missing = document.createElement("span");
      missing.className = "trace-source-missing";
      missing.textContent = "Source file unavailable · showing last capture";
      meta.appendChild(missing);
    }
    sec.appendChild(meta);

    const timeline = document.createElement("section");
    timeline.className = "trace-timeline";
    sec.appendChild(timeline);

    const chunks = index.chunks || [];
    if (!chunks.length) {
      timeline.appendChild(
        emptyView("Empty trace", "No displayable events were found in this session.")
      );
      return sec;
    }

    const controls = document.createElement("div");
    controls.className = "trace-load-controls";
    const progress = document.createElement("span");
    progress.className = "trace-load-progress";
    const loadMore = document.createElement("button");
    loadMore.type = "button";
    loadMore.className = "trace-load-more";
    controls.appendChild(progress);
    controls.appendChild(loadMore);
    sec.appendChild(controls);

    let nextChunk = 0;
    let loadedEvents = 0;
    let loading = false;
    const pendingCalls = new Map();

    function updateLoadControls() {
      const total = Number(index.event_count) || chunks.reduce(
        (sum, chunk) => sum + (Number(chunk.count) || 0),
        0
      );
      progress.textContent = `${Math.min(loadedEvents, total)} of ${total} events loaded`;
      if (nextChunk >= chunks.length) {
        loadMore.textContent = "All events loaded";
        loadMore.disabled = true;
        return;
      }
      const count = Number(chunks[nextChunk].count) || "next";
      loadMore.textContent = `Load ${count} more events`;
      loadMore.disabled = false;
    }

    async function loadNextTraceChunk() {
      if (loading || nextChunk >= chunks.length) return;
      loading = true;
      loadMore.disabled = true;
      loadMore.textContent = "Loading…";
      const descriptor = chunks[nextChunk];
      try {
        // Event chunks can be large. Do not retain the parsed JSON in DATA_CACHE;
        // the rendered DOM is the only long-lived copy.
        const chunk = await fetchData(descriptor.file, false);
        const events = chunk.events || [];
        events.forEach((event) => {
          if (
            event.kind === "tool_result" &&
            event.call_id &&
            pendingCalls.has(event.call_id)
          ) {
            appendTraceResult(pendingCalls.get(event.call_id), event);
            pendingCalls.delete(event.call_id);
            return;
          }
          const entry = traceEventCard(event);
          timeline.appendChild(entry);
          if (event.kind === "tool_call" && event.call_id) {
            pendingCalls.set(event.call_id, entry);
          }
        });
        loadedEvents += events.length;
        nextChunk += 1;
        sec.dataset.loadedChunks = String(nextChunk);
        updateLoadControls();
      } catch (error) {
        progress.textContent = "Could not load the next trace segment.";
        loadMore.textContent = "Retry";
        loadMore.disabled = false;
      } finally {
        loading = false;
      }
    }

    sec.dataset.loadedChunks = "0";
    sec.loadNextTraceChunk = loadNextTraceChunk;
    loadMore.addEventListener("click", loadNextTraceChunk);
    updateLoadControls();
    return sec;
  }

  function ensureTraceSessionLoaded(sessionId) {
    const target = document.getElementById(traceSessionAnchor(sessionId));
    if (
      target &&
      target.dataset.loadedChunks === "0" &&
      typeof target.loadNextTraceChunk === "function"
    ) {
      return target.loadNextTraceChunk();
    }
    return Promise.resolve();
  }

  function scrollToTraceSession(sessionId) {
    if (!sessionId) {
      window.scrollTo({ top: 0, behavior: "auto" });
      return;
    }
    const target = document.getElementById(traceSessionAnchor(sessionId));
    if (target) target.scrollIntoView({ behavior: "auto" });
    else window.scrollTo({ top: 0, behavior: "auto" });
  }

  async function renderTrace(route, renderId) {
    const page = document.getElementById("page");
    page.innerHTML = "";
    page.className = "trace-page";
    const sessions = MANIFEST.traces || [];
    if (!sessions.length) {
      page.appendChild(
        emptyView(
          "No trace attached",
          "Attach an agent session file to add its chronological trace to this logbook.",
          "trackio logbook attach trace <filepath>"
        )
      );
      return;
    }
    updateViewTabs({ view: "trace" });

    const loading = document.createElement("div");
    loading.className = "view-loading";
    loading.textContent = "Loading traces…";
    page.appendChild(loading);
    let loaded;
    try {
      loaded = await Promise.all(
        sessions.map(async (session) => {
          const index = await fetchData(session.index_file);
          return { session, index };
        })
      );
    } catch (error) {
      if (renderId !== RENDER_SEQUENCE) return;
      page.innerHTML = "";
      page.appendChild(
        emptyView("Trace unavailable", "The normalized traces could not be loaded.")
      );
      return;
    }
    if (renderId !== RENDER_SEQUENCE) return;
    page.innerHTML = "";

    const shell = document.createElement("div");
    shell.className = "trace-shell";
    loaded.forEach(({ session, index }) => {
      shell.appendChild(buildTraceSession(session, index));
    });
    page.appendChild(shell);
    const activeSessionId = route.sessionId || sessions[0].id;
    await ensureTraceSessionLoaded(activeSessionId);
    if (renderId !== RENDER_SEQUENCE) return;
    scrollToTraceSession(activeSessionId);
  }

  function svgIcon(kind) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      kind === "folder"
        ? "M3.5 6.5h6l2 2h9v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"
        : kind === "download"
          ? "M12 3v12m0 0 4-4m-4 4-4-4M5 20h14"
          : "M6 3.5h8l4 4V20H6zM14 3.5V8h4"
    );
    svg.appendChild(path);
    return svg;
  }

  function workspaceTree(files) {
    const root = { directories: new Map(), files: [] };
    files.forEach((file) => {
      const parts = file.path.split("/");
      let cursor = root;
      parts.slice(0, -1).forEach((name) => {
        if (!cursor.directories.has(name)) {
          cursor.directories.set(name, { directories: new Map(), files: [] });
        }
        cursor = cursor.directories.get(name);
      });
      cursor.files.push(file);
    });
    return root;
  }

  function workspaceFileRow(file) {
    const row = document.createElement("div");
    row.className = "workspace-file";
    const name = document.createElement("div");
    name.className = "workspace-file-name";
    name.appendChild(svgIcon("file"));
    const label = document.createElement("span");
    label.textContent = file.name;
    label.title = file.path;
    name.appendChild(label);
    const type = document.createElement("span");
    type.className = "workspace-file-type";
    type.textContent = file.type || "file";
    const size = document.createElement("span");
    size.className = "workspace-file-size";
    size.textContent = fmtBytes(file.size) || "—";
    const modified = document.createElement("time");
    modified.className = "workspace-file-time";
    modified.dateTime = file.modified_at || "";
    modified.textContent = formatDate(file.modified_at);
    row.appendChild(name);
    row.appendChild(type);
    row.appendChild(size);
    row.appendChild(modified);
    const url =
      isLocalPreview() && file.local_url
        ? file.local_url
        : file.download_url || file.bucket_url;
    if (url) {
      const download = document.createElement("a");
      download.className = "workspace-download";
      download.href = url;
      download.title = "Download";
      download.setAttribute("aria-label", `Download ${file.name}`);
      if (isLocalPreview() && file.local_url) download.download = file.name;
      download.appendChild(svgIcon("download"));
      row.appendChild(download);
    } else {
      const pending = document.createElement("span");
      pending.className = "workspace-unpublished";
      pending.textContent = "Local";
      row.appendChild(pending);
    }
    return row;
  }

  function renderWorkspaceNode(node, container) {
    Array.from(node.directories.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .forEach(([name, child]) => {
        const details = document.createElement("details");
        details.className = "workspace-folder";
        details.open = true;
        const summary = document.createElement("summary");
        summary.appendChild(svgIcon("folder"));
        const label = document.createElement("span");
        label.textContent = name;
        summary.appendChild(label);
        details.appendChild(summary);
        const children = document.createElement("div");
        children.className = "workspace-folder-children";
        renderWorkspaceNode(child, children);
        details.appendChild(children);
        container.appendChild(details);
      });
    node.files
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((file) => container.appendChild(workspaceFileRow(file)));
  }

  async function renderWorkspace(renderId) {
    const page = document.getElementById("page");
    page.innerHTML = "";
    page.className = "workspace-page";
    const loading = document.createElement("div");
    loading.className = "view-loading";
    loading.textContent = "Loading workspace…";
    page.appendChild(loading);
    let workspace;
    try {
      workspace = await fetchData((MANIFEST.workspace || {}).file || "workspace.json");
    } catch (error) {
      if (renderId !== RENDER_SEQUENCE) return;
      page.innerHTML = "";
      page.appendChild(emptyView("Workspace unavailable", "The workspace inventory could not be loaded."));
      return;
    }
    if (renderId !== RENDER_SEQUENCE) return;
    page.innerHTML = "";
    const shell = document.createElement("div");
    shell.className = "workspace-shell";
    const header = document.createElement("header");
    header.className = "workspace-header";
    const summary = document.createElement("p");
    summary.textContent = `${workspace.file_count || 0} files · ${fmtBytes(workspace.total_size || 0)}`;
    header.appendChild(summary);
    shell.appendChild(header);
    if (!(workspace.files || []).length) {
      shell.appendChild(
        emptyView(
          "No workspace files yet",
          "Supported model and data files created or changed after a trace was attached will appear here."
        )
      );
    } else {
      const inventory = document.createElement("section");
      inventory.className = "workspace-inventory";
      renderWorkspaceNode(workspaceTree(workspace.files), inventory);
      shell.appendChild(inventory);
    }
    page.appendChild(shell);
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  async function renderCurrentView(opts = {}) {
    const route = routeState();
    const renderId = ++RENDER_SEQUENCE;
    setActiveView(route);
    if (route.view === "trace") {
      await renderTrace(route, renderId);
    } else if (route.view === "workspace") {
      await renderWorkspace(renderId);
    } else {
      document.getElementById("page").className = "code-page";
      await renderLogbook({ ...opts, renderId });
    }
  }

  function handleRouteChange() {
    const route = routeState();
    if (
      route.view === "code" &&
      CURRENT_VIEW === "code" &&
      document.querySelector("#page .page-section")
    ) {
      updateViewTabs(route);
      scrollToHash();
      return;
    }
    if (
      route.view === "trace" &&
      CURRENT_VIEW === "trace" &&
      document.querySelector("#page .trace-session")
    ) {
      setActiveView(route);
      const sessions = MANIFEST.traces || [];
      const activeSessionId = route.sessionId || (sessions[0] || {}).id;
      ensureTraceSessionLoaded(activeSessionId);
      scrollToTraceSession(activeSessionId);
      return;
    }
    renderCurrentView();
  }

  function currentSlug() {
    const route = routeState();
    return route.view === "code" ? route.slug : MANIFEST.root.slug;
  }

  function scrollToHash(opts = {}) {
    if (routeState().view !== "code") return;
    const slug = currentSlug();
    if (!location.hash || slug === MANIFEST.root.slug) {
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
    const hash = "#/view/code/" + slug;
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
    if (CURRENT_VIEW !== "code" && CURRENT_VIEW !== "trace") return;
    cancelAnimationFrame(SCROLL_FRAME);
    SCROLL_FRAME = requestAnimationFrame(() => {
      const selector =
        CURRENT_VIEW === "trace" ? ".trace-session" : ".page-section";
      const sections = Array.from(document.querySelectorAll(selector));
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
      if (CURRENT_VIEW === "trace") {
        highlightTraceSession(active.dataset.sessionId);
      } else {
        highlight(active.dataset.slug);
      }
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
        renderCurrentView({ preserveScroll: true });
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
      const target = "#/view/code/" + MANIFEST.root.slug;
      if (location.hash === target) scrollToHash();
      else location.hash = target;
    });
    buildTree();
    setupConnect();
    setupFigureNavigation();
    window.addEventListener("hashchange", handleRouteChange);
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    await renderCurrentView();
    startLiveReload();
  }

  init();
})();
