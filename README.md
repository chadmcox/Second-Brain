# Copilot & Agent Watch

A small news site that lives in a GitHub repository. Several times a day a GitHub Action
reads official Microsoft blogs and competitor news pages, keeps the posts about the products
you track, optionally writes a short AI summary of each, and publishes the result with GitHub
Pages.

It tracks Microsoft 365 Copilot, Copilot Studio, GitHub Copilot, Copilot Cowork, Opal, Copilot Autopilot, Agent 365, Entra and
Defender, plus OpenAI, Anthropic, Google, xAI, Meta, Mistral, Salesforce and CrowdStrike.

No servers and no packages to install: the collector uses only the Python standard library.

## Set it up

1. Create a new repository on GitHub (public, so Pages is free) and upload everything in this
   folder, keeping the folder structure. The `.github` folder must be included.
2. Open **Settings → Pages**. Under *Build and deployment* choose **Deploy from a branch**,
   branch **main**, folder **/docs**, and save.
3. Open the **Actions** tab. The *Update news* workflow starts on the first upload; if it has
   not, select it and choose **Run workflow**. It takes about a minute.
4. Open the address shown in Settings → Pages. Optional: put that address in `site.url` in
   `config.toml` so the site's own RSS feed links back to it.

If the workflow fails at the last step with a permission error, open **Settings → Actions →
General → Workflow permissions** and choose **Read and write permissions**.

## What you get

- **Overview**: one row per product and per competitor showing posts per day for four weeks,
  the week's key items, and the latest post for each product.
- **Microsoft** and **Competitors**: a day-by-day timeline you can filter by product or
  company, status (Preview, Generally available, Frontier, Retiring), period and search text.
  Posts that arrived since your last visit are marked New.
- **Sources**: every source, how many posts it contributed, and whether the last read worked.
- **`feed.xml`**: everything as one RSS feed, including the sites that have no feed of their
  own, so you can also follow it from a feed reader.

## Change what it tracks

Everything is in [`config.toml`](config.toml). Edit it on github.com; saving starts a run.

- **Add a product**: copy a `[[topics]]` block and set the words that identify it. `none`
  lists phrases that rule a post out (this is how Windows Autopilot and Optimizely Opal are
  kept away from Copilot Autopilot and Microsoft's Opal).
- **Add a theme**: a `[[topics]]` block with `theme = true` tags posts from every company
  (personal agents and decision models are set up this way).
- **Add a site with an RSS feed**: copy a `[[sources]]` block with `type = "rss"`.
- **Add a site without a feed**: use `type = "page"`, point `url` at its news listing and set
  `link_pattern` to a regular expression that matches the path of its posts. The collector
  opens each new post once to read its title, description and date.
- **Turn a source off**: add `enabled = false` to its block.
- **Change how often it runs**: edit the `cron` line in `.github/workflows/update.yml`.

## AI summaries (optional)

Without any setup the site shows each publisher's own excerpt. To add AI-written summaries,
a "key item" rating and "competes with" tags, give the workflow an OpenAI-compatible chat
completions endpoint. In **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
| --- | --- |
| `SUMMARY_ENDPOINT` | e.g. `https://<resource>.openai.azure.com/openai/v1/chat/completions` (Azure OpenAI / Microsoft Foundry), or any OpenAI-compatible URL |
| `SUMMARY_API_KEY` | the key for that endpoint |
| `SUMMARY_MODEL` | the model or deployment name, e.g. `gpt-4.1-mini` |

Each run summarises at most `max_per_run` posts in batches and catches up over the following
runs. If the endpoint fails, the site still updates. The Sources page reports what happened.

Model output is checked before it is stored and is only ever shown as plain text. It can
still be wrong: treat summaries as a pointer to the source, not a replacement for it.

## Run it on your own machine

    python scripts/collect.py --no-ai        # needs Python 3.11 or newer
    python -m http.server --directory docs   # then open http://localhost:8000
    python -m unittest discover -s tests     # the collector's tests

## Good to know

- Status labels are detected from wording in the title and opening lines, so an occasional
  post will be labelled wrongly or not at all.
- A site can change its layout or block automated readers. When that happens the source shows
  as failed on the Sources page and the others carry on.
- This is a personal project and is not affiliated with Microsoft or any company it lists.
  The page says so in its footer; keep that if you publish it.
