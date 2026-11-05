// Records every press of a button or link and every form submission: the tests fail on any.
window.__jm = { clicks: [], submits: 0 };
document.addEventListener("click", (e) => {
  const b = e.target.closest("button, a, input[type=submit], input[type=button]");
  if (b) window.__jm.clicks.push((b.textContent || b.value || "").trim());
}, true);
document.addEventListener("submit", (e) => { e.preventDefault(); window.__jm.submits += 1; }, true);
