(function () {
  const storageKey = "pulps-theme";

  function preferredTheme() {
    try {
      const savedTheme = window.localStorage.getItem(storageKey);
      if (savedTheme === "dark" || savedTheme === "light") {
        return savedTheme;
      }
    } catch (error) {
      return "light";
    }
    return "light";
  }

  function applyTheme(theme) {
    const normalizedTheme = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = normalizedTheme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const isDark = normalizedTheme === "dark";
      button.setAttribute("aria-pressed", String(isDark));
      button.setAttribute("title", isDark ? "Switch to light mode" : "Switch to dark mode");
      button.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
      button.querySelectorAll("[data-theme-icon]").forEach((icon) => {
        icon.textContent = isDark ? "☀" : "☾";
      });
    });
  }

  function setTheme(theme) {
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch (error) {
      // Theme still applies for this page view when storage is unavailable.
    }
    applyTheme(theme);
  }

  applyTheme(preferredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(preferredTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
        setTheme(currentTheme === "dark" ? "light" : "dark");
      });
    });
  });
})();
