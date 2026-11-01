# traffic-cards

Builds the Kauaʻi road-closures page for kauaiconnect.com/traffic/.

`build.py` pulls planned state-highway closures for Kauaʻi from HDOT's public ArcGIS feature
service, groups the per-day records into cards, and writes one self-contained `dist/index.html`
(cards + Leaflet map + the official HDOT listing as a fallback underneath).
A GitHub Action rebuilds it hourly and publishes it to GitHub Pages.

## Set up (once)

1. Create a new repo (e.g. `amandafluharty-hdc/traffic-cards`) and push these files to `main`.
2. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions** tab → *Build traffic page* → **Run workflow**. The page appears at
   `https://<user>.github.io/traffic-cards/`.
4. On the WordPress `/traffic/` page, replace the two embeds with one HTML block:

```html
<iframe id="kc-traffic" src="https://<user>.github.io/traffic-cards/"
        style="width:100%;border:0;min-height:1400px" title="Kauaʻi road closures"></iframe>
<script>
addEventListener('message', e => {
  if (e.data && e.data.kcTrafficHeight)
    document.getElementById('kc-traffic').style.height = (e.data.kcTrafficHeight + 20) + 'px';
});
</script>
```

The script makes the iframe grow to fit, so the page doesn't get a scrollbar inside a scrollbar.

## Run locally

```
python build.py                                        # live data (needs internet)
python build.py --fixture fixtures/kauai_sample.json   # offline sample
```

Open `dist/index.html?now=2026-10-30T08:00` to preview the page as of a given Hawaiʻi time.

## Things to check / edit in `build.py`

- `ROUTES`: route number → road name. Unlisted routes show as "Route N".
- `TOWNS`: reference points used to label each closure "Near …" and assign a region
  (north / east / south / west). Edit the region for each town to match the region slugs on the site
  (Līhuʻe is currently "east").
- `HORIZON_DAYS`: how far ahead to show (default 7).

## Notes

- Data is HDOT's *planned* lane-closure layer only: no crashes, weather or emergency closures.
- The feed stores one record per day per closure, so the page groups repeats into one card.
- GitHub pauses scheduled workflows on a repo with no activity for 60 days. If the page stops
  updating, re-enable it on the Actions tab (or push any commit).
- If HDOT moves the feature service, update `SERVICE` in `build.py`; the dashboard's data sources
  can be found via the item ID in the experience.arcgis.com URL.
