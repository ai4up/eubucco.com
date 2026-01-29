// Theme toggle controller: keeps DaisyUI data-theme and Tailwind dark class in sync
(function () {
  const THEME_KEY = "ui-theme";
  const THEMES = { light: "pastel", dark: "night" };

  const getStoredTheme = () => {
    try {
      const stored = localStorage.getItem(THEME_KEY);
      if (stored === "light" || stored === "dark") {
        return stored;
      }
    } catch (err) {
      // ignore storage errors
    }
    return "dark";
  };

  const updateIcons = (mode) => {
    document.querySelectorAll('[data-theme-icon="sun"]').forEach((el) => {
      el.classList.toggle("hidden", mode !== "dark");
    });
    document.querySelectorAll('[data-theme-icon="moon"]').forEach((el) => {
      el.classList.toggle("hidden", mode !== "light");
    });
  };

  const setTheme = (mode) => {
    const normalized = mode === "light" ? "light" : "dark";
    const root = document.documentElement;
    root.dataset.theme = THEMES[normalized];
    root.classList.toggle("dark", normalized === "dark");
    try {
      localStorage.setItem(THEME_KEY, normalized);
    } catch (err) {
      // ignore storage errors
    }
    updateIcons(normalized);
  };

  window.addEventListener("DOMContentLoaded", () => {
    // Apply stored preference (fallback to dark). Initial HTML already defaults to dark to avoid flash.
    setTheme(getStoredTheme());

    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = getStoredTheme() === "light" ? "dark" : "light";
        setTheme(next);
      });
    });
  });
})();

