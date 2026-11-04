// Extras only: every page works without this file.

// The Appearance choice on the Settings page. theme.js applies it on every page.
function setUpTheme() {
  const section = document.querySelector("[data-theme-settings]");
  if (!section) return;
  const root = document.documentElement;
  section.hidden = false;
  section.querySelectorAll('input[name="theme"]').forEach((choice) => {
    choice.checked = choice.value === (root.dataset.theme || "system");
    choice.addEventListener("change", () => {
      try {
        if (choice.value === "system") {
          delete root.dataset.theme;
          localStorage.removeItem("hirewire-theme");
        } else {
          root.dataset.theme = choice.value;
          localStorage.setItem("hirewire-theme", choice.value);
        }
      } catch (error) {
        // Storage can be blocked. The theme still changes for this page.
      }
    });
  });
}

function setUpMenu() {
  const button = document.querySelector("[data-menu-button]");
  const menu = document.getElementById(button && button.getAttribute("aria-controls"));
  if (!button || !menu) return;
  button.hidden = false;
  const setOpen = (open) => {
    button.setAttribute("aria-expanded", open);
    menu.classList.toggle("is-open", open);
  };
  button.addEventListener("click", () => setOpen(button.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

function setUpUserMenu() {
  const menu = document.querySelector("[data-user-menu]");
  if (!menu) return;
  document.addEventListener("click", (event) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
}

function setUpConfirm() {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
}

// Messages float as toasts. Good news fades after 5 seconds (not while pointed at or
// focused); a problem stays until closed, so nobody misses it.
function setUpToasts() {
  document.querySelectorAll("[data-flash]").forEach((toast) => {
    const close = toast.querySelector("[data-flash-close]");
    close.hidden = false;
    const leave = () => {
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), 300);
    };
    close.addEventListener("click", leave);
    if ("stays" in toast.dataset) return;
    let timer = setTimeout(leave, 5000);
    const pause = () => clearTimeout(timer);
    const resume = () => { clearTimeout(timer); timer = setTimeout(leave, 3000); };
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusout", resume);
  });
}

// "Copy" buttons next to a recovery code or a calendar link. Where the browser has no
// clipboard (an http address), the text is selected for Ctrl+C instead.
function setUpCopy() {
  document.querySelectorAll("[data-copy-button]").forEach((button) => {
    const source = button.closest(".card, .setting").querySelector("[data-copy-text]");
    if (!source) return;
    if (!navigator.clipboard && !("copyAnywhere" in button.dataset)) return;
    button.hidden = false;
    const label = button.textContent;
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(source.value || source.textContent.trim());
        button.textContent = "Copied";
      } catch (error) {
        if (source.select) source.select();
        button.textContent = "Selected: press Ctrl+C";
      }
      setTimeout(() => { button.textContent = label; }, 2500);
    });
  });
}

// Settings: each Save button looks asleep until its form has a change, then wakes up
// and says so. It still works either way (and without JavaScript it is always awake).
function setUpUnsavedChanges() {
  document.querySelectorAll("form[data-watch-changes]").forEach((form) => {
    const button = form.querySelector("button[type=submit]");
    if (!button || button.closest("fieldset:disabled")) return;
    const note = document.createElement("span");
    note.className = "unsaved-note";
    note.textContent = "Unsaved changes";
    note.hidden = true;
    button.before(note);
    const snapshot = () => new URLSearchParams(new FormData(form)).toString();
    const start = snapshot();
    const update = () => {
      const changed = snapshot() !== start;
      button.classList.toggle("is-waiting", !changed);
      note.hidden = !changed;
    };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    update();
  });
}

// Ticking a stage or choosing a source shows the result straight away.
// Typed fields still wait for the Search or Apply button.
function setUpFilters() {
  const form = document.querySelector("[data-filters]");
  if (!form) return;
  form.addEventListener("change", (event) => {
    if (event.target.matches("input[type=checkbox], select")) form.requestSubmit();
  });
  // Empty fields stay out of the address, so a bookmarked filter is short: ?stage=interview,
  // not ?q=&stage=interview&source=&location=... (a disabled field isn't sent).
  form.addEventListener("submit", () => {
    form.querySelectorAll("input[name], select[name]").forEach((field) => {
      if (field.type !== "checkbox" && field.value === "") field.disabled = true;
    });
  });
}

// A click anywhere on a table row or a Board card opens its page (the title is the
// real link, for keyboards). A drag on the Board never fires a click.
function setUpRowLinks() {
  document.querySelectorAll("tr[data-href], .board-card[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, select, label, details")) return;
      if (String(getSelection())) return;  // selecting text to copy isn't a click to open
      location.href = row.dataset.href;
    });
  });
}

// The filter panel stays open while you tick boxes (each tick reloads the page).
function setUpFilterPanel() {
  const panel = document.querySelector("[data-filter-panel]");
  if (!panel) return;
  try {
    if (sessionStorage.getItem("hirewire-filters-open") === "yes") panel.open = true;
  } catch (error) {
    // Storage can be blocked. The panel just starts closed.
  }
  panel.addEventListener("toggle", () => {
    try {
      sessionStorage.setItem("hirewire-filters-open", panel.open ? "yes" : "no");
    } catch (error) {
      // Nothing to remember it in.
    }
  });
}

// ---------- The Board ----------

// The server decides (workflow.py): a drop is only offered where the card may
// go, and if the server still refuses, the card stays where it was.
function setUpBoard() {
  const board = document.querySelector("[data-board]");
  if (!board) return;
  const status = document.querySelector("[data-board-status]");
  const labels = JSON.parse(board.dataset.labels);
  const closed = board.dataset.closed.split(" ");
  let dragged = null;

  const zones = () => board.querySelectorAll("[data-drop]");
  const recount = () => {
    board.querySelectorAll(".board-column").forEach((column) => {
      const count = column.querySelector("[data-count]");
      // The Closed column counts every closed application, not only the ones shown.
      if (!column.classList.contains("board-closed")) count.textContent = column.querySelectorAll(".board-card").length;
    });
  };
  const finish = () => {
    if (dragged) dragged.classList.remove("is-dragged");
    dragged = null;
    board.classList.remove("is-dragging");
    zones().forEach((zone) => zone.classList.remove("can-drop", "is-over"));
  };

  const place = (card, answer) => {
    const wasClosed = card.closest(".board-closed") !== null;
    card.dataset.moves = answer.moves.join(" ");
    const select = card.querySelector("select[name=to]");
    select.replaceChildren(...answer.moves.map((stage) => new Option(labels[stage], stage)));
    const stageBox = card.querySelector(".board-card-stage");
    stageBox.replaceChildren();
    if (closed.includes(answer.stage)) {
      const pill = document.createElement("span");
      pill.className = `stage stage-${answer.stage}`;
      pill.textContent = answer.label;
      stageBox.append(pill);
      board.querySelector("[data-closed-list]").prepend(card);
    } else {
      board.querySelector(`.board-column[data-drop="${answer.stage}"] .board-cards`).prepend(card);
    }
    const closedCount = board.querySelector(".board-closed [data-count]");
    const nowClosed = closed.includes(answer.stage);
    if (nowClosed !== wasClosed) closedCount.textContent = Number(closedCount.textContent) + (nowClosed ? 1 : -1);
    recount();
  };

  board.addEventListener("dragstart", (event) => {
    const card = event.target.closest(".board-card");
    if (!card) return;
    dragged = card;
    card.classList.add("is-dragged");
    board.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.jobId);
    const moves = card.dataset.moves.split(" ");
    zones().forEach((zone) => zone.classList.toggle("can-drop", moves.includes(zone.dataset.drop)));
  });
  board.addEventListener("dragend", finish);
  board.addEventListener("dragover", (event) => {
    const zone = event.target.closest("[data-drop]");
    if (!zone || !zone.classList.contains("can-drop")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    zones().forEach((other) => other.classList.toggle("is-over", other === zone));
  });
  board.addEventListener("drop", async (event) => {
    const zone = event.target.closest("[data-drop]");
    const card = dragged;
    if (!zone || !card || !zone.classList.contains("can-drop")) return;
    event.preventDefault();
    finish();
    const body = new URLSearchParams({ csrf_token: board.dataset.csrf, to: zone.dataset.drop, from: "board" });
    try {
      const response = await fetch(card.dataset.moveUrl, {
        method: "POST", body, headers: { Accept: "application/json" },
      });
      const answer = await response.json();
      if (response.ok) {
        place(card, answer);
        status.textContent = `Moved to ${answer.label}.`;
      } else {
        status.textContent = answer.error;
      }
    } catch (error) {
      status.textContent = "The card couldn't be moved. Check your connection, or reload the page.";
    }
  });
}

// The demo's note can be closed. It stays closed until the browser is closed.
function setUpDemoNote() {
  const note = document.querySelector("[data-demo-note]");
  if (!note) return;
  const button = note.querySelector("[data-demo-close]");
  try {
    if (sessionStorage.getItem("hirewire-demo-note") === "hidden") note.hidden = true;
  } catch (error) {
    // Storage can be blocked. The note just shows again on the next page.
  }
  button.hidden = false;
  button.addEventListener("click", () => {
    note.hidden = true;
    try {
      sessionStorage.setItem("hirewire-demo-note", "hidden");
    } catch (error) {
      // Hidden on this page only.
    }
  });
}

setUpTheme();
setUpToasts();
setUpDemoNote();
setUpMenu();
setUpUserMenu();
setUpConfirm();
setUpCopy();
setUpUnsavedChanges();
setUpFilters();
setUpFilterPanel();
setUpRowLinks();
setUpBoard();
