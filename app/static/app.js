// Research Radar — vanilla JS. Vote buttons on dashboard cards.
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
