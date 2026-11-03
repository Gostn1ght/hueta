// Мост к Rust. Без Tauri (открыто в обычном браузере) — демо-данные для вёрстки.
const T = window.__TAURI__;
const invoke = T ? T.core.invoke : (cmd, a) => Mock.invoke(cmd, a);
const listen = T ? T.event.listen : (ev, cb) => Mock.listen(ev, cb);
const appWindow = T ? T.window.getCurrentWindow() : { minimize() {}, startDragging() {} };

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

function bytes(n) {
  if (n == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2) : n) .toString().replace(".", ",") + " " + u[i];
}

function eta(s) {
  if (s == null || !isFinite(s)) return "";
  if (s > 86400) return "больше суток";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h} ч ${m} мин` : m ? `${m} мин ${x} с` : `${x} с`;
}

function hhmmss() {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((v) => String(v).padStart(2, "0")).join(":");
}

// Перетаскивание окна за заголовок (data-tauri-drag-region тоже работает, это запасной путь).
document.addEventListener("mousedown", (e) => {
  if (e.button === 0 && e.target.closest("[data-drag]") && !e.target.closest("button,input,a")) {
    appWindow.startDragging();
  }
});
document.addEventListener("contextmenu", (e) => {
  if (!e.target.closest("input,.log")) e.preventDefault();
});

const ICONS = {
  bug: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3a4 4 0 0 1 4 4v.3A6 6 0 0 1 18 11h2v2h-2v1h2v2h-2.3A6 6 0 0 1 6.3 16H4v-2h2v-1H4v-2h2a6 6 0 0 1 2-3.7V7a4 4 0 0 1 4-4Zm0 2a2 2 0 0 0-2 2v.1a6 6 0 0 1 4 0V7a2 2 0 0 0-2-2Zm-1 6v6h2v-6h-2Z"/></svg>',
  discord: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.6 5.6A17 17 0 0 0 15.4 4l-.5 1a15.7 15.7 0 0 0-5.8 0l-.5-1a17 17 0 0 0-4.2 1.6C1.8 9.6 1.1 13.5 1.4 17.3a17 17 0 0 0 5.2 2.7l1.1-1.8a11 11 0 0 1-1.7-.8l.4-.3a12 12 0 0 0 11.2 0l.4.3c-.5.3-1.1.6-1.7.8l1.1 1.8a17 17 0 0 0 5.2-2.7c.4-4.4-.7-8.3-3-11.7ZM8.6 15c-1 0-1.9-1-1.9-2.2s.8-2.2 1.9-2.2 1.9 1 1.9 2.2-.8 2.2-1.9 2.2Zm6.8 0c-1 0-1.9-1-1.9-2.2s.8-2.2 1.9-2.2 1.9 1 1.9 2.2-.8 2.2-1.9 2.2Z"/></svg>',
  youtube: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.5 7.2a2.8 2.8 0 0 0-2-2C18.8 4.7 12 4.7 12 4.7s-6.8 0-8.5.5a2.8 2.8 0 0 0-2 2A29 29 0 0 0 1 12a29 29 0 0 0 .5 4.8 2.8 2.8 0 0 0 2 2c1.7.5 8.5.5 8.5.5s6.8 0 8.5-.5a2.8 2.8 0 0 0 2-2A29 29 0 0 0 23 12a29 29 0 0 0-.5-4.8ZM9.8 15V9l5.7 3-5.7 3Z"/></svg>',
  min: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 12h14"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
};

// ---------- демо-режим для просмотра вёрстки в браузере ----------
const Mock = {
  handlers: {},
  listen(ev, cb) { (this.handlers[ev] ||= []).push(cb); return Promise.resolve(() => {}); },
  emit(ev, payload) { (this.handlers[ev] || []).forEach((cb) => cb({ payload })); },
  async invoke(cmd) {
    const info = {
      product: "NetAnomaly", title: "NETANOMALY", launcher_version: "1.0.0",
      installed: "1.9.9.5(beta)", server: "1.9.9.5(beta)", game_size: 96e9,
      status: "latest", status_text: "Установлена последняя версия", offline: null,
      renderers: [{ name: "DirectX 11", hint: "", exe: "", args: "" }, { name: "R1", hint: "", exe: "", args: "" }],
      settings: { renderer: 0, ip: "", port: "", login: "", password: "" },
      busy: false, can_play: true, auto_update: false,
    };
    switch (cmd) {
      case "info": return info;
      case "check_update": return info;
      case "news": return [{ title: "Лаунчер 1.0", date: "01.10.2026", text: "Мы полностью переделали лаунчер. Старая версия работала не так, как хотелось: могла зависнуть на большом обновлении.", image: "assets/bg.jpg", link: "" }];
      case "boot":
        for (const [t, p] of [["Проверка файлов игры…", 0.2], ["Найдены все файлы игры (34)", 0.8]]) {
          this.emit("splash", { text: t, pct: p });
          await new Promise((r) => setTimeout(r, 400));
        }
        return null;
      case "setup_info": return { product: "NetAnomaly", title: "NETANOMALY", version: "1.0.0", default_dir: "C:\\Games\\NetAnomaly", existing: true, text: "Установщик поставит свежую версию лаунчера — игра и ваши настройки останутся на месте.", game_size: 96e9 };
      case "dir_info": return { free: 70e9, free_text: "Свободно на C: 65,85 ГБ", has_game: true, message: "Игра уже есть в этой папке — докачаются только изменения." };
      case "start_sync":
        let p = 0;
        const t = setInterval(() => {
          p += 0.04;
          this.emit("progress", { phase: "download", text: "Загрузка", done: p * 5e9, total: 5e9, net_done: p * 4e9, net_total: 4e9, speed: 48e6, eta: Math.round((1 - p) * 90), files_done: Math.round(p * 120), files_total: 120 });
          this.emit("log", ["✓ resources/textures/act/act_stalker_" + Math.round(p * 100) + ".dds"]);
          if (p >= 1) { clearInterval(t); this.emit("sync-done", { ok: true, cancelled: false, message: "Готово за 38 с. Версия 1.9.9.5(beta)." }); }
        }, 250);
        return null;
      default: return null;
    }
  },
};
