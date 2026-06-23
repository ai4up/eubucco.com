/* Known Issues — live-fetched from GitHub, grouped by version label.
   Pulls the union of "bug" and "known-issues" issues and classifies each:
     - has "known-issues" label  -> upstream limitation (source data; we can't easily fix)
     - otherwise (just "bug")    -> dataset bug (our side; to be fixed)
   Renders into <div id="known-issues">. No build step; runs on page load. */
(function () {
  "use strict";

  var REPO = "ai4up/eubucco";
  var LABELS = ["bug", "known-issues"];
  var ISSUES_URL = "https://github.com/" + REPO + "/issues?q=is%3Aissue+is%3Aopen+label%3Abug%2Cknown-issues";

  function api(label) {
    return "https://api.github.com/repos/" + REPO +
      "/issues?state=open&labels=" + encodeURIComponent(label) + "&per_page=100";
  }

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function esc(s) {
    return (s || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function hasLabel(issue, name) {
    return (issue.labels || []).some(function (l) { return l.name === name; });
  }

  // Plain-text teaser from the issue body (the card clamps it to 2 lines via CSS).
  function excerpt(body) {
    if (!body) return "";
    var t = body
      .replace(/<img[^>]*>/gi, "")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/<\/?[^>]+>/g, "")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/[*_`>]/g, "")
      .replace(/\r/g, "")
      .replace(/\n{2,}/g, "\n")
      .split("\n").map(function (l) { return l.trim(); }).filter(Boolean).join(" ").trim();
    if (t.length > 260) t = t.slice(0, 260).replace(/\s+\S*$/, "");
    return t;
  }

  var VERSION_RE = /^v\d+(\.\d+)*$/i;

  function versionOf(labels) {
    for (var i = 0; i < labels.length; i++) {
      if (VERSION_RE.test(labels[i].name)) return labels[i].name.toLowerCase();
    }
    return null;
  }

  // Newest version first; "General" bucket always last.
  function compareVersions(a, b) {
    if (a === b) return 0;
    if (a === "general") return 1;
    if (b === "general") return -1;
    var pa = a.replace(/^v/, "").split(".").map(Number);
    var pb = b.replace(/^v/, "").split(".").map(Number);
    for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
      var da = pa[i] || 0, db = pb[i] || 0;
      if (da !== db) return db - da;
    }
    return 0;
  }

  function fmtDate(iso) {
    try {
      return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short" });
    } catch (e) { return ""; }
  }

  function renderIssue(issue) {
    var upstream = hasLabel(issue, "known-issues");
    var card = el("article", "ki-card" + (upstream ? " ki-card--upstream" : ""));

    var head = el("div", "ki-card__head");
    var badge = el("span", "ki-badge " + (upstream ? "ki-badge--upstream" : "ki-badge--bug"),
      upstream ? "Upstream" : "Bug");
    head.appendChild(badge);
    var title = el("a", "ki-card__title");
    title.href = issue.html_url;
    title.target = "_blank";
    title.rel = "noopener";
    title.textContent = issue.title;
    head.appendChild(title);
    card.appendChild(head);

    var ex = excerpt(issue.body);
    if (ex) card.appendChild(el("p", "ki-card__body", esc(ex)));

    var meta = el("div", "ki-card__meta");
    meta.appendChild(el("a", "ki-num", "#" + issue.number)).href = issue.html_url;
    meta.lastChild.target = "_blank";
    meta.lastChild.rel = "noopener";
    meta.appendChild(el("span", "ki-date", fmtDate(issue.created_at)));
    card.appendChild(meta);

    return card;
  }

  function renderLegend() {
    var wrap = el("div", "ki-legendbox");
    [
      ["ki-badge--bug", "Dataset bug",
        "A problem introduced on our side that we plan to fix in a future release."],
      ["ki-badge--upstream", "Upstream limitation",
        "Originates in a source dataset we ingest. We flag these for transparency, but they often can’t be resolved by EUBUCCO directly."],
    ].forEach(function (row) {
      var line = el("div", "ki-legend");
      line.appendChild(el("span", "ki-badge " + row[0], row[1]));
      line.appendChild(el("span", "ki-legend__text", row[2]));
      wrap.appendChild(line);
    });
    return wrap;
  }

  function render(issues, root) {
    root.innerHTML = "";

    if (!issues.length) {
      root.appendChild(el("p", "ki-note",
        "🎉 No known issues are currently open. " +
        '<a href="' + ISSUES_URL + '" target="_blank" rel="noopener">Browse all issues on GitHub</a>.'));
      return;
    }

    root.appendChild(renderLegend());

    var groups = {};
    issues.forEach(function (it) {
      var v = versionOf(it.labels || []) || "general";
      (groups[v] = groups[v] || []).push(it);
    });

    Object.keys(groups).sort(compareVersions).forEach(function (v) {
      var label = v === "general" ? "General" : v.toUpperCase();
      var sec = el("section", "ki-group");
      var h = el("h2", "ki-group__title");
      h.appendChild(el("span", null, esc(label)));
      h.appendChild(el("span", "ki-count", String(groups[v].length)));
      sec.appendChild(h);

      // Bugs first, then upstream limitations; newest issue first within each.
      groups[v]
        .sort(function (a, b) {
          var ua = hasLabel(a, "known-issues") ? 1 : 0;
          var ub = hasLabel(b, "known-issues") ? 1 : 0;
          return ua - ub || b.number - a.number;
        })
        .forEach(function (it) { sec.appendChild(renderIssue(it)); });
      root.appendChild(sec);
    });

    root.appendChild(el("p", "ki-note",
      'Spotted something not listed here? <a href="https://github.com/' + REPO +
      '/issues/new" target="_blank" rel="noopener">Open an issue</a> or email nachtigall(at)tu-berlin.de.'));
  }

  function init() {
    var root = document.getElementById("ki-root");
    if (!root) return;
    root.innerHTML = '<p class="ki-note">Loading known issues from GitHub…</p>';

    Promise.all(LABELS.map(function (lab) {
      return fetch(api(lab), { headers: { Accept: "application/vnd.github+json" } })
        .then(function (r) {
          if (!r.ok) throw new Error("GitHub API returned " + r.status);
          return r.json();
        });
    }))
      .then(function (lists) {
        // Merge the two label queries, de-dupe by number, drop PRs.
        var seen = {}, merged = [];
        lists.forEach(function (list) {
          list.forEach(function (it) {
            if (it.pull_request || seen[it.number]) return;
            seen[it.number] = true;
            merged.push(it);
          });
        });
        render(merged, root);
      })
      .catch(function (err) {
        root.innerHTML = "";
        root.appendChild(el("p", "ki-error",
          "Couldn’t load issues from GitHub (" + esc(err.message) + "). " +
          'View them directly on <a href="' + ISSUES_URL + '" target="_blank" rel="noopener">GitHub</a>.'));
      });
  }

  // Run now, and again on Material's instant-navigation page swaps.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
