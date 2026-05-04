from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)


def allowed_fetch(client_get, url: str, user_agent: str) -> bool:
    """
    Return True if robots.txt allows GET for this URL (or robots unavailable).
    client_get: callable(url) -> object with .status_code and .text
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return True
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = urljoin(base, "/robots.txt")
    try:
        resp = client_get(robots_url)
        if resp.status_code != 200:
            return True
        rp = RobotFileParser()
        rp.parse(resp.text.splitlines())
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        ok = rp.can_fetch(user_agent, url)
        if not ok:
            log.warning("robots.txt disallows %s", url)
        return ok
    except OSError as e:
        log.debug("robots check skipped for %s: %s", url, e)
        return True
