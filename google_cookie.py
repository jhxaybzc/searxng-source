import json, glob, random, time
from urllib.parse import urlencode, urlparse, parse_qs
from lxml import html
from curl_cffi import requests as cr
from searx.exceptions import SearxEngineCaptchaException, SearxEngineAccessDeniedException

engine_type = "offline"
categories = ["general", "web"]
paging = True
time_range_support = True
safesearch = True
language_support = True
about = {"website": "https://www.google.com", "use_official_api": False, "require_api_key": False, "results": "HTML"}
COOKIE_DIR = "/etc/searxng/google-cookies"
MAX_AGE = 3 * 3600

def _sets():
    out = []
    for f in glob.glob(COOKIE_DIR + "/*.json"):
        try:
            d = json.load(open(f))
            if d.get("ok") and time.time() - d.get("ts", 0) < MAX_AGE:
                d["_file"] = f
                out.append(d)
        except Exception:
            pass
    random.shuffle(out)
    return out

def _mark_bad(d):
    try:
        f = d.pop("_file")
        d["ok"] = False
        json.dump(d, open(f, "w"))
    except Exception:
        pass

def _clean(href):
    if href.startswith("/url?"):
        q = parse_qs(urlparse(href).query)
        href = (q.get("q") or q.get("url") or [""])[0]
    return href

def parse(text):
    dom = html.fromstring(text)
    results = []
    for h3 in dom.xpath("//h3"):
        a = h3.xpath("ancestor::a[@href][1]")
        if not a:
            continue
        href = _clean(a[0].get("href"))
        if not href.startswith("http") or "google." in urlparse(href).netloc:
            continue
        title = " ".join(h3.text_content().split())
        content = ""
        box = h3.xpath("ancestor::div[contains(@class,'MjjYud') or contains(@class,'tF2Cxc') or contains(@class,'g ')][1]")
        if box:
            sn = box[0].xpath(".//div[contains(@class,'VwiC3b')] | .//div[@data-sncf] | .//span[contains(@class,'aCOpRe')]")
            if sn:
                content = " ".join(sn[0].text_content().split())
        if title and not any(x["url"] == href for x in results):
            results.append({"url": href, "title": title, "content": content})
    return results

def search(query, params):
    sets = _sets()
    if not sets:
        raise SearxEngineAPIException("google browser busy")
    args = {"q": query, "hl": "en", "gl": "us"}
    if params.get("pageno", 1) > 1:
        args["start"] = (params["pageno"] - 1) * 10
    tr = {"day": "d", "week": "w", "month": "m", "year": "y"}
    if params.get("time_range") in tr:
        args["tbs"] = "qdr:" + tr[params["time_range"]]
    if params.get("safesearch"):
        args["safe"] = "active"
    url = "https://www.google.com/search?" + urlencode(args)
    last = None
    for d in sets[:2]:
        try:
            r = cr.get(url, impersonate="chrome", proxies={"https": d["proxy"]}, timeout=8, allow_redirects=False,
                       headers={"User-Agent": d["ua"], "Accept-Language": "en-US,en;q=0.9"},
                       cookies={c["name"]: c["value"] for c in d["cookies"]})
        except Exception as e:
            last = e
            continue
        if r.status_code in (302, 403, 429) or "/sorry" in (r.headers.get("location") or ""):
            _mark_bad(d)
            last = SearxEngineCaptchaException()
            continue
        results = parse(r.text, d["proxy"])
        if results or "<h3" in r.text:
            return results
        _mark_bad(d)
        last = SearxEngineCaptchaException()
    raise last or SearxEngineAccessDeniedException()

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

def _resolve(u, proxy):
    try:
        r = cr.get(urljoin("https://www.google.com/", u), impersonate="chrome", proxies={"https": proxy}, timeout=4, allow_redirects=False)
        loc = r.headers.get("location") or ""
        return loc if loc.startswith("http") else None
    except Exception:
        return None

def parse(text, proxy=None):
    dom = html.fromstring(text)
    items = []
    for h3 in dom.xpath("//h3"):
        a = h3.xpath("ancestor::a[@href][1]")
        if not a:
            continue
        title = " ".join(h3.text_content().split())
        content = ""
        box = h3.xpath("ancestor::div[contains(@class,'MjjYud') or contains(@class,'tF2Cxc')][1]")
        if box:
            sn = box[0].xpath(".//div[contains(@class,'VwiC3b')] | .//div[@data-sncf]")
            if sn:
                content = " ".join(sn[0].text_content().split())
        if title:
            items.append((a[0].get("href"), title, content))
    todo = list(dict.fromkeys(h for h, _, _ in items if h.startswith("/goto") or (h.startswith("/url") and "CAES" in h)))
    found = {}
    if todo and proxy:
        with ThreadPoolExecutor(5) as ex:
            found = dict(zip(todo, ex.map(lambda u: _resolve(u, proxy), todo)))
    results = []
    for href, title, content in items:
        url = found.get(href) or _clean(href)
        if not url or not url.startswith("http") or "google." in urlparse(url).netloc:
            continue
        if not any(x["url"] == url for x in results):
            results.append({"url": url, "title": title, "content": content})
    return results

def _from_cite(box):
    c = box.xpath(".//cite") if box is not None else []
    if not c:
        return None, None
    t = " ".join(c[0].text_content().split())
    parts = [p.strip() for p in t.split("›") if p.strip()]
    if not parts:
        return None, None
    base = parts[0] if parts[0].startswith("http") else "https://" + parts[0]
    base = base.rstrip("/")
    if "..." in t or "…" in t:
        return None, base
    return base + ("/" + "/".join(parts[1:]) if len(parts) > 1 else ""), base

def parse(text, proxy=None):
    dom = html.fromstring(text)
    items = []
    for h3 in dom.xpath("//h3"):
        a = h3.xpath("ancestor::a[@href][1]")
        if not a:
            continue
        title = " ".join(h3.text_content().split())
        box = (h3.xpath("ancestor::div[contains(@class,'MjjYud') or contains(@class,'tF2Cxc')][1]") or [None])[0]
        content = ""
        if box is not None:
            sn = box.xpath(".//div[contains(@class,'VwiC3b')] | .//div[@data-sncf]")
            if sn:
                content = " ".join(sn[0].text_content().split())
        href = a[0].get("href")
        direct = _clean(href) if not href.startswith("/goto") else ""
        cited, base = _from_cite(box)
        if title:
            items.append([direct if direct.startswith("http") else cited, href, base, title, content])
    todo = list(dict.fromkeys(it[1] for it in items if not it[0] and (it[1].startswith("/goto") or "CAES" in it[1])))[:4]
    found = {}
    if todo and proxy:
        with ThreadPoolExecutor(4) as ex:
            found = dict(zip(todo, ex.map(lambda u: _resolve(u, proxy), todo)))
    results = []
    for url, href, base, title, content in items:
        url = url or found.get(href) or base
        if not url or not url.startswith("http") or "google." in urlparse(url).netloc:
            continue
        if not any(x["url"] == url for x in results):
            results.append({"url": url, "title": title, "content": content})
    return results

import threading
_tl = threading.local()
_POOL = ThreadPoolExecutor(6)

def _sess(proxy):
    m = getattr(_tl, "m", None)
    if m is None:
        m = _tl.m = {}
    if proxy not in m:
        m[proxy] = cr.Session(impersonate="chrome", proxies={"https": proxy})
    return m[proxy]

def _resolve(u, proxy):
    try:
        r = _sess(proxy).get(urljoin("https://www.google.com/", u), timeout=4, allow_redirects=False)
        loc = r.headers.get("location") or ""
        return loc if loc.startswith("http") else None
    except Exception:
        return None

def parse(text, proxy=None):
    dom = html.fromstring(text)
    items = []
    for h3 in dom.xpath("//h3"):
        a = h3.xpath("ancestor::a[@href][1]")
        if not a:
            continue
        title = " ".join(h3.text_content().split())
        box = (h3.xpath("ancestor::div[contains(@class,'MjjYud') or contains(@class,'tF2Cxc')][1]") or [None])[0]
        content = ""
        if box is not None:
            sn = box.xpath(".//div[contains(@class,'VwiC3b')] | .//div[@data-sncf]")
            if sn:
                content = " ".join(sn[0].text_content().split())
        href = a[0].get("href")
        direct = _clean(href) if not href.startswith("/goto") else ""
        if title:
            items.append([direct if direct.startswith("http") else None, href, _from_cite(box)[1], title, content])
    todo = list(dict.fromkeys(it[1] for it in items if not it[0]))[:10]
    found = dict(zip(todo, _POOL.map(lambda u: _resolve(u, proxy), todo))) if todo and proxy else {}
    results = []
    for url, href, base, title, content in items:
        url = url or found.get(href) or base
        if not url or not url.startswith("http") or "google." in urlparse(url).netloc:
            continue
        if not any(x["url"] == url for x in results):
            results.append({"url": url, "title": title, "content": content})
    return results

def search(query, params):
    sets = _sets()
    if not sets:
        raise SearxEngineAPIException("google browser busy")
    args = {"q": query, "hl": "en", "gl": "us", "udm": "14"}
    if params.get("pageno", 1) > 1:
        args["start"] = (params["pageno"] - 1) * 10
    tr = {"day": "d", "week": "w", "month": "m", "year": "y"}
    if params.get("time_range") in tr:
        args["tbs"] = "qdr:" + tr[params["time_range"]]
    if params.get("safesearch"):
        args["safe"] = "active"
    url = "https://www.google.com/search?" + urlencode(args)
    last = None
    for d in sets[:2]:
        try:
            r = _sess(d["proxy"]).get(url, timeout=10, allow_redirects=False,
                headers={"User-Agent": d["ua"], "Accept-Language": "en-US,en;q=0.9"},
                cookies={c["name"]: c["value"] for c in d["cookies"]})
        except Exception as e:
            last = e
            continue
        if r.status_code in (302, 403, 429) or "/sorry" in (r.headers.get("location") or ""):
            _mark_bad(d)
            last = SearxEngineCaptchaException()
            continue
        results = parse(r.text, d["proxy"])
        if results or "<h3" in r.text:
            return results
        _mark_bad(d)
        last = SearxEngineCaptchaException()
    raise last or SearxEngineAccessDeniedException()

def _resolve(u, proxy):
    return "https://search.jeremyh.xyz" + u if u.startswith("/goto") else None

import urllib.request as _ur

def _resolve(u, proxy):
    if not u.startswith("/goto"):
        return None
    try:
        tok = parse_qs(urlparse(u).query).get("url", [""])[0]
        i = _ur.urlopen(_ur.Request("http://goto-resolver:8000/add", data=tok.encode()), timeout=2).read().decode()
        return "https://search.jeremyh.xyz/r/" + i
    except Exception:
        return None

def search(query, params):
    args = {"q": query, "hl": "en", "gl": "us", "udm": "14"}
    if params.get("pageno", 1) > 1:
        args["start"] = (params["pageno"] - 1) * 10
    tr = {"day": "d", "week": "w", "month": "m", "year": "y"}
    if params.get("time_range") in tr:
        args["tbs"] = "qdr:" + tr[params["time_range"]]
    if params.get("safesearch"):
        args["safe"] = "active"
    try:
        r = cr.get("http://google-browser:8940/search?" + urlencode(args), timeout=25)
    except Exception:
        raise SearxEngineAPIException("google browser busy")
    if r.status_code != 200:
        raise SearxEngineAPIException("google browser busy")
    return parse(r.text, "browser")

SOLVE_URL = "https://search.jeremyh.xyz/__google/solve.html?next=%2F"

def search(query, params):
    args = {"q": query, "hl": "en", "gl": "us", "udm": "14"}
    if params.get("pageno", 1) > 1:
        args["start"] = (params["pageno"] - 1) * 10
    tr = {"day": "d", "week": "w", "month": "m", "year": "y"}
    if params.get("time_range") in tr:
        args["tbs"] = "qdr:" + tr[params["time_range"]]
    if params.get("safesearch"):
        args["safe"] = "active"
    try:
        r = cr.get("http://google-browser:8940/search?" + urlencode(args), timeout=20)
    except Exception:
        raise SearxEngineAPIException("google browser busy")
    if r.status_code == 503 and r.text == "captcha":
        return []
    if False:
        return [{"url": SOLVE_URL,
                 "title": "Google needs a quick human check. Click here to solve it.",
                 "content": "Opens Google's own check inside this site's browser. Google does not see your address."}]
    if r.status_code != 200:
        raise SearxEngineAPIException("google browser busy")
    return parse(r.text, "browser")

import re as _re2
_DOM = _re2.compile(r"^https?://[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", _re2.I)
_orig_from_cite = _from_cite
_orig_clean = _clean

def _from_cite(box):
    full, base = _orig_from_cite(box)
    if base and not _DOM.match(base):
        base = None
    if full and not _DOM.match(full):
        full = None
    return full, base

def _clean(href):
    if "CAES" in href or "/goto?" in href:
        return ""
    return _orig_clean(href)

def _resolve(u, proxy):
    q = parse_qs(urlparse(u).query)
    tok = next((v[0] for v in q.values() if v and v[0].startswith("CAES")), "")
    if not tok:
        return None
    try:
        i = _ur.urlopen(_ur.Request("http://goto-resolver:8000/add", data=tok.encode()), timeout=2).read().decode()
        return "https://search.jeremyh.xyz/r/" + i
    except Exception:
        return None
import urllib.request as _ur
from searx.exceptions import SearxEngineAPIException
