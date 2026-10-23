// The home page (#78): "Show data up to…", a listbox of the stages that sets the stage filter as the header select
// does on other pages (<html data-max>, localStorage; search.js), and the section counts, which follow it
// (data-counts: what each section holds up to each stage, the last = everything). The deeper bands listed under the
// well (scripts/well.py cut()) set it too.
(() => {
  const root = document.documentElement, KEY = "mimir-stage";
  const btn = document.getElementById("upto-b"), list = document.getElementById("upto-list");
  if (!btn || !list) return;
  const opts = [...list.querySelectorAll('[role="option"]')], last = opts.length - 1;
  const counts = [...document.querySelectorAll("[data-counts]")];
  const current = () => root.dataset.max === undefined ? last : +root.dataset.max;
  let active = current();

  function show() {
    const i = current(), o = opts[i];
    opts.forEach((x, n) => x.setAttribute("aria-selected", String(n === i)));
    btn.style.setProperty("--tier", o.style.getPropertyValue("--tier"));
    btn.innerHTML = o.innerHTML;
    counts.forEach((c) => { c.textContent = c.dataset.counts.split(" ")[i]; });
  }

  function choose(n) {
    const v = opts[n].dataset.upto;
    if (v === "") delete root.dataset.max; else root.dataset.max = v;
    try { localStorage.setItem(KEY, v === "" ? "all" : v); } catch (e) {}  // "all": chosen, unlike nothing stored
    show();
    close();
  }

  function move(n) {
    opts[active]?.classList.remove("active");
    active = Math.max(0, Math.min(last, n));
    opts[active].classList.add("active");
    list.setAttribute("aria-activedescendant", opts[active].id);
    opts[active].scrollIntoView({ block: "nearest" });
  }

  function open() {
    list.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    list.focus();
    move(current());
  }

  function close(refocus = true) {
    if (list.hidden) return;
    list.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (refocus) btn.focus();
  }

  btn.addEventListener("click", () => list.hidden ? open() : close());
  btn.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); open(); }
  });
  list.addEventListener("keydown", (ev) => {
    const to = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: last }[ev.key];
    if (to !== undefined) move(to);
    else if (ev.key === "Enter" || ev.key === " ") choose(active);
    else if (ev.key === "Escape") close();
    else { if (ev.key === "Tab") close(false); return; }
    ev.preventDefault();
  });
  document.querySelectorAll(".deeper [data-upto]").forEach((b) => b.addEventListener("click", () =>
    choose(opts.findIndex((o) => o.dataset.upto === b.dataset.upto))));
  addEventListener("storage", (ev) => {  // changed in another tab (as the head script reads it: nothing stored = Meadows)
    if (ev.key !== KEY && ev.key !== null) return;
    const m = ev.key === null ? null : ev.newValue;
    if (m === "all") delete root.dataset.max; else root.dataset.max = m ?? "0";
    show();
  });
  opts.forEach((o, n) => {
    o.addEventListener("click", () => choose(n));
    o.addEventListener("mousemove", () => { if (n !== active) move(n); });
  });
  list.addEventListener("focusout", (ev) => { if (!list.parentElement.contains(ev.relatedTarget)) close(false); });
  document.addEventListener("click", (ev) => { if (!ev.target.closest(".pick")) close(false); });
  show();
})();
