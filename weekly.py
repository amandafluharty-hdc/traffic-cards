"""Pull HDOT's weekly Kauaʻi lane-closure list as structured text.

Source page: https://hidot.hawaii.gov/highways/roadwork/kauai/
The page is a flat list of <p> tags inside <div class="primary-content">:
  FOR THE WEEK OF ...        -> week label
  PLEASE NOTE: / <para>      -> note
  — HIGHWAY NAME —           -> group heading
  1) TOWN                    -> area label for the next paragraph
  <paragraph>                -> one closure
  # # #                      -> end (media contact follows; we ignore it)

Everything here is best-effort: if HDOT changes the page, parse_weekly returns
None and the site shows a link to HDOT instead of breaking the build.
"""
import re
import urllib.request
from html.parser import HTMLParser

URL = "https://hidot.hawaii.gov/highways/roadwork/kauai/"
UA = "Mozilla/5.0 (compatible; kauaiconnect-traffic/1.0; +https://kauaiconnect.com)"


class _Blocks(HTMLParser):
    """Collect the <p> children of div.primary-content as lists of text/link parts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.depth = 0
        self.cur = None
        self.href = None
        self.blocks = []

    def _finish(self):
        if self.cur is not None:
            segs = []
            for t, href in self.cur:
                t = re.sub(r"\s+", " ", t.replace("\xa0", " "))
                if t:
                    segs.append({"t": t, "href": href})
            if segs:
                segs[0]["t"] = segs[0]["t"].lstrip()
                segs[-1]["t"] = segs[-1]["t"].rstrip()
                segs = [s for s in segs if s["t"]]
            if segs:
                self.blocks.append(segs)
        self.cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self.active:
            if tag == "div" and "primary-content" in (a.get("class") or "").split():
                self.active, self.depth = True, 1
            return
        if tag == "div":
            self.depth += 1
        elif tag == "p" and self.depth == 1:
            self._finish()
            self.cur = []
        elif tag == "br" and self.cur is not None:
            self.cur.append((" ", None))
        elif tag == "a" and self.cur is not None:
            self.href = a.get("href")

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self._finish()
                self.active = False
        elif tag == "p" and self.depth == 1:
            self._finish()
        elif tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.active and self.cur is not None:
            self.cur.append((data, self.href))


def parse_weekly(html):
    p = _Blocks()
    p.feed(html)
    week = note = None
    groups, cur, area, expect_note = [], None, None, False
    for segs in p.blocks:
        text = "".join(s["t"] for s in segs).strip()
        has_link = any(s["href"] for s in segs)
        if text.replace(" ", "") == "###":
            break
        if re.match(r"(?i)for the week of", text):
            week = "For the week of" + text[len("for the week of"):].title()
            continue
        if re.match(r"(?i)please note", text):
            expect_note = True
            continue
        if expect_note:
            note, expect_note = segs, False
            continue
        if text.startswith("—") and text.endswith("—"):
            cur = {"title": text.strip("— ").title(), "items": []}
            groups.append(cur)
            area = None
            continue
        m = re.match(r"^\d+\)\s*(.+)$", text)
        if m and len(text) < 80 and not has_link:
            area = m.group(1).title()
            continue
        if cur is None:
            continue
        cur["items"].append({"area": area, "segs": segs})
        area = None
    if not groups:
        return None
    return {"week": week, "note": note, "groups": groups, "url": URL}


def fetch_weekly():
    """Return the parsed weekly list, or None if the page can't be fetched/parsed."""
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            html = r.read().decode("utf-8", errors="replace")
        return parse_weekly(html)
    except Exception as e:  # never let HDOT's website break the build
        print(f"warning: could not read HDOT weekly page: {e}")
        return None
