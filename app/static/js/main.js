/**
 * Earn & Pay — Accessible Progressive Enhancement Script (Phase 4)
 * Handles mobile navigation toggle, Escape key dismissal, and form loading states.
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // 1. Mobile Navigation Toggle
    const navToggle = document.querySelector("[data-nav-toggle]");
    const siteNav = document.querySelector("[data-site-nav]");

    if (navToggle && siteNav) {
      navToggle.addEventListener("click", function () {
        const isExpanded = navToggle.getAttribute("aria-expanded") === "true";
        navToggle.setAttribute("aria-expanded", String(!isExpanded));
        siteNav.classList.toggle("is-open", !isExpanded);
      });

      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && siteNav.classList.contains("is-open")) {
          navToggle.setAttribute("aria-expanded", "false");
          siteNav.classList.remove("is-open");
          navToggle.focus();
        }
      });
    }

    // 2. Dismissible Flash Banners
    const dismissButtons = document.querySelectorAll("[data-dismiss-flash]");
    dismissButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        const banner = button.closest(".flash-banner");
        if (banner) {
          banner.remove();
        }
      });
    });

    // 3. Double-Submit Prevention on Forms
    const forms = document.querySelectorAll("form[data-prevent-double-submit]");
    forms.forEach(function (form) {
      form.addEventListener("submit", function () {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn && !submitBtn.disabled) {
          const loadingText = submitBtn.getAttribute("data-loading-text");
          if (loadingText) {
            submitBtn.textContent = loadingText;
          }
          submitBtn.disabled = true;
        }
      });
    });
  });
})();
