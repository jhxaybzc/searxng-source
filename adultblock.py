import os, time
from urllib.parse import urlparse
from searx.plugins import Plugin, PluginInfo
from searx.result_types import EngineResults

LIST = "/etc/searxng/nsfw-domains.txt"
IMAGE = "https://search.jeremyh.xyz/__saw"
NEEDED = 1
NOTICE = "Some results were hidden because they come from adult websites."

class SXNGPlugin(Plugin):
    id = "adultblock"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        self.info = PluginInfo(id=self.id, name="Adult site filter",
            description="Removes results from known adult websites", preference_section="general")
        self.domains, self.mtime, self.checked = set(), 0, 0

    def _load(self):
        now = time.time()
        if now - self.checked < 600:
            return
        self.checked = now
        try:
            m = os.path.getmtime(LIST)
            if m != self.mtime:
                with open(LIST) as f:
                    self.domains = {l.strip().lower() for l in f if l.strip() and not l.startswith("#")}
                self.mtime = m
        except OSError:
            pass

    def init(self, app):
        self._load()
        import flask

        @app.after_request
        def _adult_redirect(resp):
            if getattr(flask.g, "adult_hidden", 0) >= NEEDED:
                return flask.redirect(IMAGE, 302)
            return resp
        return True

    def on_result(self, request, search, result):
        self._load()
        url = getattr(result, "url", None)
        if not url and hasattr(result, "get"):
            url = result.get("url")
        parts = (urlparse(url or "").hostname or "").lower().split(".")
        for i in range(len(parts) - 1):
            if ".".join(parts[i:]) in self.domains:
                setattr(search, "_adult_hidden", getattr(search, "_adult_hidden", 0) + 1)
                return False
        return True

    def post_search(self, request, search):
        results = EngineResults()
        import flask
        flask.g.adult_hidden = getattr(search, "_adult_hidden", 0)
        if getattr(search, "_adult_hidden", 0):
            results.add(results.types.Answer(answer=NOTICE))
        return results
