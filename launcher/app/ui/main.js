let info = null;
let syncing = false;

for (const [id, icon] of [["b-bug", "bug"], ["b-discord", "discord"], ["b-youtube", "youtube"], ["b-min", "min"], ["b-close", "close"]]) {
  $("#" + id).innerHTML = ICONS[icon];
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.h);
  toast.h = setTimeout(() => t.classList.remove("show"), 5000);
}

// ---------- журнал ----------
const MAX_LINES = 500;
function log(lines) {
  const box = $("#log");
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const tm = hhmmss();
  for (const line of lines) {
    const row = el("div", "ln");
    row.append(el("span", "tm", tm));
    const txt = el("span", "", line);
    if (line.startsWith("⚠")) txt.className = "warn";
    else if (line.startsWith("Ошибка")) txt.className = "err";
    else if (line.startsWith("Готово")) txt.className = "ok";
    row.append(txt);
    box.append(row);
  }
  while (box.childElementCount > MAX_LINES) box.firstChild.remove();
  if (stick) box.scrollTop = box.scrollHeight;
}

// ---------- состояние ----------
function render(i) {
  info = i;
  $("#tb-name").textContent = i.title;
  $("#tb-ver").textContent = "лаунчер " + i.launcher_version;
  $("#title").textContent = i.title;
  document.title = i.product;
  $("#v-installed").textContent = i.installed || "—";
  $("#v-server").textContent = i.server || "—";

  const st = $("#status");
  st.className = "status " + ({ latest: "", update: "warn", not_installed: "warn", broken: "warn", offline: "bad", busy: "warn busy" }[i.status] || "");
  $("#status-text").textContent = i.status_text;
  st.title = i.offline || "";
  const renderer = $("#renderer");
  renderer.replaceChildren(...i.renderers.map((r, index) => {
    const option = document.createElement("option");
    option.value = String(index); option.textContent = r.name; option.title = r.hint;
    return option;
  }));
  renderer.value = String(i.settings.renderer < i.renderers.length ? i.settings.renderer : 0);
  renderer.disabled = syncing;

  const sc = $("#seed-chip");
  sc.classList.toggle("hidden", !i.p2p);
  const sb = $("#seed");
  sb.replaceChildren();
  for (const [on, label] of [[true, "Вкл"], [false, "Выкл"]]) {
    const b = el("button", "seg-btn" + (i.seed === on ? " on" : ""), label);
    b.onclick = async () => {
      try { await invoke("set_seed", { on }); render(await invoke("info")); log([on ? "Раздача включена: другие игроки смогут качать игру и у вас." : "Раздача выключена."]); } catch (e) { toast(e); }
    };
    sb.append(b);
  }
  sc.title = "Раздавать игру другим игрокам, как в торренте" + (i.seed_sent ? ` · отдано ${bytes(i.seed_sent)}` : "") + (i.seed && !i.seeding ? " · начнётся, когда игра будет обновлена" : "");

  updateButtons();
  if (!syncing) idleProgress();
}

function updateButtons() {
  const play = $("#b-play");
  const s = info ? info.status : "";
  const master = s === "master";
  $("#b-check").classList.toggle("hidden", master);
  $("#b-verify").classList.toggle("hidden", master);
  $("#b-check").disabled = syncing;
  $("#b-verify").textContent = syncing ? "Остановить" : "Проверить файлы";
  $("#b-verify").disabled = !info || (!syncing && s === "not_installed" && !info.server);
  if (syncing) {
    play.textContent = "ИГРАТЬ";
    play.disabled = true;
  } else if (s === "not_installed") {
    play.textContent = "УСТАНОВИТЬ";
    play.disabled = !info.server;
  } else if (s === "update") {
    play.textContent = "ОБНОВИТЬ";
    play.disabled = false;
  } else {
    play.textContent = "ИГРАТЬ";
    play.disabled = !info || !info.can_play;
  }
}

function idleProgress() {
  const s = info ? info.status : "";
  const ready = s === "latest" || s === "master";
  $("#p-text").textContent = s === "master" ? "Мастер-копия игры — только запуск." : ready ? "Всё готово." : s === "update" ? "Доступно обновление" : s === "not_installed" ? `Игра не установлена${info.game_size ? " · " + bytes(info.game_size) : ""}` : s === "broken" ? "Нужна проверка файлов" : s === "offline" ? "Сервер недоступен" : "";
  $("#p-pct").textContent = ready ? "100%" : "";
  $("#p-bar").style.width = ready ? "100%" : "0%";
  $("#p-sub").textContent = s === "offline" && info.offline ? info.offline : "";
}

const PHASE = { prepare: "Подготовка", verify: "Проверка файлов", copy: "Сборка из локальных данных", download: "Загрузка", finish: "Завершение" };
listen("progress", (e) => {
  const p = e.payload;
  const dl = p.phase === "download";
  const done = dl ? p.net_done : p.done;
  const total = dl ? p.net_total : p.total;
  const frac = total > 0 ? Math.min(1, done / total) : 0;
  $("#p-text").textContent = PHASE[p.phase] || p.text;
  $("#p-pct").textContent = Math.floor(frac * 100) + "%";
  $("#p-bar").style.width = (frac * 100).toFixed(1) + "%";
  const parts = [];
  if (total > 0) parts.push(`${bytes(done)} из ${bytes(total)}`);
  if (p.speed > 0) parts.push(`${bytes(p.speed)}/с`);
  if (p.eta != null && p.speed > 0) parts.push("осталось " + eta(p.eta));
  if (p.files_total > 0) parts.push(`файлов ${p.files_done}/${p.files_total}`);
  if (p.net_peers > 0) parts.push(`от игроков ${bytes(p.net_peers)}`);
  $("#p-sub").textContent = parts.join("  ·  ");
});
listen("log", (e) => log(e.payload));
listen("sync-done", async (e) => {
  syncing = false;
  const d = e.payload;
  if (!d.ok && !d.cancelled) toast(d.message);
  render(await invoke("info"));
  if (d.ok) {
    $("#p-text").textContent = "Всё готово.";
    $("#p-pct").textContent = "100%";
    $("#p-bar").style.width = "100%";
    $("#p-sub").textContent = d.message;
  }
});

async function startSync(verify) {
  if (syncing) return;
  try {
    await invoke("start_sync", { verify });
    syncing = true;
    $("#p-text").textContent = verify ? "Проверка файлов" : "Подготовка";
    $("#p-pct").textContent = "";
    $("#p-bar").style.width = "0%";
    $("#p-sub").textContent = "";
    updateButtons();
    const s = $("#status");
    s.className = "status warn busy";
    $("#status-text").textContent = verify ? "Идёт проверка файлов…" : "Идёт обновление…";
  } catch (e) {
    toast(e);
  }
}

// ---------- кнопки ----------
$("#b-min").onclick = () => appWindow.minimize();
$("#b-close").onclick = () => invoke("quit");
for (const k of ["bug", "discord", "youtube"]) $("#b-" + k).onclick = () => invoke("open_link", { which: k }).catch(toast);

$("#b-check").onclick = async () => {
  $("#b-check").disabled = true;
  try {
    render(await invoke("check_update"));
    log([info.status === "update" ? `Доступна версия ${info.server}` : "Обновлений нет."]);
    if (info.status === "update" || info.status === "broken") startSync(false);
  } catch (e) {
    toast(e);
    log(["⚠ " + e]);
  } finally {
    $("#b-check").disabled = syncing;
  }
};
$("#b-verify").onclick = () => (syncing ? invoke("cancel_sync") : startSync(true));
$("#b-play").onclick = async () => {
  if (!info) return;
  if (info.status === "not_installed" || info.status === "update") return startSync(false);
  try { await invoke("play"); } catch (e) { toast(e); }
};

$("#renderer").onchange = async (e) => {
  try { await invoke("set_renderer", { index: Number(e.target.value) }); }
  catch (error) { toast(error); render(await invoke("info")); }
};
async function renderAddons(rows) {
  const box = $("#addons-list"); box.replaceChildren();
  for (const addon of rows) {
    const row = el("section", "addon");
    row.append(el("h3", "", addon.name + (addon.installed ? " · Установлен" : "")));
    row.append(el("p", "", addon.description), el("p", "addon-note", addon.requires));
    row.append(el("p", "addon-note", "Конфликты: " + addon.conflict_names.join(", ")));
    const conflict = rows.some(other => other.installed && addon.conflicts.includes(other.id));
    const button = el("button", "btn", addon.installed ? "Удалить" : conflict ? "Заменить меню" : "Установить");
    button.disabled = syncing || (!addon.installed && !addon.available);
    button.onclick = async () => {
      for (const b of box.querySelectorAll("button")) b.disabled = true;
      try {
        await renderAddons(await invoke("set_addon", { id: addon.id, install: !addon.installed, replaceConflicts: conflict }));
      } catch (error) { toast(error); await renderAddons(await invoke("list_addons")); }
    };
    row.append(button); box.append(row);
  }
}
$("#b-addons").onclick = async () => {
  try { await renderAddons(await invoke("list_addons")); $("#addons-dialog").showModal(); }
  catch (error) { toast(error); }
};
$("#addons-close").onclick = () => $("#addons-dialog").close();

// ---------- старт ----------
// Окно создаётся скрытым во время заставки; настоящий старт — по событию "booted".
let started = false;
async function onBooted() {
  if (started) return;
  started = true;
  render(await invoke("info"));
  if (info.busy) { syncing = true; updateButtons(); }
  else if (info.auto_update && (info.status === "update" || info.status === "broken")) startSync(false);
  else if (info.status === "master") log(["Мастер-копия игры: обновления и проверка файлов отключены."]);
  else if (info.status === "latest") log(["Установлена последняя версия " + info.installed + "."]);
  else if (info.status === "offline") log(["⚠ Нет связи с сервером: " + (info.offline || "")]);
  else if (info.status === "not_installed" && info.server) log([`Доступна версия ${info.server}. Нажмите «Установить».`]);
}
listen("booted", onBooted);
// Recheck the signed launcher release while the window stays open. This does
// not install game files or interrupt the game; its ordinary update remains a
// separate action. Offline checks stay quiet and retry at the next interval.
setInterval(async () => {
  if (!started || syncing || !info || info.status === "master" || document.hidden) return;
  try { render(await invoke("check_update")); } catch (_) { /* retry later */ }
}, 10 * 60 * 1000);
(async () => {
  render(await invoke("info"));
  if (!T) onBooted();
})();
