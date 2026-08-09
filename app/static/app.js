// Research Radar — vanilla JS. Vote buttons + structured interest editors.

// Structured editors (topics / exclusions): add row, remove row, star core.
document.addEventListener("click", (ev) => {
  const add = ev.target.closest("[data-add-row]");
  if (add) {
    const editor = add.closest(".flavor-editor");
    const tpl = editor.querySelector(".flavor-template");
    tpl.before(tpl.content.cloneNode(true));
    return;
  }
  const rm = ev.target.closest(".flavor-row .rm");
  if (rm) {
    const editor = rm.closest(".flavor-editor");
    rm.closest(".flavor-row").remove();
    if (!editor.querySelector(".flavor-row")) {         // never zero rows
      const tpl = editor.querySelector(".flavor-template");
      tpl.before(tpl.content.cloneNode(true));
    }
    return;
  }
  const star = ev.target.closest(".flavor-row .star");
  if (star) {
    const hidden = star.closest(".row-head").querySelector("input[name=flavor_core]");
    const on = hidden.value !== "1";
    hidden.value = on ? "1" : "0";
    star.classList.toggle("on", on);
  }
});

// Priority-journal autocomplete (onboarding + settings).
document.addEventListener("input", (ev) => {
  const q = ev.target.closest(".journal-q");
  if (!q) return;
  const editor = q.closest(".journals-editor");
  clearTimeout(editor._t);
  editor._t = setTimeout(async () => {
    const box = editor.querySelector(".journal-results");
    const term = q.value.trim();
    if (term.length < 2) { box.innerHTML = ""; return; }
    try {
      const resp = await fetch("/journals/search?q=" + encodeURIComponent(term));
      if (!resp.ok) throw new Error("search failed");
      const data = await resp.json();
      box.innerHTML = "";
      for (const src of data.results) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "journal-hit" + (src.selected ? " on" : "");
        b.textContent = src.display_name + (src.country_code ? " · " + src.country_code : "");
        if (!src.selected) {
          b.addEventListener("click", async () => {
            await fetch("/journals/add", {
              method: "POST",
              headers: {"Content-Type": "application/x-www-form-urlencoded"},
              body: new URLSearchParams({
                source_id: src.id, display_name: src.display_name,
                country_code: src.country_code || "", next: editor.dataset.jnext,
              }),
            });
            window.location = editor.dataset.jnext;
          });
        }
        box.appendChild(b);
      }
    } catch (e) { console.error(e); }
  }, 250);
});

// AI coach: "Get suggestions on my draft" — posts the surrounding form's
// current fields, renders dismissible notes. Nothing is applied automatically.
function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

document.addEventListener("click", async (ev) => {
  const dismiss = ev.target.closest(".coach-dismiss");
  if (dismiss) {
    dismiss.closest(".coach-note").remove();
    return;
  }
  const btn = ev.target.closest(".coach-suggest");
  if (!btn) return;
  const box = btn.closest("[data-coach]");
  const form = btn.closest("form");
  const results = box.querySelector(".coach-results");
  const body = new URLSearchParams();
  if (form) for (const [k, v] of new FormData(form)) body.append(k, v);
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Thinking…";
  try {
    const resp = await fetch("/coach/suggest", {
      method: "POST",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body,
    });
    const data = await resp.json();
    results.hidden = false;
    if (!resp.ok) {
      results.innerHTML = `<div class="coach-note flag">${escHtml(data.error || "Something went wrong.")}</div>`;
      return;
    }
    const section = (title, items, cls) => (items && items.length)
      ? `<h4>${title}</h4>` + items.map((i) =>
          `<div class="coach-note ${cls}">${escHtml(i)}
           <button type="button" class="coach-dismiss" title="Dismiss">&#10005;</button></div>`).join("")
      : "";
    results.innerHTML =
      section("Worth clarifying", data.questions, "question") +
      section("Suggestions", data.suggestions, "suggestion") +
      section("Possibly too broad", data.flags, "flag") ||
      `<div class="coach-note">No suggestions — this draft reads clearly.</div>`;
  } catch (e) {
    results.hidden = false;
    results.innerHTML = `<div class="coach-note flag">Could not reach the coach — try again shortly.</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
});

// Vote buttons on dashboard cards.
document.addEventListener("click", async (ev) => {
  const btn = ev.target.closest(".vote");
  if (!btn) return;
  const card = btn.closest(".card");
  const paperId = card.dataset.paper;
  const dir = btn.classList.contains("up") ? "up" : "down";
  const next = card.dataset.vote === dir ? "" : dir;   // click same = toggle off
  try {
    const resp = await fetch("/feedback", {
      method: "POST",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({paper_id: paperId, vote: next}),
    });
    if (!resp.ok) throw new Error("vote failed");
    card.dataset.vote = next;
    card.querySelector(".vote.up").classList.toggle("on", next === "up");
    card.querySelector(".vote.down").classList.toggle("on", next === "down");
  } catch (e) {
    console.error(e);
  }
});
