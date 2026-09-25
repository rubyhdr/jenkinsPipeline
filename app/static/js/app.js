// Progressive enhancement: live search, confirm prompts and auto-hiding flash messages.
(function () {
  "use strict";

  function debounce(fn, wait) {
    let timer;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function initLiveSearch() {
    const form = document.querySelector("[data-live-search]");
    const results = document.getElementById("results");
    if (!form || !results) return;

    const genreInput = form.querySelector("input[name=genre]");
    let controller;

    function refresh() {
      const params = new URLSearchParams(new FormData(form));
      for (const [key, value] of Array.from(params.entries())) {
        if (!value) params.delete(key);
      }
      history.replaceState(null, "", params.toString() ? "?" + params : location.pathname);
      params.set("partial", "1");

      if (controller) controller.abort();
      controller = new AbortController();
      fetch("/?" + params, { signal: controller.signal, headers: { "X-Requested-With": "fetch" } })
        .then(function (res) { return res.ok ? res.text() : Promise.reject(res.status); })
        .then(function (html) { results.innerHTML = html; })
        .catch(function () { /* aborted or offline: keep current results */ });
    }

    form.addEventListener("input", debounce(refresh, 200));
    form.addEventListener("submit", function (event) { event.preventDefault(); refresh(); });

    document.querySelectorAll("[data-genre]").forEach(function (chip) {
      chip.addEventListener("click", function (event) {
        event.preventDefault();
        genreInput.value = chip.dataset.genre;
        document.querySelectorAll("[data-genre]").forEach(function (c) {
          c.classList.toggle("chip-active", c === chip);
        });
        refresh();
      });
    });
  }

  function initConfirms() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      });
    });
  }

  function initFlashes() {
    document.querySelectorAll(".flash-success, .flash-info").forEach(function (flash) {
      setTimeout(function () { flash.classList.add("is-hidden"); }, 4000);
      setTimeout(function () { flash.remove(); }, 4500);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initLiveSearch();
    initConfirms();
    initFlashes();
  });
})();
