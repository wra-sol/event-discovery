(function () {
  function getInitialMode() {
    try {
      const stored = window.localStorage.getItem("theme");
      if (stored === "light" || stored === "dark" || stored === "auto") {
        return stored;
      }
    } catch (_) {
      /* ignore */
    }
    return "auto";
  }

  function applyThemeMode(mode) {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const resolved = mode === "auto" ? (prefersDark ? "dark" : "light") : mode;
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(resolved);
    if (mode === "auto") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", mode);
    }
    root.style.colorScheme = resolved;
  }

  function labelForMode(mode) {
    if (mode === "auto") {
      return "Color theme: Auto (follows device). Activate to use light mode.";
    }
    if (mode === "dark") {
      return "Color theme: Dark. Activate to use automatic (device) mode.";
    }
    return "Color theme: Light. Activate to use dark mode.";
  }

  function syncToggleButton() {
    const btn = document.getElementById("themeToggle");
    if (!btn) {
      return;
    }
    const mode = getInitialMode();
    btn.textContent = mode === "auto" ? "Auto" : mode === "dark" ? "Dark" : "Light";
    btn.setAttribute("aria-label", labelForMode(mode));
  }

  function cycleTheme() {
    const mode = getInitialMode();
    const next = mode === "light" ? "dark" : mode === "dark" ? "auto" : "light";
    try {
      window.localStorage.setItem("theme", next);
    } catch (_) {
      /* ignore */
    }
    applyThemeMode(next);
    syncToggleButton();
  }

  function init() {
    syncToggleButton();
    const btn = document.getElementById("themeToggle");
    if (btn) {
      btn.addEventListener("click", cycleTheme);
    }

    const skip = document.querySelector(".skip-link");
    const main = document.getElementById("main-content");
    if (skip && main) {
      skip.addEventListener("click", function () {
        queueMicrotask(function () {
          main.focus({ preventScroll: false });
        });
      });
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", function () {
      if (getInitialMode() === "auto") {
        applyThemeMode("auto");
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
