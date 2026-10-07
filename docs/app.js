/* Copilot & Agent Watch: reads data/news.json and renders the page.
   No build step and no dependencies. All text from the data file is written
   with textContent, never as HTML. */
(function () {
  "use strict";

  var DAY = 86400000;
  var PAGE = 120;
  var KNOWN_LANES = ["copilot", "copilotstudio", "githubcopilot", "cowork", "autopilot", "agent365", "entra", "defender", "ai-threats", "incidents", "agent-registries", "security-agents"];
  var VIEWS = ["overview", "microsoft", "competitors", "security", "community", "models", "sources"];
  var FEEDS = { microsoft: "microsoft", competitors: "competitor", security: "security" };
  var DEFAULTS = { scope: "", theme: "", status: "", range: "30", q: "", key: "", roadmap: "" };

  var data = null;
  var topicName = {};
  var isTheme = {};
  var sourceById = {};
  var lastVisit = 0;
  var state = { view: "overview", limit: PAGE };
  Object.keys(DEFAULTS).forEach(function (k) { state[k] = DEFAULTS[k]; });

  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------- helpers
  function el(tag, props, children) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") node.textContent = v;
        else if (k === "class") node.className = v;
        else if (k === "on") Object.keys(v).forEach(function (e) { node.addEventListener(e, v[e]); });
        else node.setAttribute(k, v === true ? "" : v);
      });
    }
    (children || []).forEach(function (c) {
      if (c) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function safeUrl(url) {
    try {
      var u = new URL(url, location.href);
      return u.protocol === "https:" || u.protocol === "http:" ? u.href : "";
    } catch (e) { return ""; }
  }

  function setLane(node, id) {
    if (!id) return node;
    node.dataset.lane = id;
    if (KNOWN_LANES.indexOf(id) < 0) {
      // A product added in config.toml gets a stable colour from its id.
      var h = 0;
      for (var i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
      node.style.setProperty("--lane", "hsl(" + h + " 50% 46%)");
    }
    return node;
  }

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* private mode: carry on without it */ }
    return null;
  }

  function dayKey(d) { return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }
  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

  var fmtDay = new Intl.DateTimeFormat(undefined, { weekday: "long" });
  var fmtDate = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long" });
  var fmtShort = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
  var fmtFull = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });

  function ago(ms) {
    var mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
    if (mins < 2) return "just now";
    if (mins < 90) return mins + " minutes ago";
    var hours = Math.round(mins / 60);
    if (hours < 36) return hours + " hours ago";
    return Math.round(hours / 24) + " days ago";
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function laneOf(item) {
    if (item.group !== "microsoft") return "";
    return item.topics.filter(function (t) { return !isTheme[t]; })[0] || "";
  }
  function isFresh(item) { return lastVisit && Date.parse(item.first_seen) > lastVisit; }

  // -------------------------------------------------------------- routing
  function readHash() {
    var raw = location.hash.replace(/^#/, "");
    var parts = raw.split("?");
    state.view = VIEWS.indexOf(parts[0]) >= 0 ? parts[0] : "overview";
    var params = new URLSearchParams(parts[1] || "");
    Object.keys(DEFAULTS).forEach(function (k) { state[k] = params.get(k) || DEFAULTS[k]; });
    state.limit = PAGE;
  }

  function writeHash(replace) {
    var params = new URLSearchParams();
    if (FEEDS[state.view] || state.view === "community") {
      Object.keys(DEFAULTS).forEach(function (k) {
        if (state[k] && state[k] !== DEFAULTS[k]) params.set(k, state[k]);
      });
    }
    var q = params.toString();
    var hash = "#" + state.view + (q ? "?" + q : "");
    if (hash === location.hash) return;
    if (replace) history.replaceState(null, "", hash);
    else location.hash = hash;
  }

  function go(view, changes) {
    Object.keys(DEFAULTS).forEach(function (k) { state[k] = DEFAULTS[k]; });
    Object.assign(state, changes || {}, { view: view, limit: PAGE });
    writeHash(false);
    render();
    window.scrollTo(0, 0);
    $("main").focus({ preventScroll: true });
  }

  // ---------------------------------------------------------------- posts
  function postNode(item, opts) {
    opts = opts || {};
    var src = sourceById[item.source] || {};
    var url = safeUrl(item.url);
    var title = url
      ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: item.title })
      : document.createTextNode(item.title);
    var meta = el("p", { class: "post-meta" });
    if (isFresh(item)) meta.appendChild(el("span", { class: "fresh", text: "New" }));
    if (opts.showDate) meta.appendChild(el("span", { text: fmtShort.format(new Date(item.published)) }));
    meta.appendChild(el("span", { text: src.name || item.company || item.source }));
    if (item.status && data.statuses[item.status]) {
      meta.appendChild(el("span", { class: "state", "data-s": item.status, text: data.statuses[item.status] }));
    }
    if (item.kind === "roadmap") meta.appendChild(el("span", { class: "state", text: "Roadmap entry" }));
    if (item.relevance === "high") meta.appendChild(el("span", { class: "key", text: "Key item" }));
    item.topics.forEach(function (t) {
      // Product tags belong to Microsoft posts; theme tags show for every company.
      if (item.group === "competitor" && !isTheme[t]) return;
      meta.appendChild(setLane(el("span", { class: "tag", text: topicName[t] || t }), t));
    });

    var node = setLane(el("article", { class: "post" }, [el("h3", null, [title]), meta]), laneOf(item));
    var body = item.summary || item.excerpt;
    if (body) {
      var p = el("p", { class: "post-text", text: body + " " });
      if (item.summary) p.appendChild(el("span", { class: "by", text: "AI summary" }));
      node.appendChild(p);
    }
    var vs = (item.competes_with || []).map(function (t) { return topicName[t]; }).filter(Boolean);
    if (item.group !== "microsoft" && vs.length) {
      node.appendChild(el("p", { class: "post-vs" }, ["Competes with ", el("b", { text: vs.join(", ") })]));
    }
    return node;
  }

  // ------------------------------------------------------------- overview
  function renderOverview() {
    var today = startOfDay(new Date());
    var first = new Date(today.getTime() - 27 * DAY);
    var days = [];
    for (var i = 0; i < 28; i++) days.push(new Date(first.getFullYear(), first.getMonth(), first.getDate() + i));
    var index = {};
    days.forEach(function (d, i) { index[dayKey(d)] = i; });

    var posts = data.items.filter(function (i) { return i.kind !== "roadmap"; });
    function row(match) {
      var counts = new Array(28).fill(0);
      posts.forEach(function (item) {
        var slot = index[dayKey(new Date(item.published))];
        if (slot !== undefined && match(item)) counts[slot]++;
      });
      return counts;
    }

    function lane(label, counts, lane, onPick) {
      var total = counts.reduce(function (a, b) { return a + b; }, 0);
      var strip = el("div", { class: "strip", "aria-hidden": "true" });
      counts.forEach(function (n, i) {
        var level = n === 0 ? 0 : n === 1 ? 38 : n === 2 ? 62 : n === 3 ? 82 : 100;
        var cell = el("span", {
          class: "cell" + (i && i % 7 === 0 ? " week-start" : ""),
          "data-n": String(Math.min(n, 4)),
          title: plural(n, "post") + " on " + fmtShort.format(days[i])
        });
        cell.style.setProperty("--level", level);
        strip.appendChild(cell);
      });
      var button = el("button", {
        class: "lane-name", type: "button",
        "aria-label": label + ": " + plural(total, "post") + " in the last four weeks. Show them.",
        on: { click: onPick }
      }, [el("b", { text: label }), el("span", { text: String(total) })]);
      return setLane(el("div", { class: "lane" }, [button, strip]), lane);
    }

    var box = clear($("lanes"));
    data.products.forEach(function (t) {
      box.appendChild(lane(t.name, row(function (i) {
        return i.group === "microsoft" && i.topics.indexOf(t.id) >= 0;
      }), t.id, function () { go("microsoft", { scope: t.id }); }));
    });
    function themeLanes(title, group, view) {
      var themes = themesFor(view);
      if (!themes.length) return;
      box.appendChild(el("p", { class: "lane-group", text: title }));
      themes.forEach(function (t) {
        box.appendChild(lane(t.name, row(function (i) {
          return i.group === group && i.topics.indexOf(t.id) >= 0;
        }), t.id, function () { go(view, { theme: t.id }); }));
      });
    }
    themeLanes("Threat intel", "security", "security");
    themeLanes("Themes across competitors", "competitor", "competitors");
    var companies = companyList("competitor");
    if (companies.length) {
      box.appendChild(el("p", { class: "lane-group", text: "Competitors" }));
      companies.forEach(function (c) {
        box.appendChild(lane(c, row(function (i) {
          return i.group === "competitor" && i.company === c;
        }), "", function () { go("competitors", { scope: c }); }));
      });
    }
    var axis = el("div", { class: "strip" });
    for (var w = 0; w < 4; w++) axis.appendChild(el("span", { text: fmtShort.format(days[w * 7]) }));
    box.appendChild(el("div", { class: "lane-axis", "aria-hidden": "true" }, [el("span"), axis]));

    // Picks: this week's key items, or simply the newest posts without AI ratings.
    var weekAgo = Date.now() - 7 * DAY;
    // Threat intel has its own tab; it would otherwise crowd out everything here.
    var briefing = posts.filter(function (i) { return i.group !== "security"; });
    var week = briefing.filter(function (i) { return Date.parse(i.published) >= weekAgo; });
    var rated = week.some(function (i) { return i.relevance; });
    var picks = rated
      ? week.filter(function (i) { return i.relevance === "high"; })
      : [];
    if (picks.length < 3) { picks = (week.length ? week : briefing); rated = false; }
    $("picks-title").textContent = rated ? "Worth reading this week" : "Latest posts";
    var list = clear($("picks"));
    picks.slice(0, 8).forEach(function (i) { list.appendChild(postNode(i, { showDate: true })); });
    if (!picks.length) list.appendChild(el("p", { class: "empty", text: "Nothing has been collected yet." }));

    var latest = clear($("latest"));
    data.products.forEach(function (t) {
      var item = posts.find(function (i) { return i.group === "microsoft" && i.topics.indexOf(t.id) >= 0; });
      var li = setLane(el("li"), t.id);
      li.appendChild(el("span", {
        class: "who",
        text: t.name + (item ? ", " + fmtShort.format(new Date(item.published)) : "")
      }));
      var url = item && safeUrl(item.url);
      li.appendChild(url
        ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: item.title })
        : el("span", { class: "none", text: "No posts in the collected period" }));
      latest.appendChild(li);
    });
  }

  function companyList(group) {
    var seen = [];
    data.sources.forEach(function (s) {
      if (s.group === group && s.company && seen.indexOf(s.company) < 0) seen.push(s.company);
    });
    return seen;
  }

  // Themes scoped to threat intel show on that tab only; the rest show elsewhere.
  function themesFor(view) {
    return data.themes.filter(function (t) {
      return t.scope === "all" || (t.scope === "security") === (view === "security");
    });
  }

  // ----------------------------------------------------------------- feed
  function inRange(item) {
    var days = parseInt(state.range, 10);
    return !days || Date.parse(item.published) >= Date.now() - days * DAY;
  }

  function matches(item, skip) {
    var ms = state.view === "microsoft";
    if (item.group !== FEEDS[state.view]) return false;
    if (item.kind === "roadmap" && !(ms && state.roadmap)) return false;
    if (!inRange(item)) return false;
    if (skip !== "scope" && state.scope) {
      if (ms ? item.topics.indexOf(state.scope) < 0 : item.company !== state.scope) return false;
    }
    if (skip !== "theme" && state.theme && item.topics.indexOf(state.theme) < 0) return false;
    if (skip !== "status" && state.status && item.status !== state.status) return false;
    if (state.key && item.relevance !== "high") return false;
    if (state.q) {
      var hay = [item.title, item.summary, item.excerpt, (sourceById[item.source] || {}).name, item.company]
        .join(" ").toLowerCase();
      var words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function chip(label, count, pressed, lane, onClick) {
    var node = el("button", { class: "chip", type: "button", "aria-pressed": pressed ? "true" : "false", on: { click: onClick } },
      [label, count === null ? null : el("small", { text: String(count) })]);
    return setLane(node, lane);
  }

  function renderFeed() {
    var ms = state.view === "microsoft";
    $("lbl-scope").textContent = ms ? "Product" : state.view === "security" ? "Source" : "Company";
    $("roadmap-wrap").hidden = !ms || !data.items.some(function (i) { return i.kind === "roadmap"; });
    $("f-range").value = state.range;
    if (document.activeElement !== $("f-q")) $("f-q").value = state.q;
    $("f-key").checked = !!state.key;
    $("f-roadmap").checked = !!state.roadmap;

    function set(key, value) {
      state[key] = value; state.limit = PAGE; writeHash(true); renderFeed();
    }

    // Chip counts respect every other filter, so a count is what you get on click.
    var forScope = data.items.filter(function (i) { return matches(i, "scope"); });
    var scopes = ms
      ? data.products.map(function (t) { return { id: t.id, name: t.name, lane: t.id }; })
      : companyList(FEEDS[state.view]).map(function (c) { return { id: c, name: c, lane: "" }; });
    var scopeBox = clear($("chips-scope"));
    scopeBox.appendChild(chip("All", forScope.length, !state.scope, "", function () { set("scope", ""); }));
    scopes.forEach(function (s) {
      var n = forScope.filter(function (i) { return ms ? i.topics.indexOf(s.id) >= 0 : i.company === s.id; }).length;
      scopeBox.appendChild(chip(s.name, n, state.scope === s.id, s.lane, function () {
        set("scope", state.scope === s.id ? "" : s.id);
      }));
    });

    var forTheme = data.items.filter(function (i) { return matches(i, "theme"); });
    var themeBox = clear($("chips-theme"));
    var themes = themesFor(state.view);
    $("row-theme").hidden = !themes.length;
    themeBox.appendChild(chip("Any", null, !state.theme, "", function () { set("theme", ""); }));
    themes.forEach(function (t) {
      var n = forTheme.filter(function (i) { return i.topics.indexOf(t.id) >= 0; }).length;
      themeBox.appendChild(chip(t.name, n, state.theme === t.id, t.id, function () {
        set("theme", state.theme === t.id ? "" : t.id);
      }));
    });

    var forStatus = data.items.filter(function (i) { return matches(i, "status"); });
    var statusBox = clear($("chips-status"));
    statusBox.appendChild(chip("Any", null, !state.status, "", function () { set("status", ""); }));
    Object.keys(data.statuses).forEach(function (s) {
      if (!s) return;
      var n = forStatus.filter(function (i) { return i.status === s; }).length;
      if (!n && state.status !== s) return;
      statusBox.appendChild(chip(data.statuses[s], n, state.status === s, "", function () {
        set("status", state.status === s ? "" : s);
      }));
    });

    var found = data.items.filter(function (i) { return matches(i); });
    var shown = found.slice(0, state.limit);
    $("result-count").textContent = found.length
      ? plural(found.length, "post") + (shown.length < found.length ? ", showing the newest " + shown.length : "")
      : "";

    var box = clear($("timeline"));
    if (!found.length) {
      box.appendChild(el("p", { class: "empty", text: data.items.length
        ? "No posts match these filters. Widen the period or clear a filter to see more."
        : "Nothing has been collected yet." }));
    }
    var todayKey = dayKey(new Date());
    var yesterdayKey = dayKey(new Date(Date.now() - DAY));
    var thisYear = new Date().getFullYear();
    var current = null, group = null;
    shown.forEach(function (item) {
      var d = new Date(item.published);
      var key = dayKey(d);
      if (key !== current) {
        current = key;
        var note = key === todayKey ? "Today" : key === yesterdayKey ? "Yesterday" : fmtDay.format(d);
        if (d.getFullYear() !== thisYear) note += " " + d.getFullYear();
        group = el("div", { class: "posts" });
        box.appendChild(el("section", { class: "day" }, [
          el("h2", { class: "day-date" }, [fmtDate.format(d), el("small", { text: note })]),
          group
        ]));
      }
      group.appendChild(postNode(item));
    });
    $("more").hidden = shown.length >= found.length;
  }

  // --------------------------------------------------------------- models
  function money(n) {
    if (typeof n !== "number") return "";
    return "$" + (n >= 100 ? n.toFixed(0) : n >= 1 ? n.toFixed(2) : n.toFixed(n < 0.1 ? 3 : 2));
  }

  function changeText(prev) {
    if (!prev) return "No earlier release to compare";
    var c = prev.change_pct;
    if (typeof c !== "number") return "Follows " + prev.name;
    if (c === 0) return "Same price as " + prev.name;
    return Math.abs(c) + "% " + (c < 0 ? "cheaper" : "more expensive") + " than " + prev.name;
  }

  function renderModels() {
    var m = data.models || { rows: [] };
    var body = clear($("models-body"));
    var note = "";
    if (m.checked) note = "Prices checked " + fmtFull.format(new Date(m.checked)) + ".";
    if (m.error) note += " The latest check failed (" + m.error + "), so this is the last good copy.";
    $("models-note").textContent = note;
    $("models-empty").hidden = m.rows.length > 0;
    $("models-wrap").hidden = !m.rows.length;
    var top = m.rows.reduce(function (a, r) { return Math.max(a, r.output || 0); }, 0);
    var lab = null;
    m.rows.forEach(function (r) {
      if (r.lab !== lab) {
        lab = r.lab;
        body.appendChild(el("tr", { class: "lab-row" }, [el("th", { colspan: "6", scope: "colgroup", text: lab })]));
      }
      var url = safeUrl(r.url);
      var out = el("td", { class: "num" }, [money(r.output)]);
      var bar = el("span", { class: "bar", "aria-hidden": "true" });
      bar.style.width = (top ? Math.max(2, Math.round(r.output / top * 100)) : 0) + "%";
      out.appendChild(bar);
      var change = el("td", { text: changeText(r.previous) });
      if (r.previous && typeof r.previous.change_pct === "number" && r.previous.change_pct !== 0) {
        change.appendChild(el("small", { text: "was " + money(r.previous.input) + " in, " + money(r.previous.output) + " out" }));
      }
      body.appendChild(el("tr", null, [
        el("th", { scope: "row" }, [
          url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: r.name }) : r.name,
          r.context ? el("small", { text: Math.round(r.context / 1000).toLocaleString() + "K token context" }) : null
        ]),
        el("td", null, [
          fmtShort.format(new Date(r.released)) + " " + new Date(r.released).getFullYear(),
          r.date_is === "price" ? el("small", { text: "price effective" }) : null
        ]),
        el("td", { class: "num", text: money(r.input) }),
        out,
        change,
        el("td", { class: "about", text: r.about ||
          (r.date_is === "price" ? "Azure's price list gives no description for this model." : "") })
      ]));
    });
  }

  // ------------------------------------------------------------ community
  function renderCommunity() {
    var c = data.community || { rows: [] };
    var labels = [];
    c.rows.forEach(function (r) {
      (r.labels || []).forEach(function (l) { if (labels.indexOf(l) < 0) labels.push(l); });
    });
    var chips = clear($("chips-community"));
    function pick(value) { state.scope = value; writeHash(true); renderCommunity(); }
    chips.appendChild(chip("All", c.rows.length, !state.scope, "", function () { pick(""); }));
    labels.forEach(function (l) {
      var n = c.rows.filter(function (r) { return (r.labels || []).indexOf(l) >= 0; }).length;
      chips.appendChild(chip(l, n, state.scope === l, "", function () { pick(state.scope === l ? "" : l); }));
    });
    var note = c.checked ? "Checked " + fmtFull.format(new Date(c.checked)) + "." : "";
    if (c.error) note += " Some searches failed: " + c.error + ".";
    $("community-note").textContent = note;

    var started = Date.parse(c.started || "") || 0;
    var list = clear($("community-list"));
    var rows = c.rows.filter(function (r) { return !state.scope || (r.labels || []).indexOf(state.scope) >= 0; });
    if (!rows.length) {
      list.appendChild(el("p", { class: "empty", text: c.rows.length
        ? "No projects carry this label right now."
        : "No projects have been collected yet. They appear after the next run." }));
    }
    rows.forEach(function (r) {
      var url = safeUrl(r.url);
      var meta = el("p", { class: "post-meta" });
      var seen = Date.parse(r.first_seen || "") || 0;
      // "New" means it joined the list after the first collection, within the last week.
      if (seen > started + DAY / 2 && Date.now() - seen < 7 * DAY) meta.appendChild(el("span", { class: "fresh", text: "New" }));
      if (r.pinned) meta.appendChild(el("span", { class: "key", text: "Pinned" }));
      meta.appendChild(el("span", { text: plural(r.stars, "star").replace(/^\d+/, r.stars.toLocaleString()) }));
      if (typeof r.gain === "number" && r.gain > 0) meta.appendChild(el("span", { class: "key", text: "+" + r.gain.toLocaleString() + " this week" }));
      if (r.pushed) meta.appendChild(el("span", { text: "Updated " + fmtShort.format(new Date(r.pushed)) }));
      if (r.language) meta.appendChild(el("span", { text: r.language }));
      (r.labels || []).forEach(function (l) { meta.appendChild(el("span", { class: "tag", text: l })); });
      var node = el("article", { class: "post" }, [
        el("h3", null, [url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: r.full_name }) : r.full_name]),
        meta
      ]);
      if (r.description) node.appendChild(el("p", { class: "post-text", text: r.description }));
      list.appendChild(node);
    });
  }

  // -------------------------------------------------------------- sources
  function renderSources() {
    var body = clear($("sources-body"));
    data.sources.forEach(function (s) {
      var url = safeUrl(s.home);
      var name = el("td", null, [
        url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: s.name }) : s.name,
        el("span", { class: "who", text: s.group === "microsoft" ? "Microsoft" : (s.company || "Competitor") })
      ]);
      var last = el("td");
      if (s.ok) {
        last.textContent = s.last_ok ? fmtFull.format(new Date(s.last_ok)) : "";
      } else {
        last.appendChild(el("span", { class: "bad", text: "Failed on the last run" }));
        last.appendChild(el("small", { text: (s.error || "No details") +
          (s.last_ok ? ". Last worked " + fmtFull.format(new Date(s.last_ok)) + "." : ". It has not worked yet.") }));
      }
      body.appendChild(el("tr", null, [
        name,
        el("td", { text: s.type === "page" ? "News page (no feed)" : "RSS feed" }),
        el("td", { text: String(s.count || 0) }),
        last
      ]));
    });
    $("summary-state").textContent = data.summaries ? "AI summaries on the last run: " + data.summaries + "." : "";
  }

  // --------------------------------------------------------------- render
  function render() {
    document.querySelectorAll(".tabs a").forEach(function (a) {
      if (a.dataset.view === state.view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    var feed = !!FEEDS[state.view];
    $("view-overview").hidden = state.view !== "overview";
    $("view-feed").hidden = !feed;
    $("view-models").hidden = state.view !== "models";
    $("view-community").hidden = state.view !== "community";
    $("view-sources").hidden = state.view !== "sources";
    if (!data) return;
    if (!data.generated) {
      // Nothing collected yet: the message below explains how to start.
      ["view-overview", "view-feed", "view-models", "view-community", "view-sources"].forEach(function (id) { $(id).hidden = true; });
      return;
    }
    if (state.view === "overview") renderOverview();
    else if (feed) renderFeed();
    else if (state.view === "models") renderModels();
    else if (state.view === "community") renderCommunity();
    else renderSources();
    var label = { overview: "Overview", microsoft: "Microsoft", competitors: "Competitors",
      security: "Threat intel", community: "Community", models: "Models", sources: "Sources" }[state.view];
    document.title = label + " | " + data.site.title;
  }

  function showMessage(title, lines) {
    var box = clear($("message"));
    box.appendChild(el("h2", { text: title }));
    lines.forEach(function (l) { box.appendChild(el("p", { text: l })); });
    box.hidden = false;
  }

  function renderStatus() {
    var line = clear($("site-status"));
    var checked = Date.parse(data.generated);
    var failing = data.sources.filter(function (s) { return !s.ok; }).length;
    var text = "Checked " + ago(checked) + " across " + plural(data.sources.length, "source") + ".";
    if (Date.now() - checked > 36 * 3600000) {
      text = "Last checked " + ago(checked) + ". The scheduled run may have stopped; look at the Actions tab of the repository.";
    } else if (failing) {
      text += " " + plural(failing, "source") + " could not be read; see Sources.";
    }
    line.appendChild(document.createTextNode(text + " "));
    var fresh = data.items.filter(isFresh).length;
    if (fresh) line.appendChild(el("strong", { text: plural(fresh, "post") + " new since your last visit." }));
  }

  // ----------------------------------------------------------------- init
  function effectiveTheme() {
    return document.documentElement.dataset.theme ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function labelTheme() {
    $("theme-toggle").textContent = effectiveTheme() === "dark" ? "Light theme" : "Dark theme";
  }

  function init() {
    labelTheme();
    $("theme-toggle").addEventListener("click", function () {
      var next = effectiveTheme() === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      store("watch-theme", next);
      labelTheme();
    });
    $("filters").addEventListener("submit", function (e) { e.preventDefault(); });
    function bind(id, key, read) {
      $(id).addEventListener(id === "f-q" ? "input" : "change", function (e) {
        state[key] = read(e.target); state.limit = PAGE; writeHash(true); renderFeed();
      });
    }
    bind("f-range", "range", function (t) { return t.value; });
    bind("f-q", "q", function (t) { return t.value.trim(); });
    bind("f-key", "key", function (t) { return t.checked ? "1" : ""; });
    bind("f-roadmap", "roadmap", function (t) { return t.checked ? "1" : ""; });
    $("more").addEventListener("click", function () { state.limit += PAGE; renderFeed(); });
    window.addEventListener("hashchange", function () { readHash(); render(); });

    readHash();
    render();

    fetch("data/news.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (json) {
        if (!json || !Array.isArray(json.items) || !Array.isArray(json.sources)) throw new Error("unexpected file contents");
        data = json;
        data.topics = data.topics || [];
        data.statuses = data.statuses || {};
        data.site = data.site || { title: "Copilot & Agent Watch" };
        data.items.forEach(function (i) { i.topics = i.topics || []; });
        data.topics.forEach(function (t) { topicName[t.id] = t.name; });
        data.products = data.topics.filter(function (t) { return !t.theme; });
        data.themes = data.topics.filter(function (t) { return t.theme; });
        data.themes.forEach(function (t) { isTheme[t.id] = true; });
        data.sources.forEach(function (s) { sourceById[s.id] = s; });
        $("site-title").textContent = data.site.title;

        lastVisit = parseInt(store("watch-last-visit") || "0", 10) || 0;
        // Count this visit once the reader has had time to see what was new.
        setTimeout(function () { store("watch-last-visit", String(Date.now())); }, 8000);

        if (!data.generated) {
          $("site-status").textContent = "Waiting for the first collection run.";
          showMessage("No posts yet", [
            "The page fills in after the first collection run, which starts when the files are pushed to GitHub.",
            "To start one by hand, open the Actions tab of the repository, choose “Update news”, then “Run workflow”. It takes about a minute."
          ]);
        } else {
          renderStatus();
        }
        render();
      })
      .catch(function (err) {
        $("site-status").textContent = "The posts could not be loaded.";
        showMessage("Could not read data/news.json", [
          "Reason: " + err.message + ".",
          "If you opened index.html straight from disk, serve the folder instead: run “python -m http.server” inside docs and open http://localhost:8000."
        ]);
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
