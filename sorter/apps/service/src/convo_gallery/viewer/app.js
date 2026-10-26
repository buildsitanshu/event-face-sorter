// Dependency-free viewer. Hash routes: #/ (grid) and #/person/<id>.
(function () {
  "use strict";
  var app = document.getElementById("app");
  var state = { index: null, apiAvailable: false, error: null };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "class") n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }

  function skeleton() {
    var g = el("div", { "class": "grid", "aria-busy": "true" });
    for (var i = 0; i < 12; i++) g.appendChild(el("div", { "class": "sk" }));
    app.replaceChildren(g);
  }

  function fail(what, next) {
    app.replaceChildren(el("p", { "class": "err", role: "alert", text: what + " " + next }));
  }

  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }

  function renderGrid() {
    var people = state.index.people.slice().sort(function (a, b) { return b.media_count - a.media_count; });
    var photos = people.reduce(function (s, p) { return s + (p.photo_count || 0); }, 0);
    var head = el("div", {}, [
      el("h1", { text: "Sorted photos" }),
      el("p", { "class": "sub", text: people.length + " people, " + photos + " photos" })
    ]);
    if (!people.length) {
      app.replaceChildren(head, el("p", { "class": "empty", text: "No people found yet. Run the sorter first." }));
      return;
    }
    var search = el("input", { type: "search", id: "q", placeholder: "Search by name", "aria-label": "Search by name" });
    var grid = el("div", { "class": "grid" });
    function draw() {
      var q = search.value.trim().toLowerCase();
      grid.replaceChildren();
      people.forEach(function (p) {
        if (q && p.name.toLowerCase().indexOf(q) < 0) return;
        var img = el("img", { src: p.rep_crop || "", alt: p.name, loading: "lazy" });
        var nm = el("div", { "class": "nm" + (p.named ? "" : " muted"), text: p.name });
        grid.appendChild(el("a", { "class": "card", href: "#/person/" + p.cluster_id },
          [img, nm, el("div", { "class": "ct", text: plural(p.photo_count, "photo") })]));
      });
    }
    search.addEventListener("input", draw);
    draw();
    app.replaceChildren(head, el("div", { "class": "bar" }, [search]), grid);
  }

  function renderPerson(id) {
    skeleton();
    fetch("people/" + id + ".json").then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    }).then(function (d) {
      var entry = state.index.people.filter(function (p) { return String(p.cluster_id) === String(id); })[0];
      var title = el("h1", { text: d.name || (entry && entry.name) || ("person-" + id) });
      var back = el("a", { href: "#/", text: "All people" });
      var head = el("div", { "class": "head" }, [
        el("img", { src: d.rep_crop || "", alt: title.textContent }), title
      ]);
      var kids = [back, head];
      if (state.apiAvailable) {
        var input = el("input", { type: "text", value: title.textContent, "aria-label": "Name", maxlength: "80" });
        var save = el("button", { type: "button", text: "Save name" });
        var msg = el("span", { "aria-live": "polite" });
        save.addEventListener("click", function () {
          msg.className = ""; msg.textContent = "";
          fetch("/api/people/" + id + "/label", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ label: input.value })
          }).then(function (r) {
            if (!r.ok) throw new Error("status " + r.status);
            return r.json();
          }).then(function (j) {
            title.textContent = j.name; input.value = j.name;
            if (entry) { entry.name = j.name; entry.label = j.label; entry.named = !!j.label; }
            msg.className = "ok"; msg.textContent = "Saved";
          }).catch(function () {
            msg.className = "err"; msg.textContent = "Could not save the name. Check that the sorter is still running, then try again.";
          });
        });
        var zip = el("a", { "class": "btn", href: "/zip/" + id, text: "Download all" });
        kids.push(el("div", { "class": "bar" }, [input, save, zip, msg]));
      }
      var grid = el("div", { "class": "grid" });
      (d.photos || []).forEach(function (p) {
        var media;
        if (p.thumb) {
          media = el("img", { src: p.thumb, alt: p.name, loading: "lazy" });
          var f = p.face || [0.5, 0.5];
          media.style.objectPosition = (f[0] * 100) + "% " + (f[1] * 100) + "%";
        } else {
          media = el("div", { "class": "ph", text: p.name });
        }
        var tile = [media, el("div", { "class": "fn", text: p.name })];
        if (p.kind === "video") tile.push(el("span", { "class": "tag", text: "video" }));
        var attrs = { "class": "tile" };
        if (p.jpg_url || p.view_url) { attrs.href = p.jpg_url || p.view_url; attrs.target = "_blank"; attrs.rel = "noopener"; }
        grid.appendChild(el(attrs.href ? "a" : "div", attrs, tile));
      });
      kids.push(grid);
      app.replaceChildren.apply(app, kids);
    }).catch(function () {
      fail("Could not load this person.", "Go back to All people and try again, or re-run the export.");
    });
  }

  function route() {
    if (state.error) return;
    var m = /^#\/person\/(\d+)/.exec(location.hash);
    if (m) renderPerson(m[1]); else renderGrid();
  }

  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", function (e) {
    var t = e.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
    if (e.key === "Escape" && /^#\/person\//.test(location.hash)) { location.hash = "#/"; }
    else if (e.key === "/" && !typing) {
      var q = document.getElementById("q");
      if (q) { e.preventDefault(); q.focus(); }
    }
  });

  skeleton();
  var health = fetch("/health").then(function (r) { state.apiAvailable = r.status === 200; })
    .catch(function () { state.apiAvailable = false; });
  var index = fetch("index.json").then(function (r) {
    if (!r.ok) throw new Error("status " + r.status);
    return r.json();
  });
  Promise.all([index, health]).then(function (v) {
    state.index = v[0];
    route();
  }).catch(function () {
    state.error = true;
    fail("Could not load index.json.", "Run the sorter, then open this page through the gallery server.");
  });
})();
