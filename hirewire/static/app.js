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

// "Copy" buttons next to a recovery code or a calendar link.
function setUpCopy() {
  document.querySelectorAll("[data-copy-button]").forEach((button) => {
    const source = button.closest(".card, .setting").querySelector("[data-copy-text]");
    if (!source || !navigator.clipboard) return;
    button.hidden = false;
    const label = button.textContent;
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(source.value || source.textContent.trim());
        button.textContent = "Copied";
      } catch (error) {
        button.textContent = "Copy didn't work";
      }
      setTimeout(() => { button.textContent = label; }, 2000);
    });
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

setUpTheme();
setUpMenu();
setUpUserMenu();
setUpConfirm();
setUpCopy();
setUpBoard();
