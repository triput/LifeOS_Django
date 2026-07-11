(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  window.lifeosSyncPaletteViewContext = function () {
    var root = document.querySelector("[data-views-surface]");
    var surface = document.getElementById("palette-view-surface");
    var query = document.getElementById("palette-view-query");
    if (!surface || !query) return;
    if (root) {
      surface.value = root.getAttribute("data-views-surface") || "";
      query.value = root.getAttribute("data-views-query") || "";
    } else {
      surface.value = "";
      query.value = "";
    }
  };

  function fetchHeaders() {
    return {
      "X-Requested-With": "XMLHttpRequest",
      "HX-Request": "true",
      "X-CSRFToken": csrfToken(),
    };
  }

  window.lifeosOpenDrawer = function () {
    var panel = document.getElementById("drawer-panel");
    if (!panel) return;
    panel.style.transform = "translateX(0)";
    panel.style.pointerEvents = "auto";
    panel.setAttribute("aria-hidden", "false");
    var backdrop = document.getElementById("drawer-backdrop");
    if (backdrop) backdrop.style.display = "block";
  };

  window.lifeosCloseDrawer = function () {
    var panel = document.getElementById("drawer-panel");
    if (!panel) return false;
    // Prefer aria-hidden: browsers often serialize translateX(0) as translateX(0px),
    // so an exact transform string match falsely reports the drawer as closed.
    if (panel.getAttribute("aria-hidden") === "true") return false;
    panel.style.transform = "translateX(100%)";
    panel.style.pointerEvents = "none";
    panel.setAttribute("aria-hidden", "true");
    var backdrop = document.getElementById("drawer-backdrop");
    if (backdrop) backdrop.style.display = "none";
    return true;
  };

  /** Convert weather band cutoff inputs when Imperial checkbox toggles (DEF-P33-005). */
  window.lifeosConvertWeatherBandInputs = function (toImperial) {
    var inputs = document.querySelectorAll("[data-weather-band]");
    inputs.forEach(function (el) {
      var v = parseFloat(el.value);
      if (isNaN(v)) return;
      var next = toImperial ? v * 9 / 5 + 32 : (v - 32) * 5 / 9;
      el.value = Math.round(next * 10) / 10;
    });
    var unit = document.getElementById("weather-band-unit");
    if (unit) unit.textContent = toImperial ? "°F" : "°C";
  };

  function lifeosGeoStatus(msg, isError) {
    var el = document.getElementById("settings-geo-status");
    if (!el) return;
    el.textContent = msg || "";
    el.className = isError
      ? "text-[10px] font-mono text-orange-400"
      : "text-[10px] font-mono text-cockpit-faint";
  }

  function lifeosRoundCoord(n) {
    return Math.round(Number(n) * 10000) / 10000;
  }

  /** Optional reverse label via Open-Meteo (BL-TELE-004). */
  function lifeosReverseGeocodeLabel(lat, lon) {
    var url =
      "https://geocoding-api.open-meteo.com/v1/reverse?latitude=" +
      encodeURIComponent(lat) +
      "&longitude=" +
      encodeURIComponent(lon) +
      "&language=en&format=json";
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("reverse " + res.status);
        return res.json();
      })
      .then(function (data) {
        var r = data && data.results && data.results[0];
        if (!r) return "";
        var parts = [];
        if (r.name) parts.push(r.name);
        if (r.admin1 && r.admin1 !== r.name) parts.push(r.admin1);
        if (r.country_code && r.country_code !== "US" && r.country) parts.push(r.country);
        else if (r.country_code === "US" && r.admin1) {
          /* city, state already covered */
        }
        return parts.join(", ").slice(0, 255);
      })
      .catch(function () {
        return "";
      });
  }

  /** Browser geolocation → Settings lat/lon (+ optional label). Save to persist. */
  window.lifeosDetectWeatherLocation = function () {
    var latEl = document.getElementById("settings-latitude");
    var lonEl = document.getElementById("settings-longitude");
    var nameEl = document.getElementById("settings-location-name");
    if (!latEl || !lonEl) return;
    if (!navigator.geolocation) {
      lifeosGeoStatus("Geolocation is not available in this browser.", true);
      return;
    }
    lifeosGeoStatus("Detecting location…");
    navigator.geolocation.getCurrentPosition(
      function (pos) {
        var lat = lifeosRoundCoord(pos.coords.latitude);
        var lon = lifeosRoundCoord(pos.coords.longitude);
        latEl.value = String(lat);
        lonEl.value = String(lon);
        lifeosGeoStatus("Coordinates filled — Save general to persist.");
        lifeosReverseGeocodeLabel(lat, lon).then(function (label) {
          if (label && nameEl) {
            nameEl.value = label;
            lifeosGeoStatus("Location detected — Save general to persist.");
          }
        });
      },
      function (err) {
        var msg = "Could not detect location.";
        if (err && err.code === 1) msg = "Location permission denied.";
        else if (err && err.code === 2) msg = "Location unavailable.";
        else if (err && err.code === 3) msg = "Location request timed out.";
        lifeosGeoStatus(msg + " Enter coordinates manually.", true);
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 }
    );
  };

  /** Typed city/state(/country) → lat/lon via server geocoder (BL-TELE-005). */
  window.lifeosResolveLocationFromLabel = function () {
    var nameEl = document.getElementById("settings-location-name");
    var latEl = document.getElementById("settings-latitude");
    var lonEl = document.getElementById("settings-longitude");
    var btn = document.getElementById("settings-resolve-location");
    if (!nameEl || !latEl || !lonEl) return;
    var label = (nameEl.value || "").trim();
    if (!label) {
      lifeosGeoStatus("Enter a place like Phoenix, AZ first.", true);
      return;
    }
    var url = (btn && btn.getAttribute("data-geocode-url")) || "/settings/geocode/";
    lifeosGeoStatus("Resolving “" + label + "”…");
    var body = new URLSearchParams();
    body.set("location_name", label);
    fetch(url, {
      method: "POST",
      headers: fetchHeaders(),
      credentials: "same-origin",
      body: body,
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { status: res.status, data: data };
        });
      })
      .then(function (pack) {
        var data = pack.data || {};
        if (!data.ok || data.latitude == null || data.longitude == null) {
          lifeosGeoStatus(data.message || "Could not resolve place.", true);
          return;
        }
        latEl.value = String(data.latitude);
        lonEl.value = String(data.longitude);
        if (data.label) nameEl.value = data.label;
        lifeosGeoStatus((data.message || "Resolved.") + " Save general to persist.");
      })
      .catch(function () {
        lifeosGeoStatus("Geocode request failed — try again or enter lat/lon.", true);
      });
  };

  window.lifeosOpenDrawerUrl = function (url) {
    var overlay = document.getElementById("drawer-overlay");
    if (!overlay || !url) return;
    overlay.innerHTML = '<p class="p-6 text-sm font-mono text-zinc-500">Loading…</p>';
    lifeosOpenDrawer();
    fetch(url, { headers: fetchHeaders(), credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(function (html) {
        overlay.innerHTML = html;
        if (window.htmx) htmx.process(overlay);
      })
      .catch(function (err) {
        overlay.innerHTML =
          '<p class="p-6 text-sm text-red-400 font-mono">Drawer failed: ' +
          err.message +
          "</p>";
      });
  };

  window.lifeosExpandInto = function (url, targetId) {
    var target = document.getElementById(targetId);
    if (!target || !url) return;
    target.innerHTML = '<p class="p-3 text-xs font-mono text-zinc-600">Loading…</p>';
    fetch(url, { headers: fetchHeaders(), credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(function (html) {
        target.innerHTML = html;
        if (window.htmx) htmx.process(target);
        if (window.matrixUpdateSelectionCount) matrixUpdateSelectionCount();
      })
      .catch(function (err) {
        target.innerHTML =
          '<p class="p-3 text-xs text-red-400 font-mono">Expand failed: ' +
          err.message +
          "</p>";
      });
  };

  window.matrixUpdateSelectionCount = function () {
    var n = document.querySelectorAll(
      "#matrix-canvas-inner input[name='item_ids']:checked, #overview-canvas-inner input[name='item_ids']:checked"
    ).length;
    var el = document.getElementById("matrix-selected-count");
    if (el) el.textContent = n + " selected";
  };

  document.addEventListener("click", function (e) {
    var drawerEl = e.target.closest("[data-lifeos-drawer]");
    if (drawerEl) {
      e.preventDefault();
      e.stopPropagation();
      lifeosOpenDrawerUrl(drawerEl.getAttribute("data-lifeos-drawer"));
      return;
    }
    var expandEl = e.target.closest("[data-lifeos-expand]");
    if (expandEl) {
      e.preventDefault();
      e.stopPropagation();
      lifeosExpandInto(
        expandEl.getAttribute("data-lifeos-expand"),
        expandEl.getAttribute("data-lifeos-expand-target")
      );
      return;
    }
    var backdrop = e.target.closest("#drawer-backdrop");
    if (backdrop) {
      lifeosCloseDrawer();
    }
  });

  document.addEventListener("change", function (e) {
    if (e.target && e.target.matches("input[name='item_ids']")) {
      var row = e.target.closest(".matrix-item-row");
      if (row) row.classList.toggle("is-selected", e.target.checked);
      matrixUpdateSelectionCount();
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.htmx === "undefined") {
      console.warn("LifeOS: HTMX did not load — inline edits may not work.");
    }
    document.body.addEventListener("htmx:configRequest", function (event) {
      var token = csrfToken();
      if (token) event.detail.headers["X-CSRFToken"] = token;
    });
    document.body.addEventListener("htmx:afterSwap", function (evt) {
      var target = evt.detail.target;
      if (target && target.id === "drawer-overlay") {
        lifeosOpenDrawer();
      }
      if (target && target.id === "matrix-canvas-inner") {
        matrixUpdateSelectionCount();
      }
      var trig = evt.detail.xhr && evt.detail.xhr.getResponseHeader("HX-Trigger");
      if (trig === "drawer-open") lifeosOpenDrawer();
      if (trig === "drawer-close") lifeosCloseDrawer();
      if (trig) {
        try {
          var obj = JSON.parse(trig);
          if (obj["palette-close"]) window.dispatchEvent(new CustomEvent("palette-close"));
          if (obj.refreshHome) {
            var focus = document.getElementById("active-focus-card");
            if (focus && window.htmx) htmx.trigger(focus, "refreshHome");
            if (window.htmx) htmx.trigger("body", "refreshHome");
          }
          if (obj.refreshStability && window.htmx) htmx.trigger("body", "refreshStability");
          if (obj["matrix-reload"] && window.htmx) htmx.trigger("body", "matrix-reload");
          if (obj["drawer-open"]) lifeosOpenDrawer();
          if (obj["drawer-close"]) lifeosCloseDrawer();
        } catch (ignore) {}
      }
    });
    document.body.addEventListener("htmx:responseError", function (evt) {
      if (evt.detail.target && evt.detail.target.id === "drawer-overlay") {
        var overlay = document.getElementById("drawer-overlay");
        if (overlay) {
          overlay.innerHTML =
            "<p class=\"p-6 text-sm text-red-400 font-mono\">Failed to load drawer (" +
            evt.detail.xhr.status +
            ").</p>";
          lifeosOpenDrawer();
        }
      }
    });
  });
})();
