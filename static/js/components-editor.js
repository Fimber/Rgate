(function () {
  "use strict";
  var rows = document.getElementById("componentRows");
  var tpl = document.getElementById("componentRowTemplate");
  var totalEl = document.getElementById("componentTotal");
  var addBtn = document.getElementById("addComponent");
  if (!rows || !tpl || !addBtn) return;

  function nextName() {
    var max = 0;
    rows.querySelectorAll("input[name=component_name]").forEach(function (el) {
      var match = /^CA\s*(\d+)$/i.exec((el.value || "").trim());
      if (match) max = Math.max(max, parseInt(match[1], 10));
    });
    return "CA" + (max + 1);
  }

  function updateTotal() {
    var sum = 0;
    rows.querySelectorAll("input[name=component_max]").forEach(function (el) {
      sum += parseInt(el.value, 10) || 0;
    });
    if (totalEl) {
      totalEl.textContent =
        "Scores are out of " + sum + (sum && sum !== 100 ? ". Grades use the percentage of " + sum + "." : ".");
      totalEl.classList.toggle("bad", sum < 1);
    }
    var removes = rows.querySelectorAll(".component-remove");
    removes.forEach(function (btn) {
      btn.disabled = removes.length <= 1;
    });
  }

  rows.addEventListener("input", updateTotal);
  rows.addEventListener("click", function (e) {
    var btn = e.target.closest(".component-remove");
    if (!btn || btn.disabled) return;
    var row = btn.closest(".component-row");
    if (!row || rows.querySelectorAll(".component-row").length <= 1) return;
    row.remove();
    updateTotal();
  });
  addBtn.addEventListener("click", function () {
    var node = tpl.content.cloneNode(true);
    var name = node.querySelector("input[name=component_name]");
    if (name) name.value = nextName();
    rows.appendChild(node);
    updateTotal();
    if (name) name.focus();
  });
  updateTotal();
})();
