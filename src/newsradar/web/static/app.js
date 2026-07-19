document.documentElement.classList.add("js");

const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector("#site-nav");

if (navToggle && siteNav) {
  navToggle.setAttribute("aria-expanded", "false");
  siteNav.dataset.open = "false";
  navToggle.addEventListener("click", () => {
    const expanded = navToggle.getAttribute("aria-expanded") === "true";
    navToggle.setAttribute("aria-expanded", String(!expanded));
    siteNav.dataset.open = String(!expanded);
  });
}

const activeDailyRun = document.querySelector('[data-active-daily-run="true"]');

if (activeDailyRun) {
  window.setTimeout(() => window.location.reload(), 10000);
}

for (const button of document.querySelectorAll("[data-copy-web-console-url]")) {
  button.addEventListener("click", async () => {
    const status = document.querySelector("[data-copy-web-console-status]");
    const url = button.dataset.copyWebConsoleUrl;
    try {
      if (!url || !navigator.clipboard?.writeText) throw new Error("clipboard_unavailable");
      await navigator.clipboard.writeText(url);
      if (status) status.textContent = "已复制本机网页地址";
    } catch {
      if (status) status.textContent = "无法自动复制，请手动复制上方地址";
    }
  });
}

for (const form of document.querySelectorAll("[data-report-selection]")) {
  const selectors = Array.from(document.querySelectorAll("[data-report-selector]"));
  const selectAll = document.querySelector("[data-select-all-reports]");
  const buttons = Array.from(form.querySelectorAll("button[type='submit']"));
  const count = form.querySelector("[data-selected-report-count]");

  const syncSelection = () => {
    const selected = selectors.filter((selector) => selector.checked).length;
    for (const button of buttons) button.disabled = selected === 0;
    if (count) count.textContent = selected ? `已选择 ${selected} 份日报` : "尚未选择日报";
    if (selectAll) selectAll.checked = selected > 0 && selected === selectors.length;
  };

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      for (const selector of selectors) selector.checked = selectAll.checked;
      syncSelection();
    });
  }
  for (const selector of selectors) selector.addEventListener("change", syncSelection);
  syncSelection();
}
