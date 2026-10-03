// Client-side search over search.json: [[name, id, url, icon, label, stage], ...], loaded on first use.
// Ranking: exact name, name prefix, word prefix, substring of name, substring of id. Entries past the stage filter
// (<html data-max>, the header's "Up to" select, kept in localStorage) are left out.
(() => {
  const sel = document.getElementById("stage"), root = document.documentElement, KEY = "mimir-stage";
  if (!sel) return;
  sel.value = root.dataset.max ?? "";
  sel.addEventListener("change", () => {
    if (sel.value === "") delete root.dataset.max; else root.dataset.max = sel.value;
    try { sel.value === "" ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, sel.value); } catch (e) {}
  });
})();

(() => {
  const q = document.getElementById("q");
  const list = document.getElementById("results");
  if (!q || !list) return;
  const base = document.baseURI;
  let index = null, loading = null, hits = [], sel = 0;

  const load = () => loading || (loading = fetch(new URL("search.json", base))
    .then((r) => r.json())
    .then((d) => { index = d.map((e) => [...e, e[0].toLowerCase(), e[1].toLowerCase()]); }));

  function score(e, s) {
    const name = e[6], id = e[7];
    if (name === s) return 0;
    if (name.startsWith(s)) return 1;
    if (name.includes(" " + s)) return 2;
    if (name.includes(s)) return 3;
    if (id.includes(s.replace(/\s+/g, ""))) return 4;
    return -1;
  }

  function search(s) {
    s = s.trim().toLowerCase();
    if (!s) return [];
    const out = [], max = document.documentElement.dataset.max;
    for (const e of index) {
      if (max !== undefined && e[5] > +max) continue;
      const r = score(e, s);
      if (r >= 0) out.push([r, e[0].length, e]);
    }
    out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    return out.slice(0, 20).map((x) => x[2]);
  }

  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function render() {
    if (!q.value.trim()) { list.hidden = true; return; }
    list.innerHTML = hits.length ? hits.map((e, i) =>
      `<li${i === sel ? ' class="sel"' : ""}><a href="${new URL(e[2], base)}">` +
      (e[3] ? `<img class="ico" src="${new URL("icons/" + encodeURIComponent(e[3]) + ".png", base)}" alt="">`
            : '<span class="ico"></span>') +
      `<span>${esc(e[0])}</span><small>${esc(e[4])}</small></a></li>`).join("")
      : '<li class="empty">No matches</li>';
    list.hidden = false;
  }

  q.addEventListener("input", async () => {
    await load();
    hits = search(q.value);
    sel = 0;
    render();
  });
  q.addEventListener("focus", load, { once: true });
  q.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!hits.length) return;
      sel = (sel + (ev.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length;
      render();
      list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
      ev.preventDefault();
    } else if (ev.key === "Enter" && hits[sel]) {
      location.href = new URL(hits[sel][2], base);
    } else if (ev.key === "Escape") {
      q.value = ""; list.hidden = true; q.blur();
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement !== q) { ev.preventDefault(); q.focus(); }
  });
  document.addEventListener("click", (ev) => { if (!ev.target.closest(".search")) list.hidden = true; });
})();
