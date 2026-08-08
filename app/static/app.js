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
