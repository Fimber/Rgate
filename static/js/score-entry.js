(function () {
  const form = document.querySelector("[data-score-form]");
  if (!form) return;
  const status = document.querySelector("[data-sync-state]");
  const key = form.dataset.draftKey;
  const url = form.dataset.saveUrl;
  const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
  const draft = JSON.parse(localStorage.getItem(key) || "{}");

  function setState(kind, text) {
    if (!status) return;
    status.dataset.state = kind;
    status.innerHTML = '<span class="status-dot ' + kind + '"></span> ' + text;
  }

  function persist(id, value, marker) {
    draft[id] = { value: value, marker: marker, at: Date.now() };
    localStorage.setItem(key, JSON.stringify(draft));
    setState("saved", "Saved on this phone");
  }

  async function sync(input) {
    const body = new URLSearchParams({
      csrfmiddlewaretoken: csrf,
      enrollment: input.dataset.enrollment,
      component: input.dataset.component,
      value: input.value,
      marker: input.dataset.marker || "score",
    });
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
        body: body,
      });
      const data = await response.json();
      if (!data.ok) {
        setState("saved", data.error || "Not accepted");
        input.classList.add("invalid");
        return;
      }
      input.classList.remove("invalid");
      delete draft[input.dataset.cell];
      localStorage.setItem(key, JSON.stringify(draft));
      setState("synced", "Synced");
    } catch (err) {
      setState("saved", "Offline — will sync when the network returns");
    }
  }

  form.querySelectorAll("[data-cell]").forEach(function (input) {
    const stored = draft[input.dataset.cell];
    if (stored && stored.value !== undefined && stored.value !== input.value) {
      input.value = stored.value;
    }
    input.addEventListener("change", function () {
      persist(input.dataset.cell, input.value, input.dataset.marker || "score");
      sync(input);
    });
  });

  window.addEventListener("online", function () {
    form.querySelectorAll("[data-cell]").forEach(sync);
  });
})();
