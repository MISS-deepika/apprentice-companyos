"""Thin Playwright wrapper. The agent perceives pages as (url, text, interactive elements by role+name)
and acts through semantic targets - never CSS selectors - which is what makes learned skills repairable."""
import re
from playwright.sync_api import sync_playwright, Error as PWError


class StepError(Exception):
    pass


JS_ELEMENTS = """() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const nameOf = e => {
    const al = e.getAttribute('aria-label'); if (al) return al.trim();
    if (e.id) { const l = document.querySelector('label[for="' + e.id + '"]'); if (l) return l.innerText.trim(); }
    if (e.tagName === 'INPUT' && ['submit', 'button'].includes(e.type)) return (e.value || '').trim();
    const t = (e.innerText || '').trim(); if (t) return t;
    return (e.getAttribute('placeholder') || e.getAttribute('title') || '').trim();
  };
  const roleOf = e => {
    const t = e.tagName;
    if (t === 'A') return 'link'; if (t === 'BUTTON') return 'button'; if (t === 'TEXTAREA') return 'textbox';
    if (t === 'INPUT') { const ty = e.type;
      if (['submit', 'button'].includes(ty)) return 'button'; if (ty === 'search') return 'searchbox'; return 'textbox'; }
    return null;
  };
  const out = [];
  document.querySelectorAll('a[href],button,input,textarea').forEach(e => {
    if (!vis(e)) return; const r = roleOf(e); if (!r) return;
    out.push({role: r, name: nameOf(e)});
  });
  return out;
}"""


def render(value, params):
    if isinstance(value, str):
        for k, v in (params or {}).items():
            value = value.replace("{{%s}}" % k, str(v))
    return value


class Browser:
    def __init__(self, base_url, headless=True):
        self.base = base_url.rstrip("/")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self.page = self._browser.new_page(viewport={"width": 1100, "height": 750})
        self.page.set_default_timeout(4000)

    def snapshot(self):
        p = self.page
        url = p.url.replace(self.base, "") or "/"
        status = ""
        loc = p.locator("[role=status]")
        if loc.count():
            status = loc.first.inner_text().strip()
        return {"url": url, "status": status, "text": p.inner_text("body")[:1800],
                "elements": p.evaluate(JS_ELEMENTS)}

    def _loc(self, target):
        loc = self.page.get_by_role(target["role"], name=target["name"], exact=True)
        if loc.count() == 0:
            raise StepError(f"No {target['role']} named '{target['name']}' on {self.page.url.replace(self.base, '') or '/'}")
        return loc.first

    def path(self):
        return self.page.url.replace(self.base, "") or "/"

    def has(self, target):
        return self.page.get_by_role(target["role"], name=target["name"], exact=True).count() > 0

    def act(self, step):
        d = step.get("do")
        try:
            if d == "goto":
                if not step["url"].startswith("/"):
                    raise StepError("only relative company URLs are allowed")
                self.page.goto(self.base + step["url"])
            elif d == "type":
                self._loc(step["target"]).fill(step["value"])
            elif d == "click":
                self._loc(step["target"]).click()
            else:
                raise StepError(f"unknown action '{d}'")
            self.page.wait_for_load_state("load")
        except PWError as e:
            raise StepError(str(e).splitlines()[0])

    def check_assert(self, spec, params=None):
        if not spec or not spec.get("text_matches"):
            return
        pattern = render(spec["text_matches"], params)
        if not re.search(pattern, self.page.inner_text("body")):
            raise StepError(f"assertion failed: expected text matching /{pattern}/ not visible")

    def screenshot(self, path):
        self.page.screenshot(path=str(path))

    def close(self):
        try:
            self._browser.close(); self._pw.stop()
        except Exception:
            pass
