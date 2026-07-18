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
