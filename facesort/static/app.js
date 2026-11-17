"use strict";
/* facesort: giao diện thuần JS, không build, không CDN. Mọi dữ liệu hiển thị qua textContent. */

const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const S = {
  status: null, config: null, projects: [], current: null, labels: [],
  filter: "all", hideDone: true, page: 1, items: [], total: 0,
  focus: 0, fresh: null, polling: null, facesCache: {}, lastJob: null,
};

const STEP_TEXT = {
  start: "Đang bắt đầu…",
  scan: "Đang quét ảnh",
  model: "Đang nạp model nhận diện (lần đầu sẽ tải về, có thể mất vài phút)",
  detect: "Đang tìm khuôn mặt",
  cluster: "Đang gom nhóm",
  plan: "Đang lập kế hoạch copy",
  export: "Đang copy ảnh",
};

/* ---------------------------------------------------------------- tiện ích */

async function api(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Mất kết nối tới facesort. Kiểm tra cửa sổ lệnh còn chạy không.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* không phải JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Lỗi ${res.status}`);
  return data;
}

function toast(msg, opts = {}) {
  const box = $("#toasts");
  const t = h("div", { class: "toast" + (opts.error ? " error" : "") }, h("span", {}, msg));
  if (opts.undo) {
    t.append(h("button", { onclick: () => { doUndo(); t.remove(); } }, "Hoàn tác"));
  }
  box.append(t);
  setTimeout(() => t.remove(), opts.error ? 7000 : 4000);
}

function fmtBytes(n) {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtEta(s) {
  if (s == null) return "";
  if (s < 60) return "còn dưới 1 phút";
  if (s < 3600) return `còn khoảng ${Math.round(s / 60)} phút`;
  return `còn khoảng ${Math.floor(s / 3600)} giờ ${Math.round((s % 3600) / 60)} phút`;
}

const num = (n) => Number(n).toLocaleString("vi-VN");
const faceUrl = (id) => `/thumbs/faces/${id}.jpg`;

/* ---------------------------------------------------------------- khởi động */

async function boot() {
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", onKey);
  $("#projectSelect").addEventListener("change", async (e) => {
    try {
      await api("POST", "/api/projects/select", { name: e.target.value });
      await refreshAll();
      route();
    } catch (err) { toast(err.message, { error: true }); }
  });
  await refreshAll();
  route();
}

async function refreshAll() {
  const p = await api("GET", "/api/projects");
  S.projects = p.projects;
  S.current = p.current;
  const sel = $("#projectSelect");
  sel.replaceChildren(...S.projects.map((n) => h("option", { value: n, selected: n === S.current }, n)));
  sel.hidden = S.projects.length < 2;
  $("#projectName").textContent = S.current ? `· ${S.current}` : "";
  if (S.current) {
    const [st, cfg] = await Promise.all([api("GET", "/api/status"), api("GET", "/api/config")]);
    S.status = st;
    S.config = cfg.config;
    S.lastJob = st.job;
    $("#topProgress").textContent = labelingProgressText();
  } else {
    S.status = null; S.config = null; $("#topProgress").textContent = "";
  }
}

function labelingProgressText() {
  const s = S.status;
  return s && s.clusters ? `Đã đặt tên ${s.clusters_labeled}/${s.clusters} nhóm` : "";
}

function route() {
  stopPolling();
  closeModal();
  const view = location.hash === "#/label" && S.current ? "label" : "main";
  if (view === "label") renderLabeling(); else renderMain();
}

/* ---------------------------------------------------------------- màn chính */

function pathField(id, label, value, onChange) {
  const input = h("input", { type: "text", id, value, spellcheck: "false", placeholder: "Dán đường dẫn hoặc bấm Chọn…" });
  input.addEventListener("change", () => onChange(input.value.trim()));
  const pick = h("button", { type: "button", onclick: async () => {
    try {
      const r = await api("POST", "/api/pick-folder", { initial: input.value });
      if (r.path) { input.value = r.path; onChange(r.path); }
    } catch (err) { toast(err.message, { error: true }); }
  } }, "Chọn…");
  return h("div", { class: "field" }, h("label", { for: id }, label), h("div", { class: "row" }, input, pick));
}

function renderMain() {
  const app = $("#app");
  app.replaceChildren();
  if (!S.current) return renderCreateProject(app);

  const errBox = h("div", { class: "hint-err", id: "cfgErr" });
  const saveCfg = async (patch) => {
    try {
      await api("PUT", "/api/config", { config: patch });
      Object.assign(S.config, patch);
      errBox.textContent = "";
    } catch (err) { errBox.textContent = err.message; }
  };
  app.append(h("section", { class: "panel" },
    h("div", { class: "row" },
      pathField("inDir", "Folder input (chỉ đọc, không bao giờ bị sửa)", S.config.input_dir, (v) => saveCfg({ input_dir: v })),
      pathField("outDir", "Folder output", S.config.output_dir, (v) => saveCfg({ output_dir: v }))),
    errBox));

  const s = S.status;
  const running = s.job.state === "running";
  const hasClusters = s.clusters > 0 || s.photos > 0;
  const toLabel = s.clusters > s.clusters_labeled;
  const steps = h("section", { class: "steps" },
    h("button", { class: "step" + (!hasClusters || s.photos_pending > 0 ? " primary" : ""), id: "btnScan", disabled: running, onclick: startScan },
      h("b", {}, "1. Scan"),
      h("span", {}, s.photos ? `${num(s.photos)} ảnh · ${num(s.clusters)} nhóm` : "Chưa quét"),
      h("span", { class: "muted" }, "Tìm khuôn mặt và gom thành các nhóm")),
    h("a", { class: "step" + (hasClusters && s.photos_pending === 0 && toLabel ? " primary" : ""), id: "btnLabel", href: "#/label", "aria-disabled": s.clusters === 0 ? "true" : false },
      h("b", {}, "2. Labeling"),
      h("span", {}, s.clusters ? `${s.clusters_labeled}/${s.clusters} nhóm đã đặt tên` : "Chưa có nhóm nào"),
      h("span", { class: "muted" }, "Đặt tên cho từng người hoặc từng nhóm")),
    h("button", { class: "step" + (hasClusters && !toLabel && s.photos > 0 ? " primary" : ""), id: "btnExport", disabled: running || !s.photos, onclick: startExport },
      h("b", {}, "3. Export"),
      h("span", {}, "Quét lại, gán ảnh mới, copy"),
      h("span", { class: "muted" }, "Mỗi nhãn một folder trong folder output")));
  app.append(steps);

  app.append(h("section", { id: "progress" }), h("section", { id: "result" }));
  renderAdvanced(app);
  renderJob(s.job);
  if (running) startPolling();
}

function renderCreateProject(app) {
  const st = { inp: "", out: "" };
  const err = h("div", { class: "hint-err" });
  const form = h("section", { class: "panel" },
    h("h2", {}, "Tạo dự án mới"),
    h("p", { class: "muted" }, "Chọn folder chứa ảnh cưới (chỉ đọc) và folder để lưu kết quả phân loại. Hai folder không được lồng nhau."),
    h("div", { class: "row" },
      pathField("inDir", "Folder input", "", (v) => { st.inp = v; }),
      pathField("outDir", "Folder output", "", (v) => { st.out = v; })),
    err,
    h("div", { class: "row" }, h("button", { class: "primary", onclick: async (e) => {
      st.inp = $("#inDir").value.trim(); st.out = $("#outDir").value.trim();
      e.target.disabled = true;
      try {
        await api("POST", "/api/projects", { input_dir: st.inp, output_dir: st.out });
        await refreshAll(); route();
      } catch (ex) { err.textContent = ex.message; e.target.disabled = false; }
    } }, "Tạo dự án")));
  app.append(form);
}

function renderAdvanced(app) {
  const c = S.config;
  const save = async (patch) => {
    try { await api("PUT", "/api/config", { config: patch }); Object.assign(c, patch); toast("Đã lưu thiết lập. Bấm Scan lại để áp dụng."); }
    catch (err) { toast(err.message, { error: true }); }
  };
  const eps = [["Chặt", 0.42], ["Vừa", 0.5], ["Lỏng", 0.58]];
  const cur = eps.find(([, v]) => Math.abs(v - c.cluster_eps) < 0.005);
  const sel = h("select", { id: "epsSel", onchange: (e) => save({ cluster_eps: parseFloat(e.target.value) }) },
    ...eps.map(([n, v]) => h("option", { value: v, selected: cur && cur[1] === v }, n)),
    !cur && h("option", { value: c.cluster_eps, selected: true }, `Tùy chỉnh (${c.cluster_eps})`));
  const ratio = h("input", { type: "number", min: "0", max: "1", step: "0.05", value: c.min_face_ratio, onchange: (e) => save({ min_face_ratio: parseFloat(e.target.value) }) });
  const assign = h("input", { type: "number", min: "0.1", max: "1", step: "0.01", value: c.assign_threshold, onchange: (e) => save({ assign_threshold: parseFloat(e.target.value) }) });
  const unl = h("input", { type: "text", value: c.unlabeled_folder, onchange: (e) => save({ unlabeled_folder: e.target.value.trim() }) });
  const unlOn = h("input", { type: "checkbox", checked: c.export_unlabeled, onchange: (e) => save({ export_unlabeled: e.target.checked }) });
  app.append(h("details", { class: "panel" },
    h("summary", {}, "Tùy chỉnh nâng cao"),
    h("div", { class: "adv" },
      h("div", {}, h("h3", {}, "Độ chặt khi gom nhóm"), sel,
        h("p", {}, "Chặt: ít gộp nhầm hai người nhưng một người dễ bị tách thành nhiều nhóm (đặt cùng một tên cho các nhóm đó).")),
      h("div", {}, h("h3", {}, "Bỏ mặt nhỏ ở hậu cảnh"), ratio,
        h("p", {}, "Mặt nhỏ hơn tỉ lệ này so với mặt lớn nhất trong ảnh sẽ bị bỏ qua (0.25 = bằng một phần tư).")),
      h("div", {}, h("h3", {}, "Độ chặt khi tự gán ảnh mới"), assign,
        h("p", {}, "Số nhỏ hơn thì chặt hơn: ít ảnh người lạ lọt vào folder người quen.")),
      h("div", {}, h("h3", {}, "Folder cho ảnh không có nhãn"), unl,
        h("label", { class: "row" }, unlOn, "Tạo folder này")))));
}

/* ---------------------------------------------------------------- tác vụ nền */

async function startScan() { await startJob("/api/jobs/scan"); }
async function startExport() { await startJob("/api/jobs/export"); }

async function startJob(url) {
  try {
    const job = await api("POST", url);
    $("#result").replaceChildren();
    renderJob(job);
    startPolling();
    $("#btnScan").disabled = $("#btnExport").disabled = true;
  } catch (err) { toast(err.message, { error: true }); }
}

function startPolling() {
  stopPolling();
  S.polling = setInterval(async () => {
    try {
      const job = await api("GET", "/api/job");
      renderJob(job);
      if (job.state !== "running") {
        stopPolling();
        await refreshAll();
        if (!location.hash || location.hash === "#/") renderMain();
      }
    } catch { /* thử lại ở lần sau */ }
  }, 500);
}

function stopPolling() { if (S.polling) { clearInterval(S.polling); S.polling = null; } }

function renderJob(job) {
  const prog = $("#progress"), res = $("#result");
  if (!prog || !res) return;
  prog.replaceChildren();
  if (job.state === "running") {
    const pct = job.total > 0 ? Math.min(100, Math.round((job.i / job.total) * 100)) : null;
    const text = STEP_TEXT[job.step] || job.step;
    const count = job.total > 0 ? ` · ${num(job.i)} / ${num(job.total)}` : job.i > 0 ? ` · ${num(job.i)}` : "";
    prog.append(h("div", { class: "panel" },
      h("div", { class: "row" }, h("b", {}, text + count), h("span", { class: "muted" }, fmtEta(job.eta_seconds)), h("span", { class: "spacer" }),
        h("button", { id: "btnCancel", disabled: job.cancel_requested, onclick: async () => { try { await api("POST", "/api/job/cancel"); } catch (e) { toast(e.message, { error: true }); } } },
          job.cancel_requested ? "Đang dừng…" : "Dừng")),
      h("div", { class: "bar" + (pct == null ? " indeterminate" : "") }, h("i", { style: pct != null ? `width:${pct}%` : null }))));
    return;
  }
  res.replaceChildren();
  if (job.state === "error") {
    res.append(h("div", { class: "panel err" }, h("b", {}, "Không hoàn tất: "), job.error));
  } else if (job.state === "cancelled") {
    res.append(h("div", { class: "panel warn" }, "Đã dừng. Tiến độ đã làm được vẫn được giữ; bấm lại để chạy tiếp."));
  } else if (job.state === "done" && job.kind === "scan") {
    renderScanResult(res, job.result);
  } else if (job.state === "done" && job.kind === "export") {
    renderExportResult(res, job.result);
  }
}

function renderScanResult(res, r) {
  res.append(h("div", { class: "panel" },
    h("h2", {}, "Đã quét xong"),
    h("p", {}, `${num(r.photos)} ảnh duy nhất (${num(r.duplicate_files)} file trùng), tìm thấy ${num(r.faces_found)} khuôn mặt mới, ${num(r.clusters ?? 0)} nhóm.`),
    r.assigned > 0 && h("p", {}, `${num(r.assigned)} khuôn mặt mới được tự gán vào người đã có nhãn.`),
    r.photo_errors > 0 && h("p", { class: "warn" }, `${num(r.photo_errors)} ảnh không đọc được (sẽ thử lại ở lần Scan sau).`),
    h("a", { class: "step primary", href: "#/label", style: "display:inline-flex;min-height:0" }, "Sang bước 2. Labeling")));
}

function renderExportResult(res, r) {
  const rows = Object.entries(r.per_folder || {});
  res.append(h("div", { class: "panel" },
    h("h2", {}, "Kết quả Export"),
    h("p", {}, `Đã copy ${num(r.copied)} file, ${fmtBytes(r.total_bytes)}. Bỏ qua ${num((r.skipped_existing || 0) + (r.duplicate_source_files || 0))} file trùng.`),
    rows.length > 0 && h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Folder"), h("th", { class: "num" }, "Số ảnh mới"))),
      h("tbody", {}, rows.map(([f, n]) => h("tr", {}, h("td", {}, f), h("td", { class: "num" }, num(n)))))),
    h("p", {}, `Số khuôn mặt tự gán vào người đã có nhãn: ${num(r.assigned)}.`),
    r.unlabeled_clusters > 0 && h("p", { class: "warn" }, `${num(r.unlabeled_clusters)} nhóm chưa có tên. `, h("a", { href: "#/label" }, "Mở Labeling")),
    r.reconciled && (r.reconciled.moved || r.reconciled.removed_duplicates) ? h("p", {}, `Đã sắp lại folder cũ: chuyển ${r.reconciled.moved} file, xóa ${r.reconciled.removed_duplicates} bản trùng.`) : null,
    r.error_photos && r.error_photos.length > 0 && h("div", { class: "warn" }, h("b", {}, "Ảnh không đọc được:"), h("ul", {}, r.error_photos.map((e) => h("li", {}, `${e.path}: ${e.message}`)))),
    r.errors && r.errors.length > 0 && h("div", { class: "err" }, h("b", {}, "Lỗi khi copy:"), h("ul", {}, r.errors.map((e) => h("li", {}, `${e.folder}/${e.name}: ${e.message}`)))),
    h("div", { class: "row" }, h("button", { onclick: async () => {
      try { await api("POST", "/api/open-output"); } catch (e) { toast(e.message, { error: true }); }
    } }, "Mở thư mục kết quả"))));
}

/* ---------------------------------------------------------------- Labeling */

async function renderLabeling() {
  const app = $("#app");
  S.page = 1; S.items = []; S.focus = 0; S.fresh = null;
  const filterSel = h("select", { id: "filterSel", "aria-label": "Lọc nhóm", onchange: (e) => { S.filter = e.target.value; loadClusters(true); } },
    ...[["all", "Tất cả nhóm"], ["unlabeled", "Chưa đặt tên"], ["labeled", "Đã đặt tên"], ["ignored", "Đã bỏ qua"]]
      .map(([v, t]) => h("option", { value: v, selected: v === S.filter }, t)));
  const hide = h("input", { type: "checkbox", checked: S.hideDone, onchange: (e) => { S.hideDone = e.target.checked; $("#cards").classList.toggle("hide-done", S.hideDone); } });
  app.replaceChildren(
    h("div", { class: "toolbar" },
      h("a", { href: "#/" }, "← Quay lại"), filterSel,
      h("label", { class: "row" }, hide, "Ẩn nhóm đã xong"),
      h("span", { class: "spacer" }),
      h("button", { onclick: doUndo }, "Hoàn tác ", h("span", { class: "kbd" }, "Ctrl+Z"))),
    h("p", { class: "muted" }, "Gõ tên rồi nhấn Enter để lưu và sang nhóm kế tiếp. Gõ trùng một tên có sẵn thì các nhóm dùng chung một folder. ",
      h("span", { class: "kbd" }, "J"), "/", h("span", { class: "kbd" }, "K"), " di chuyển, ", h("span", { class: "kbd" }, "S"), " bỏ qua."),
    h("div", { id: "cards", class: "cards" + (S.hideDone ? " hide-done" : "") }),
    h("div", { class: "row", id: "more" }),
    h("details", { class: "panel", id: "loose", style: "margin-top:16px" }, h("summary", {}, "Mặt lẻ (không thuộc nhóm nào)")));
  $("#loose").addEventListener("toggle", (e) => { if (e.target.open) loadLoose(1); });
  try { S.labels = (await api("GET", "/api/labels")).labels; } catch { S.labels = []; }
  await loadClusters(true);
}

function datalist() {
  let dl = $("#labelNames");
  if (!dl) { dl = h("datalist", { id: "labelNames" }); document.body.append(dl); }
  dl.replaceChildren(...S.labels.map((l) => h("option", { value: l.name })));
}

async function loadClusters(reset) {
  if (reset) { S.page = 1; S.items = []; $("#cards").replaceChildren(); }
  try {
    const r = await api("GET", `/api/clusters?filter=${S.filter}&page=${S.page}`);
    S.total = r.total;
    S.items.push(...r.items);
    datalist();
    for (const c of r.items) $("#cards").append(clusterCard(c));
    const more = $("#more");
    more.replaceChildren();
    if (S.items.length < r.total) {
      more.append(h("button", { onclick: () => { S.page++; loadClusters(false); } }, `Tải thêm (${num(r.total - S.items.length)} nhóm nữa)`));
    } else if (r.total === 0) {
      more.append(h("p", { class: "muted" }, S.filter === "unlabeled" ? "Không còn nhóm nào chưa đặt tên." : "Không có nhóm nào."));
    }
    if (reset) focusCard(0);
  } catch (err) { toast(err.message, { error: true }); }
}

function cardEl(id) { return $(`.card[data-id="${id}"]`); }

function clusterCard(c) {
  const input = h("input", { type: "text", list: "labelNames", placeholder: "Nhập tên, ví dụ Họ nhà gái", value: c.label || "", "aria-label": "Tên nhóm", autocomplete: "off" });
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") { e.preventDefault(); await saveLabel(c.id, input.value); }
    else if (e.key === "Escape") { input.value = c.label || ""; input.blur(); }
  });
  const minis = h("div", { class: "minis" }, c.small_faces.map((f) => h("img", { class: "mini", src: faceUrl(f), alt: "Khuôn mặt khác trong nhóm", loading: "lazy", title: "Bấm để tách hoặc xem ảnh", onclick: () => faceDialog(c.id, f) })));
  const el = h("div", { class: "card" + (c.label || c.ignored ? " done" : ""), "data-id": c.id },
    c.main_face ? h("img", { class: "big", src: faceUrl(c.main_face), alt: "Khuôn mặt đại diện", onclick: () => faceDialog(c.id, c.main_face) }) : h("div", { class: "big" }),
    h("div", {},
      minis,
      h("div", { class: "meta" }, `${num(c.photos)} ảnh · ${num(c.faces)} khuôn mặt`, c.ignored && " · đã bỏ qua", " · ",
        h("button", { class: "link", onclick: () => allFacesDialog(c.id) }, "Xem tất cả")),
      h("div", { class: "row", style: "margin-top:8px" }, input,
        h("button", { onclick: () => ignoreCluster(c.id, !c.ignored) }, c.ignored ? "Bỏ qua: tắt" : "Bỏ qua")),
      c.hint && h("div", { class: "banner", "data-hint": "1" }, `Có phải ${c.hint.label}?`,
        h("button", { class: "primary", onclick: () => saveLabel(c.id, c.hint.label) }, "Đồng ý")),
      h("div", { class: "suggest" })));
  el.addEventListener("focusin", () => { S.focus = S.items.findIndex((x) => x.id === c.id); markFocus(); });
  return el;
}

async function saveLabel(id, name) {
  name = name.trim();
  if (!name) { toast("Hãy nhập tên cho nhóm.", { error: true }); return; }
  try {
    const r = await api("PUT", `/api/clusters/${id}/label`, { name });
    markDone(id, r.label);
    toast(`Đã lưu: ${r.label}`, { undo: true });
    if (!S.labels.some((l) => l.id === r.label_id)) S.labels.push({ id: r.label_id, name: r.label }), datalist();
    refreshTop();
    showSuggestions(id, r.label);
    nextCard(id);
  } catch (err) { toast(err.message, { error: true }); }
}

function markDone(id, label) {
  const el = cardEl(id);
  if (!el) return;
  if (S.fresh && S.fresh !== id) { const old = cardEl(S.fresh); if (old) old.classList.remove("fresh"); }
  S.fresh = id;
  el.classList.add("done", "fresh");
  const hint = $("[data-hint]", el); if (hint) hint.remove();
  const it = S.items.find((x) => x.id === id);
  if (it) { it.label = label; it.ignored = false; }
  const input = $("input", el); if (input) input.value = label;
}

async function showSuggestions(id, label) {
  const el = cardEl(id);
  if (!el) return;
  const box = $(".suggest", el);
  box.replaceChildren();
  try {
    const r = await api("GET", `/api/clusters/${id}/suggest-merge`);
    for (const s of r.suggestions.filter((x) => !x.label)) {
      const row = h("div", { class: "banner" },
        s.main_face && h("img", { src: faceUrl(s.main_face), alt: "" }),
        `Nhóm ${s.cluster_id} (${num(s.faces)} khuôn mặt) có thể cũng là ${label}`,
        h("button", { class: "primary", onclick: async () => {
          try { await api("PUT", `/api/clusters/${s.cluster_id}/label`, { name: label }); markDone(s.cluster_id, label); row.remove(); toast(`Đã gộp vào ${label}`, { undo: true }); refreshTop(); }
          catch (err) { toast(err.message, { error: true }); }
        } }, "Đúng"),
        h("button", { onclick: () => row.remove() }, "Không"));
      box.append(row);
    }
  } catch { /* gợi ý là tùy chọn */ }
}

async function ignoreCluster(id, ignored) {
  try {
    await api("POST", `/api/clusters/${id}/ignore`, { ignored });
    const it = S.items.find((x) => x.id === id);
    if (it) { it.ignored = ignored; if (ignored) it.label = null; }
    const el = cardEl(id);
    if (el) { el.classList.toggle("done", ignored); el.classList.toggle("fresh", false); }
    toast(ignored ? "Đã bỏ qua nhóm này (ảnh của họ vào folder không nhãn nếu không có ai khác)." : "Đã bật lại nhóm.", { undo: true });
    refreshTop();
    if (ignored) nextCard(id);
  } catch (err) { toast(err.message, { error: true }); }
}

async function refreshTop() {
  try { S.status = await api("GET", "/api/status"); $("#topProgress").textContent = labelingProgressText(); } catch { /* bỏ qua */ }
}

async function doUndo() {
  try {
    await api("POST", "/api/undo");
    toast("Đã hoàn tác.");
    refreshTop();
    if (location.hash === "#/label") { S.labels = (await api("GET", "/api/labels")).labels; await loadClusters(true); }
  } catch (err) { toast(err.message, { error: true }); }
}

/* --- điều hướng bằng bàn phím */

function visibleCards() {
  return [...document.querySelectorAll("#cards .card")].filter((c) => c.offsetParent !== null);
}

function markFocus() {
  document.querySelectorAll(".card.focused").forEach((c) => c.classList.remove("focused"));
  const it = S.items[S.focus];
  const el = it && cardEl(it.id);
  if (el) el.classList.add("focused");
}

function focusCard(i, toInput = true) {
  const cards = visibleCards();
  if (!cards.length) return;
  i = Math.max(0, Math.min(i, cards.length - 1));
  const el = cards[i];
  S.focus = S.items.findIndex((x) => String(x.id) === el.dataset.id);
  markFocus();
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  if (toInput) $("input", el).focus({ preventScroll: true });
}

function nextCard(afterId) {
  const cards = visibleCards();
  const idx = cards.findIndex((c) => c.dataset.id === String(afterId));
  // chuyển tới nhóm chưa xong kế tiếp
  for (let i = idx + 1; i < cards.length; i++) {
    if (!cards[i].classList.contains("done")) { focusCard(i); return; }
  }
  focusCard(Math.min(idx + 1, cards.length - 1));
}

function isTyping(t) { return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT"); }

function onKey(e) {
  if (e.key === "Escape" && !$("#modal").hidden) { closeModal(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    const t = e.target;
    if (!isTyping(t) || (t.tagName === "INPUT" && t.type === "text" && t.value === "")) {
      e.preventDefault(); doUndo();
    }
    return;
  }
  if (location.hash !== "#/label" || isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
  const cards = visibleCards();
  const cur = cards.findIndex((c) => c.classList.contains("focused"));
  if (e.key === "j" || e.key === "J") { e.preventDefault(); focusCard(cur + 1, false); }
  else if (e.key === "k" || e.key === "K") { e.preventDefault(); focusCard(Math.max(cur - 1, 0), false); }
  else if (e.key === "Enter" && cur >= 0) { e.preventDefault(); $("input", cards[cur]).focus(); }
  else if ((e.key === "s" || e.key === "S") && cur >= 0) {
    e.preventDefault();
    const id = Number(cards[cur].dataset.id);
    const it = S.items.find((x) => x.id === id);
    ignoreCluster(id, !(it && it.ignored));
  }
}

/* --- hộp thoại */

function openModal(content) {
  const m = $("#modal");
  m.replaceChildren(h("div", { class: "dialog", role: "dialog", "aria-modal": "true" }, content));
  m.hidden = false;
  m.onclick = (e) => { if (e.target === m) closeModal(); };
}
function closeModal() { const m = $("#modal"); m.hidden = true; m.replaceChildren(); }

async function clusterFaces(cid) {
  if (!S.facesCache[cid]) S.facesCache[cid] = (await api("GET", `/api/clusters/${cid}/faces`)).faces;
  return S.facesCache[cid];
}

function photoDialog(sha, faceId) {
  openModal([
    h("img", { class: "photo", src: `/api/photos/${sha}/preview?face=${faceId}`, alt: "Ảnh gốc, khung đỏ là khuôn mặt đang xem" }),
    h("div", { class: "row" }, h("button", { onclick: closeModal }, "Đóng")),
  ]);
}

async function faceDialog(cid, faceId) {
  let sha = null;
  try { sha = ((await clusterFaces(cid)).find((f) => f.id === faceId) || {}).photo; } catch { /* bỏ qua */ }
  faceActions(faceId, sha, cid);
}

function faceActions(faceId, sha, cid) {
  const name = h("input", { type: "text", list: "labelNames", placeholder: "Đặt tên riêng cho khuôn mặt này", autocomplete: "off" });
  const done = (msg) => { toast(msg, { undo: true }); delete S.facesCache[cid]; closeModal(); refreshTop(); if (location.hash === "#/label") loadClusters(true); };
  const act = (fn, msg) => async () => { try { await fn(); done(msg); } catch (err) { toast(err.message, { error: true }); } };
  name.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && name.value.trim()) act(() => api("PUT", `/api/faces/${faceId}/label`, { name: name.value.trim() }), "Đã đặt tên riêng cho khuôn mặt.")();
  });
  openModal([
    h("div", { class: "row" }, h("img", { class: "big", src: faceUrl(faceId), alt: "Khuôn mặt" }),
      h("div", { class: "field" },
        h("p", { class: "muted" }, "Nếu khuôn mặt này bị nhận nhầm vào nhóm, hãy tách nó ra. Tên đặt riêng luôn thắng tên của nhóm."),
        h("div", { class: "row" },
          cid != null && h("button", { class: "primary", onclick: act(() => api("POST", `/api/faces/${faceId}/detach`), "Đã tách khuôn mặt khỏi nhóm.") }, "Tách khỏi nhóm"),
          sha && h("button", { onclick: () => photoDialog(sha, faceId) }, "🔍 Xem ảnh gốc"),
          h("button", { class: "danger", onclick: act(() => api("POST", `/api/faces/${faceId}/ignore`), "Đã bỏ qua khuôn mặt này.") }, "Bỏ qua mặt này")),
        h("div", { style: "margin-top:8px" }, name),
        h("div", { class: "row", style: "margin-top:12px" }, h("button", { onclick: closeModal }, "Đóng")))),
  ]);
  name.focus();
}

async function allFacesDialog(cid) {
  try {
    const faces = await clusterFaces(cid);
    openModal([
      h("h3", {}, `Tất cả ${num(faces.length)} khuôn mặt trong nhóm ${cid}`),
      h("div", { class: "grid" }, faces.map((f) => h("div", { class: "tile" },
        h("img", { src: faceUrl(f.id), loading: "lazy", alt: "", onclick: () => faceActions(f.id, f.photo, cid) }),
        h("div", { class: "meta" }, `${f.size}px · ${f.score}`)))),
      h("div", { class: "row", style: "margin-top:12px" }, h("button", { onclick: closeModal }, "Đóng")),
    ]);
  } catch (err) { toast(err.message, { error: true }); }
}

/* --- mặt lẻ */

async function loadLoose(page) {
  const box = $("#loose");
  if (page === 1) box.querySelectorAll(":scope > :not(summary)").forEach((n) => n.remove());
  try {
    const r = await api("GET", `/api/faces/loose?page=${page}`);
    if (page === 1 && r.total === 0) { box.append(h("p", { class: "muted" }, "Không có mặt lẻ.")); return; }
    const grid = page === 1 ? h("div", { class: "grid", id: "looseGrid" }) : $("#looseGrid");
    if (page === 1) box.append(h("p", { class: "muted" }, `${num(r.total)} khuôn mặt chưa thuộc nhóm nào. Không bắt buộc phải xử lý.`), grid);
    for (const f of r.items) {
      const input = h("input", { type: "text", list: "labelNames", placeholder: f.hint ? `Có phải ${f.hint.label}?` : "Tên", autocomplete: "off", "aria-label": "Tên khuôn mặt" });
      const save = async (name) => {
        try { await api("PUT", `/api/faces/${f.id}/label`, { name }); tile.remove(); toast("Đã đặt tên.", { undo: true }); refreshTop(); }
        catch (err) { toast(err.message, { error: true }); }
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) save(input.value.trim()); });
      const tile = h("div", { class: "tile" },
        h("img", { src: faceUrl(f.id), loading: "lazy", alt: "Mặt lẻ", onclick: () => faceActions(f.id, f.photo, null) }),
        f.hint && h("button", { class: "link", onclick: () => save(f.hint.label) }, `Đúng, là ${f.hint.label}`),
        input,
        h("button", { class: "link danger", onclick: async () => { try { await api("POST", `/api/faces/${f.id}/ignore`); tile.remove(); } catch (err) { toast(err.message, { error: true }); } } }, "Bỏ qua"));
      grid.append(tile);
    }
    $("#loose .more-loose")?.remove();
    if (page * r.page_size < r.total) box.append(h("button", { class: "more-loose", onclick: () => loadLoose(page + 1) }, "Tải thêm"));
  } catch (err) { toast(err.message, { error: true }); }
}

boot().catch((err) => {
  $("#app").replaceChildren(h("div", { class: "panel err" }, err.message));
});
