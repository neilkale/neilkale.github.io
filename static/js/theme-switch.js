const STORAGE_KEY = "preferred-theme";
const ICON_LEAVE_DURATION = 450;
const ICON_DROP_DURATION = 550;
const COLOR_TRANSITION_DURATION = ICON_LEAVE_DURATION + ICON_DROP_DURATION;
const ICON_DROP_DELAY = Math.max(COLOR_TRANSITION_DURATION - ICON_DROP_DURATION, ICON_LEAVE_DURATION);

const body = document.body;
const toggleButton = document.getElementById("theme-toggle");
const iconImages = toggleButton ? Array.from(toggleButton.querySelectorAll(".theme-toggle-icon")) : [];
const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
let activeIcon = iconImages.find((icon) => icon.classList.contains("is-active")) || null;
let isThemeTransitioning = false;

function systemTheme() {
  return mediaQuery.matches ? "dark" : "light";
}

function resetAllIcons() {
  iconImages.forEach((icon) => {
    icon.classList.remove("is-active", "no-transition", "is-leaving");
  });
}

function setActiveIcon(theme, { animate = true, delay = 0 } = {}) {
  if (!toggleButton || iconImages.length === 0) {
    return;
  }

  const nextIcon = iconImages.find((icon) => icon.dataset.theme === theme);
  if (!nextIcon) {
    return;
  }

  if (activeIcon === nextIcon && nextIcon.classList.contains("is-active")) {
    return;
  }

  if (!animate) {
    resetAllIcons();
    nextIcon.classList.add("no-transition");
    nextIcon.classList.add("is-active");
    void nextIcon.offsetWidth;
    nextIcon.classList.remove("no-transition");
    activeIcon = nextIcon;
    return;
  }

  if (!activeIcon) {
    resetAllIcons();
    nextIcon.classList.add("is-active");
    activeIcon = nextIcon;
    return;
  }

  const currentIcon = activeIcon;
  const dropDelay = Math.max(delay, ICON_LEAVE_DURATION);

  const handleLeaveEnd = (event) => {
    if (event.target !== currentIcon || event.propertyName !== "transform") {
      return;
    }

    currentIcon.removeEventListener("transitionend", handleLeaveEnd);
    currentIcon.classList.remove("is-leaving", "is-active");
  };

  currentIcon.classList.remove("is-leaving");
  currentIcon.addEventListener("transitionend", handleLeaveEnd);

  requestAnimationFrame(() => {
    currentIcon.classList.add("is-leaving");
  });

  setTimeout(() => {
    resetAllIcons();
    nextIcon.classList.add("is-active");
    activeIcon = nextIcon;
  }, dropDelay);
}

function updateToggle(currentTheme, options = {}) {
  if (!toggleButton) {
    return;
  }

  const { animateIcon = true, skipIcon = false, iconDelay = 0 } = options;
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  toggleButton.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
  toggleButton.setAttribute("title", `Switch to ${nextTheme} mode`);
  if (!skipIcon) {
    setActiveIcon(currentTheme, { animate: animateIcon, delay: iconDelay });
  }
}

function applyTheme(theme, options = {}) {
  const { animateIcon = true, skipIcon = false, iconDelay = 0 } = options;

  body.classList.remove("auto", "light", "dark");

  if (theme === "auto") {
    body.classList.add("auto");
    const resolved = systemTheme();
    body.classList.add(resolved);
    updateToggle(resolved, { animateIcon, skipIcon, iconDelay });
    return;
  }

  body.classList.add(theme);
  updateToggle(theme, { animateIcon, skipIcon, iconDelay });
}

function remember(theme) {
  if (theme === "auto") {
    localStorage.removeItem(STORAGE_KEY);
    return;
  }

  localStorage.setItem(STORAGE_KEY, theme);
}

function initTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);

  if (stored === "light" || stored === "dark") {
    applyTheme(stored, { animateIcon: false });
    return stored;
  }

  if (body.classList.contains("dark")) {
    applyTheme("dark", { animateIcon: false });
    return "dark";
  }

  applyTheme("auto", { animateIcon: false });
  return "auto";
}

function handleToggle() {
  if (!toggleButton) {
    return;
  }

  toggleButton.addEventListener("click", () => {
    const next = body.classList.contains("dark") ? "light" : "dark";
    transitionTheme(next, () => remember(next));
  });
}

function transitionTheme(nextTheme, onComplete) {
  if (isThemeTransitioning) {
    return;
  }

  const currentTheme = body.classList.contains("dark") ? "dark" : "light";
  if (nextTheme === currentTheme) {
    return;
  }

  isThemeTransitioning = true;

  applyTheme(nextTheme, { animateIcon: false, skipIcon: true });
  setActiveIcon(nextTheme, { animate: true, delay: ICON_DROP_DELAY });

  setTimeout(() => {
    isThemeTransitioning = false;
    if (typeof onComplete === "function") {
      onComplete();
    }
  }, COLOR_TRANSITION_DURATION);
}

function handleSystemChange() {
  if (localStorage.getItem(STORAGE_KEY)) {
    return;
  }

  applyTheme("auto");
}

if (typeof mediaQuery.addEventListener === "function") {
  mediaQuery.addEventListener("change", handleSystemChange);
} else if (typeof mediaQuery.addListener === "function") {
  mediaQuery.addListener(handleSystemChange);
}

const initialTheme = initTheme();

if (initialTheme === "auto") {
  remember("auto");
}

handleToggle();

