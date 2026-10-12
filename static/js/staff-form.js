// Add staff: show class/subject rows only for teaching roles, and let the admin add more rows.
(function () {
  var form = document.getElementById("staff-form") || document.getElementById("my-classes-form");
  if (!form) return;
  var role = document.getElementById("staff-role");
  var teaching = document.getElementById("teaching");
  var formClass = document.getElementById("form-class-field");
  var rows = document.getElementById("teach-rows");
  var add = document.getElementById("teach-add");
  var teachingRoles = teaching ? (teaching.dataset.teachingRoles || "").split(" ") : [];

  function sync() {
    if (role && teaching) {
      teaching.hidden = teachingRoles.indexOf(role.value) === -1;
      if (formClass) formClass.hidden = role.value !== "class_teacher";
    }
    if (rows) {
      var removes = rows.querySelectorAll(".teach-remove");
      removes.forEach(function (btn) { btn.disabled = removes.length <= 1; });
    }
  }

  if (add && rows) {
    add.addEventListener("click", function () {
      var last = rows.lastElementChild;
      var copy = last.cloneNode(true);
      // Keep the class picked on the row above: usually the same subject goes to several arms.
      copy.querySelector("select").value = "";
      copy.querySelector("input").value = last.querySelector("input").value;
      rows.appendChild(copy);
      copy.querySelector("select").focus();
      sync();
    });
    rows.addEventListener("click", function (e) {
      var btn = e.target.closest(".teach-remove");
      if (!btn || rows.children.length <= 1) return;
      btn.closest(".teach-row").remove();
      sync();
    });
  }
  if (role) role.addEventListener("change", sync);
  sync();
})();
