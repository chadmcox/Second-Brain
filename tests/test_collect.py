"""Run with:  python -m unittest discover -s tests -v"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)

CONFIG = """
[site]
title = "Test"
url = "https://example.github.io/watch/"
ingest_days = 45
[summaries]
enabled = true
models = ["bad/model", "good/model"]
batch_size = 2
max_per_run = 10
[[topics]]
id = "copilot"
name = "Copilot"
any = ["copilot"]
[[topics]]
id = "cowork"
name = "Cowork"
any = ["cowork"]
none = ["coworking"]
[[topics]]
id = "autopilot"
name = "Autopilot"
any = ["autopilot"]
none = ["windows autopilot", "intune"]
scope = "microsoft"
[[topics]]
id = "entra"
name = "Entra"
any = ["entra"]
[[topics]]
id = "defender"
name = "Defender"
any = ["defender"]
[[sources]]
id = "sec"
name = "Security Blog"
group = "microsoft"
url = "https://feeds.test/wordpress.xml"
filter = "topics"
[[sources]]
id = "roadmap"
name = "Roadmap"
group = "microsoft"
kind = "roadmap"
url = "https://feeds.test/roadmap.xml"
filter = "topics"
[[sources]]
id = "ws"
name = "Workspace"
group = "competitor"
company = "Google"
url = "https://feeds.test/atom.xml"
filter = "keywords"
keywords = ["gemini", "ai"]
[[sources]]
id = "lab"
name = "Lab News"
group = "competitor"
company = "Lab"
type = "page"
url = "https://lab.test/news"
link_pattern = "^/news/[a-z0-9-]+/?$"
[[sources]]
id = "down"
name = "Broken Source"
group = "competitor"
company = "Nope"
url = "https://feeds.test/missing.xml"
"""

PAGES = {
    "https://feeds.test/wordpress.xml": "wordpress.xml",
    "https://feeds.test/roadmap.xml": "roadmap.xml",
    "https://feeds.test/atom.xml": "atom.xml",
    "https://lab.test/news": "listing.html",
    "https://lab.test/news/new-model": "article-new-model.html",
    "https://lab.test/news/older-post": "article-older-post.html",
}


class Base(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_fetch(url, timeout=25, tries=2):
            self.calls.append(url)
            if url not in PAGES:
                raise RuntimeError("HTTP 404 Not Found")
            return (FIX / PAGES[url]).read_text(encoding="utf-8")

        self._fetch, collect.fetch = collect.fetch, fake_fetch
        self._sleep, collect.time.sleep = collect.time.sleep, lambda s: None
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.toml"
        self.cfg.write_text(CONFIG, encoding="utf-8")
        self.out = self.dir / "docs"

    def tearDown(self):
        collect.fetch = self._fetch
        collect.time.sleep = self._sleep
        self.tmp.cleanup()

    def run_once(self, **kw):
        code = collect.run(self.cfg, self.out, now=kw.pop("now", NOW), **kw)
        path = self.out / "data" / "news.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return code, data


class CollectTests(Base):
    def test_end_to_end_without_ai(self):
        code, data = self.run_once(use_ai=False)
        self.assertEqual(code, 0)
        by_title = {i["title"]: i for i in data["items"]}

        cowork = by_title["Securing Copilot Cowork with Microsoft Defender – now generally available"]
        self.assertEqual(cowork["url"], "https://example.com/blog/2026/10/05/securing-cowork/?id=7")
        self.assertEqual(cowork["topics"], ["copilot", "cowork", "defender"])
        self.assertEqual(cowork["status"], "ga")
        self.assertEqual(cowork["excerpt"], "Runtime protection for agents is now generally available.")
        self.assertEqual(cowork["published"], "2026-10-05T16:00:00Z")

        # no product in the title or opening lines -> dropped by filter = "topics"
        self.assertNotIn("CISO perspectives on patching", by_title)
        # excluded term (Windows Autopilot / Intune) -> no autopilot tag -> dropped
        self.assertNotIn("Windows Autopilot device preparation update", by_title)
        # older than ingest_days -> never ingested
        self.assertNotIn("Old Entra post from last year", by_title)

        road = by_title["Microsoft Copilot (Microsoft 365): Cowork scheduled tasks"]
        self.assertEqual((road["kind"], road["status"]), ("roadmap", "rolling"))
        self.assertEqual(road["published"], "2026-10-06T22:56:31Z")
        self.assertNotIn("Microsoft Purview: archive mailbox API", by_title)

        gem = by_title["Gemini agents arrive in Docs"]
        self.assertEqual(gem["url"], "https://example.org/2026/10/gemini-agents.html")
        self.assertEqual(gem["published"], "2026-10-03T16:30:00Z")
        self.assertEqual((gem["company"], gem["status"]), ("Google", "preview"))
        self.assertEqual(gem["excerpt"], "Admins can turn on Gemini agents in preview.")
        self.assertNotIn("Calendar colour tweaks", by_title)

        lab = by_title["Introducing a new model"]
        self.assertEqual(lab["url"], "https://lab.test/news/new-model")
        self.assertEqual(lab["published"], "2026-10-06T19:00:00Z")
        self.assertIn("computer use & lower prices", lab["excerpt"])
        self.assertNotIn("Older post", by_title)  # dated 2025 on its own page

        self.assertEqual([i["published"] for i in data["items"]],
                         sorted((i["published"] for i in data["items"]), reverse=True))
        src = {s["id"]: s for s in data["sources"]}
        self.assertTrue(src["sec"]["ok"])
        self.assertFalse(src["down"]["ok"])
        self.assertIn("404", src["down"]["error"])
        self.assertEqual(src["lab"]["count"], 1)

        feed = (self.out / "feed.xml").read_text(encoding="utf-8")
        root = collect.ET.fromstring(feed)
        titles = [n.findtext("title") for n in root.iter("item")]
        self.assertIn("[Lab] Introducing a new model", titles)
        self.assertFalse(any("scheduled tasks" in t for t in titles))  # roadmap rows stay out

    def test_second_run_keeps_history_and_does_not_reopen_pages(self):
        self.run_once(use_ai=False)
        self.calls.clear()
        later = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
        code, data = self.run_once(use_ai=False, now=later)
        self.assertEqual(code, 0)
        self.assertNotIn("https://lab.test/news/new-model", self.calls)
        self.assertNotIn("https://lab.test/news/older-post", self.calls)
        lab = next(i for i in data["items"] if i["source"] == "lab")
        self.assertEqual(lab["first_seen"], "2026-10-07T01:00:00Z")
        self.assertEqual({s["id"]: s["new"] for s in data["sources"]}["sec"], 0)
        self.assertEqual(data["generated"], "2026-10-08T01:00:00Z")

    def test_all_sources_failing_keeps_existing_data(self):
        self.run_once(use_ai=False)
        before = (self.out / "data" / "news.json").read_text(encoding="utf-8")
        collect.fetch = lambda url, timeout=25, tries=2: (_ for _ in ()).throw(RuntimeError("down"))
        code = collect.run(self.cfg, self.out, use_ai=False, now=NOW)
        self.assertEqual(code, 1)
        self.assertEqual(before, (self.out / "data" / "news.json").read_text(encoding="utf-8"))


class SummaryTests(Base):
    def setUp(self):
        super().setUp()
        self._env = collect.os.environ.get("SUMMARY_API_KEY")
        collect.os.environ["SUMMARY_API_KEY"] = "test-key"
        self._endpoint, collect.SUMMARY_ENDPOINT = collect.SUMMARY_ENDPOINT, "https://llm.test/v1/chat/completions"
        self._call = collect.call_model

    def tearDown(self):
        collect.call_model = self._call
        collect.SUMMARY_ENDPOINT = self._endpoint
        if self._env is None:
            collect.os.environ.pop("SUMMARY_API_KEY", None)
        else:
            collect.os.environ["SUMMARY_API_KEY"] = self._env
        super().tearDown()

    def patch_model(self, fn):
        collect.summarise.__defaults__ = (fn,)

    def test_summaries_fall_back_to_next_model_and_are_validated(self):
        used = []

        def fake(model, token, payload, topic_ids):
            used.append(model)
            if model == "bad/model":
                raise collect.ModelUnavailable("HTTP 404")
            rows = []
            for p in payload:
                rows.append({
                    "id": p["id"],
                    "summary": "<b>Summary</b> of " + p["title"] + " with enough words to pass.",
                    "relevance": "urgent",                       # invalid -> medium
                    "competes_with": ["cowork", "made-up"],      # made-up is dropped
                })
            rows.append({"id": "not-requested", "summary": "x" * 50})
            return "Here you go:\n" + json.dumps({"items": rows})

        self.patch_model(fake)
        code, data = self.run_once()
        self.assertEqual(code, 0)
        self.assertEqual(used[0], "bad/model")
        self.assertTrue(all(m == "good/model" for m in used[1:]))
        posts = [i for i in data["items"] if i["kind"] != "roadmap"]
        self.assertTrue(posts and all(i["summary"].startswith("Summary of ") for i in posts))
        self.assertTrue(all(i["relevance"] == "medium" for i in posts))
        ms = next(i for i in posts if i["group"] == "microsoft")
        comp = next(i for i in posts if i["group"] == "competitor")
        self.assertEqual(ms["competes_with"], [])
        self.assertEqual(comp["competes_with"], ["cowork"])
        road = next(i for i in data["items"] if i["kind"] == "roadmap")
        self.assertEqual(road["summary"], "")
        self.assertIn("written with good/model", data["summaries"])

        # second run: nothing left to summarise, so the model is not called again
        used.clear()
        self.run_once(now=datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(used, [])

    def test_rate_limit_keeps_the_site_working(self):
        def fake(model, token, payload, topic_ids):
            raise collect.SummariesStopped("rate limit reached")

        self.patch_model(fake)
        code, data = self.run_once()
        self.assertEqual(code, 0)
        self.assertTrue(data["items"])
        self.assertTrue(all(i["summary"] == "" for i in data["items"]))
        self.assertIn("rate limit", data["summaries"])

    def test_no_endpoint_means_summaries_are_off(self):
        collect.SUMMARY_ENDPOINT = ""
        self.patch_model(lambda *a: self.fail("model must not be called"))
        code, data = self.run_once()
        self.assertEqual(code, 0)
        self.assertIn("off until", data["summaries"])

    def test_garbage_reply_is_ignored(self):
        self.patch_model(lambda *a: "I cannot help with that. <script>alert(1)</script>")
        code, data = self.run_once()
        self.assertEqual(code, 0)
        self.assertTrue(all(i["summary"] == "" for i in data["items"]))


class UnitTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(collect.iso(collect.parse_date("Tue, 06 Oct 2026 22:56:31 Z")), "2026-10-06T22:56:31Z")
        self.assertEqual(collect.iso(collect.parse_date("2026-10-06T19:00:00.000Z")), "2026-10-06T19:00:00Z")
        self.assertEqual(collect.iso(collect.parse_date("October 6, 2026")), "2026-10-06T00:00:00Z")
        self.assertIsNone(collect.parse_date("soon"))
        self.assertIsNone(collect.parse_date(""))

    def test_urls(self):
        self.assertEqual(collect.canonical_url("javascript:alert(1)"), "")
        self.assertEqual(collect.canonical_url("/a?utm_medium=x&b=1#f", "http://Example.com/x"),
                         "https://example.com/a?b=1")

    def test_status(self):
        s = collect.detect_status
        self.assertEqual(s("What's new in Agent 365", "Frontier AI models are everywhere", [], "post"), "")
        self.assertEqual(s("Opal (Frontier) is here", "", [], "post"), "frontier")
        self.assertEqual(s("Retiring the legacy connector", "now available", [], "post"), "retiring")
        self.assertEqual(s("Cowork GA", "", [], "post"), "ga")
        self.assertEqual(s("Meet the gateway", "", [], "post"), "")

    def test_models_table(self):
        cfg = {"models": {"per_lab": 5, "max_age_days": 365, "labs": [
            {"prefix": "openai", "name": "OpenAI"}, {"prefix": "anthropic", "name": "Anthropic"},
            {"prefix": "mistralai", "name": "Mistral"}]}}
        rows = collect.build_models(cfg, (FIX / "models.json").read_text(), NOW)
        self.assertEqual([r["name"] for r in rows], ["GPT-6.1 Sol", "Claude Sonnet 5.5"])
        sol = rows[0]
        self.assertEqual((sol["lab"], sol["input"], sol["output"]), ("OpenAI", 2.0, 10.0))
        self.assertEqual(sol["previous"]["name"], "GPT-5.6 Sol")
        self.assertEqual(sol["previous"]["change_pct"], -50)
        self.assertEqual(sol["about"], "Near-Astra intelligence for coding, computer use and professional work.")
        self.assertEqual(sol["url"], "https://openrouter.ai/openai/gpt-6.1-sol")
        self.assertIsNone(rows[1]["previous"])
        self.assertTrue(rows[1]["about"].startswith("Balanced model"))
        self.assertEqual(collect.model_family("OpenAI: GPT-6.1 Sol"), collect.model_family("GPT-5.6 Sol"))
        self.assertNotEqual(collect.model_family("Claude Sonnet 5.5"), collect.model_family("Claude Opus 5.5"))

    def test_scoped_theme_only_tags_its_group(self):
        cl = collect.Classifier([{"id": "ai-threats", "theme": True, "scope": "security", "any": ["ai agents"]}])
        self.assertEqual(cl.topics_for("AI agents used to hack banks", "", "security", []), ["ai-threats"])
        self.assertEqual(cl.topics_for("AI agents for everyone", "", "competitor", []), [])

    def test_strip_html(self):
        self.assertEqual(collect.strip_html("<p>a&amp;b</p><script>x()</script><p>c</p>"), "a&b c")


if __name__ == "__main__":
    unittest.main()
