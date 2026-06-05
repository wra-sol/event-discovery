from __future__ import annotations

import copy
import json
import logging
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .dedupe import merge_discovered_event_group
from .models import DiscoveredEvent, dedupe_key_from_url_title
from .source_validation import slugify_source_key

log = logging.getLogger(__name__)


def _merge_notes_distinct(notes: list[str]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for n in notes:
        t = (n or "").strip()
        if t and t not in seen:
            seen.add(t)
            parts.append(t)
    return "\n\n".join(parts)


def compact_series_duplicates(conn: sqlite3.Connection) -> tuple[int, int]:
    """
    Merge rows that share the same logical dedupe key (e.g. Tribe one-per-occurrence URLs).
    Returns (removed_row_count, dedupe_key_normalized_count).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, dedupe_key, title, url, source, website_id, start_at, end_at, venue, raw_snippet,
               relevance_score, relevance_reasons_json, first_seen_at, last_seen_at,
               reviewed, rejected, notes, last_run_id
        FROM discovered_events
        """
    )
    rows = cur.fetchall()
    if not rows:
        return (0, 0)

    groups: dict[str, list[tuple[sqlite3.Row, DiscoveredEvent]]] = {}
    for r in rows:
        reasons_raw = r["relevance_reasons_json"] or "[]"
        try:
            reasons = json.loads(reasons_raw)
        except json.JSONDecodeError:
            reasons = []
        if not isinstance(reasons, list):
            reasons = []
        ev = DiscoveredEvent(
            title=r["title"] or "",
            url=r["url"] or "",
            source=r["source"] or "",
            website_id=r["website_id"],
            start=r["start_at"],
            end=r["end_at"],
            venue=r["venue"],
            raw_snippet=r["raw_snippet"] or "",
            relevance_score=float(r["relevance_score"] or 0),
            relevance_reasons=[str(x) for x in reasons],
        )
        k = dedupe_key_from_url_title(ev.url, ev.title)
        groups.setdefault(k, []).append((r, ev))

    removed = 0
    key_fixes = 0
    for k, pairs in groups.items():
        if len(pairs) == 1:
            r = pairs[0][0]
            if r["dedupe_key"] != k:
                cur.execute(
                    "UPDATE discovered_events SET dedupe_key = ? WHERE id = ?",
                    (k, r["id"]),
                )
                key_fixes += 1
            continue

        wi = 0
        for i, (row, _) in enumerate(pairs):
            if row["reviewed"]:
                wi = i
                break
        else:
            cand = [i for i in range(len(pairs)) if not pairs[i][0]["rejected"]]
            if not cand:
                cand = list(range(len(pairs)))
            best_i = cand[0]
            best_s = pairs[best_i][0]["start_at"] or "9999"
            for i in cand[1:]:
                row = pairs[i][0]
                s = row["start_at"] or "9999"
                if s < best_s:
                    best_s = s
                    best_i = i
            wi = best_i

        merged_ev = merge_discovered_event_group([ev for _, ev in pairs])
        winner_row = pairs[wi][0]
        winner_id = int(winner_row["id"])
        loser_ids = [int(pairs[i][0]["id"]) for i in range(len(pairs)) if i != wi]

        reviewed = 1 if any(pairs[i][0]["reviewed"] for i in range(len(pairs))) else 0
        rejected = (
            0
            if reviewed
            else (1 if any(pairs[i][0]["rejected"] for i in range(len(pairs))) else 0)
        )
        notes = _merge_notes_distinct([pairs[i][0]["notes"] or "" for i in range(len(pairs))])
        first_seen = min(pairs[i][0]["first_seen_at"] for i in range(len(pairs)))
        last_seen = max(pairs[i][0]["last_seen_at"] for i in range(len(pairs)))
        run_ids = [
            pairs[i][0]["last_run_id"]
            for i in range(len(pairs))
            if pairs[i][0]["last_run_id"] is not None
        ]
        last_run_id = max(run_ids) if run_ids else None

        reasons_json = json.dumps(merged_ev.relevance_reasons, ensure_ascii=False)
        cur.execute(
            """
            UPDATE discovered_events SET
                dedupe_key = ?, title = ?, url = ?, source = ?, website_id = ?, start_at = ?, end_at = ?,
                venue = ?, raw_snippet = ?, relevance_score = ?, relevance_reasons_json = ?,
                first_seen_at = ?, last_seen_at = ?, reviewed = ?, rejected = ?, notes = ?, last_run_id = ?
            WHERE id = ?
            """,
            (
                k,
                merged_ev.title,
                merged_ev.url,
                merged_ev.source,
                merged_ev.website_id,
                merged_ev.start,
                merged_ev.end,
                merged_ev.venue,
                merged_ev.raw_snippet,
                merged_ev.relevance_score,
                reasons_json,
                first_seen,
                last_seen,
                reviewed,
                rejected,
                notes,
                last_run_id,
                winner_id,
            ),
        )
        for lid in loser_ids:
            cur.execute("DELETE FROM discovered_events WHERE id = ?", (lid,))
        removed += len(loser_ids)

    if removed:
        log.info("Merged recurring/listing duplicates: removed %d extra row(s)", removed)
    if key_fixes:
        log.info("Normalized dedupe_key on %d row(s)", key_fixes)
    return (removed, key_fixes)


@dataclass
class EventListFilters:
    source: str | None = None
    min_score: float | None = None
    reviewed: bool | None = None
    rejected: bool | None = None
    q: str | None = None
    start_from: str | None = None
    """Inclusive YYYY-MM-DD; only rows with a parseable start_at date are included when set."""
    start_to: str | None = None
    """Inclusive YYYY-MM-DD when set alongside start_from or alone."""
    include_past: bool = True
    """When False, rows with a parseable start date before as_of_date are excluded."""
    as_of_date: str | None = None
    """YYYY-MM-DD; compared to substr(start_at,1,10) when include_past is False."""
    website_id: int | None = None
    sort: str = "relevance"
    """relevance | start_at | title | source | reviewed."""
    order: str | None = None
    """asc | desc; None uses a sensible default per sort key."""
    first_seen_since_utc: str | None = None
    """ISO8601 UTC lower bound for first_seen_at (automation: newly discovered events)."""


def _events_where_clause(filters: EventListFilters) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if filters.source:
        conditions.append("source = ?")
        params.append(filters.source)
    if filters.min_score is not None:
        conditions.append("relevance_score >= ?")
        params.append(filters.min_score)
    if filters.reviewed is not None:
        conditions.append("reviewed = ?")
        params.append(1 if filters.reviewed else 0)
    if filters.rejected is not None:
        conditions.append("rejected = ?")
        params.append(1 if filters.rejected else 0)
    if filters.q and filters.q.strip():
        like = f"%{filters.q.strip()}%"
        conditions.append(
            "(title LIKE ? OR url LIKE ? OR IFNULL(venue,'') LIKE ? OR IFNULL(raw_snippet,'') LIKE ?)"
        )
        params.extend([like, like, like, like])
    if filters.website_id is not None:
        conditions.append("website_id = ?")
        params.append(filters.website_id)
    if filters.start_from or filters.start_to:
        conditions.append("start_at IS NOT NULL")
        conditions.append("length(trim(start_at)) >= 10")
        # 1-based substr: YYYY-MM-DD prefix
        conditions.append("substr(start_at, 5, 1) = '-'")
        conditions.append("substr(start_at, 8, 1) = '-'")
        if filters.start_from:
            conditions.append("substr(start_at, 1, 10) >= ?")
            params.append(filters.start_from.strip()[:10])
        if filters.start_to:
            conditions.append("substr(start_at, 1, 10) <= ?")
            params.append(filters.start_to.strip()[:10])
    if filters.first_seen_since_utc:
        conditions.append("first_seen_at >= ?")
        params.append(filters.first_seen_since_utc.strip())
    if not filters.include_past:
        raw = (filters.as_of_date or "").strip()[:10]
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            as_of = raw
        else:
            as_of = date.today().isoformat()
        conditions.append(
            "("
            "start_at IS NULL OR trim(start_at) = '' OR length(trim(start_at)) < 10 "
            "OR substr(start_at, 5, 1) != '-' OR substr(start_at, 8, 1) != '-' "
            "OR substr(start_at, 1, 10) >= ?"
            ")"
        )
        params.append(as_of)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


def _default_order_for_sort(sort: str) -> str:
    if sort in ("start_at", "title", "source", "reviewed"):
        return "asc"
    return "desc"


def _events_order_clause(sort: str, order: str | None) -> str:
    allowed_sorts = ("relevance", "start_at", "title", "source", "reviewed")
    sort_norm = sort if sort in allowed_sorts else "relevance"
    o = order if order in ("asc", "desc") else None
    if o is None:
        o = _default_order_for_sort(sort_norm)
    asc, desc = "ASC", "DESC"
    sql_dir = desc if o == "desc" else asc
    if sort_norm == "relevance":
        return f"ORDER BY relevance_score {sql_dir}, title COLLATE NOCASE ASC"
    if sort_norm == "start_at":
        return (
            "ORDER BY (start_at IS NULL OR trim(start_at) = ''), "
            f"start_at {sql_dir}, title COLLATE NOCASE ASC"
        )
    if sort_norm == "title":
        return f"ORDER BY title COLLATE NOCASE {sql_dir}"
    if sort_norm == "source":
        return f"ORDER BY source COLLATE NOCASE {sql_dir}, title COLLATE NOCASE ASC"
    if sort_norm == "reviewed":
        return (
            f"ORDER BY reviewed {sql_dir}, rejected ASC, relevance_score DESC, "
            "title COLLATE NOCASE ASC"
        )
    return "ORDER BY relevance_score DESC, title COLLATE NOCASE ASC"


def count_discovered_events(conn: sqlite3.Connection, filters: EventListFilters) -> int:
    where, params = _events_where_clause(filters)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM discovered_events {where}", params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def list_discovered_events(
    conn: sqlite3.Connection,
    filters: EventListFilters,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _events_where_clause(filters)
    order_sql = _events_order_clause(filters.sort, filters.order)
    sql = f"""
        SELECT id, dedupe_key, title, url, source, website_id, start_at, end_at, venue, raw_snippet,
               relevance_score, relevance_reasons_json, first_seen_at, last_seen_at,
               reviewed, rejected, notes
        FROM discovered_events
        {where}
        {order_sql}
        LIMIT ? OFFSET ?
    """
    cur = conn.cursor()
    cur.execute(sql, [*params, limit, offset])
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        reasons_raw = r["relevance_reasons_json"] or "[]"
        try:
            reasons = json.loads(reasons_raw)
        except json.JSONDecodeError:
            reasons = []
        out.append(
            {
                "id": r["id"],
                "dedupe_key": r["dedupe_key"],
                "title": r["title"],
                "url": r["url"],
                "source": r["source"],
                "website_id": r["website_id"],
                "start_at": r["start_at"],
                "end_at": r["end_at"],
                "venue": r["venue"],
                "raw_snippet": r["raw_snippet"] or "",
                "relevance_score": float(r["relevance_score"] or 0),
                "relevance_reasons": reasons if isinstance(reasons, list) else [],
                "first_seen_at": r["first_seen_at"],
                "last_seen_at": r["last_seen_at"],
                "reviewed": bool(r["reviewed"]),
                "rejected": bool(r["rejected"]),
                "notes": r["notes"] or "",
            }
        )
    return out


def list_event_sources(conn: sqlite3.Connection) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT source FROM discovered_events ORDER BY source COLLATE NOCASE"
    )
    return [str(r["source"]) for r in cur.fetchall() if r["source"]]


def update_event_review(
    conn: sqlite3.Connection,
    event_id: int,
    *,
    reviewed: bool | None = None,
    rejected: bool | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute("SELECT id FROM discovered_events WHERE id = ?", (event_id,))
    if cur.fetchone() is None:
        return None
    sets: list[str] = []
    params: list[Any] = []
    if reviewed is not None or rejected is not None:
        if rejected is True:
            sets.append("reviewed = 0")
            sets.append("rejected = 1")
        elif reviewed is True:
            sets.append("reviewed = 1")
            sets.append("rejected = 0")
        elif reviewed is False:
            sets.append("reviewed = 0")
            sets.append("rejected = 0")
        elif rejected is False:
            sets.append("rejected = 0")
    if notes is not None:
        sets.append("notes = ?")
        params.append(notes)
    if not sets:
        cur.execute(
            """
            SELECT id, reviewed, rejected, notes FROM discovered_events WHERE id = ?
            """,
            (event_id,),
        )
        r = cur.fetchone()
        assert r is not None
        return {
            "id": event_id,
            "reviewed": bool(r["reviewed"]),
            "rejected": bool(r["rejected"]),
            "notes": r["notes"] or "",
        }
    params.append(event_id)
    cur.execute(
        f"UPDATE discovered_events SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()
    cur.execute(
        "SELECT id, reviewed, rejected, notes FROM discovered_events WHERE id = ?",
        (event_id,),
    )
    r = cur.fetchone()
    assert r is not None
    return {
        "id": event_id,
        "reviewed": bool(r["reviewed"]),
        "rejected": bool(r["rejected"]),
        "notes": r["notes"] or "",
    }


def websites_row_count(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM websites")
    row = cur.fetchone()
    return int(row[0]) if row else 0


def enabled_websites_count(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM websites WHERE enabled = 1")
    row = cur.fetchone()
    return int(row[0]) if row else 0


WEBSITE_PREFERENCE_KEYS = frozenset({"http", "scoring", "enrichment"})


def parse_website_preferences(raw: str | None) -> dict[str, Any]:
    """Parse preferences_json; only http, scoring, enrichment dict blocks are kept."""
    if not raw or not str(raw).strip():
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("preferences_json: invalid JSON, using empty dict")
        return {}
    if not isinstance(val, dict):
        return {}
    out: dict[str, Any] = {}
    for k in WEBSITE_PREFERENCE_KEYS:
        block = val.get(k)
        if isinstance(block, dict):
            out[str(k)] = dict(block)
    return out


def merge_site_preferences_into_cfg(
    base_cfg: dict[str, Any], prefs: dict[str, Any]
) -> dict[str, Any]:
    """Deep-merge website preference blocks over base_cfg (http, scoring, enrichment)."""
    out = copy.deepcopy(base_cfg)
    if not prefs:
        return out
    for k in WEBSITE_PREFERENCE_KEYS:
        p = prefs.get(k)
        if not isinstance(p, dict) or not p:
            continue
        base_block = out.get(k) if isinstance(out.get(k), dict) else {}
        out[str(k)] = _deep_merge_dict(dict(base_block), p)
    return out


def load_all_website_preferences(
    conn: sqlite3.Connection,
) -> dict[int, dict[str, Any]]:
    """Map websites.id -> parsed preferences dict (may be empty)."""
    cur = conn.cursor()
    cur.execute("SELECT id, preferences_json FROM websites")
    out: dict[int, dict[str, Any]] = {}
    for row in cur.fetchall():
        out[int(row["id"])] = parse_website_preferences(row["preferences_json"])
    return out


def discovery_settings_populated(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT key FROM discovery_settings WHERE key IN ('http', 'scoring')"
    )
    keys = {str(r["key"]) for r in cur.fetchall()}
    return "http" in keys and "scoring" in keys


_DISCOVERY_SETTING_KEYS = ("http", "scoring", "enrichment")


def merge_config_with_db(cfg: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    """Return a copy of cfg with http, scoring, and enrichment replaced when present in discovery_settings."""
    out = copy.deepcopy(cfg)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(_DISCOVERY_SETTING_KEYS))
    cur.execute(
        f"SELECT key, value_json FROM discovery_settings WHERE key IN ({placeholders})",
        _DISCOVERY_SETTING_KEYS,
    )
    for row in cur.fetchall():
        raw = row["value_json"] or "{}"
        try:
            val = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("discovery_settings %s: invalid JSON, skipping", row["key"])
            continue
        if isinstance(val, dict):
            out[str(row["key"])] = val
    return out


def sync_settings_from_config(conn: sqlite3.Connection, cfg: dict[str, Any]) -> int:
    """Upsert http, scoring, and enrichment JSON from merged YAML-shaped cfg. Returns rows touched."""
    cur = conn.cursor()
    n = 0
    for key in _DISCOVERY_SETTING_KEYS:
        block = cfg.get(key)
        if not isinstance(block, dict):
            continue
        cur.execute(
            """
            INSERT INTO discovery_settings (key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, json.dumps(block, ensure_ascii=False)),
        )
        n += 1
    conn.commit()
    log.info("Synced %d discovery_settings row(s) from config", n)
    return n


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _load_setting_json(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT value_json FROM discovery_settings WHERE key = ?",
        (key,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    raw = row["value_json"] or "{}"
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("discovery_settings %s: invalid JSON", key)
        return None
    return val if isinstance(val, dict) else None


def get_discovery_settings_bundle(
    conn: sqlite3.Connection, defaults_cfg: dict[str, Any]
) -> dict[str, Any]:
    """
    Return http, scoring, enrichment dicts merged from DB (when present) over defaults_cfg.
    """
    out: dict[str, Any] = {}
    for key in _DISCOVERY_SETTING_KEYS:
        base = defaults_cfg.get(key)
        base_d = base if isinstance(base, dict) else {}
        row = _load_setting_json(conn, key)
        if row is not None:
            out[key] = _deep_merge_dict(base_d, row)
        else:
            out[key] = copy.deepcopy(base_d)
    return out


def patch_discovery_settings(
    conn: sqlite3.Connection,
    *,
    http: dict[str, Any] | None = None,
    scoring: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
    defaults_cfg: dict[str, Any],
) -> None:
    """
    Shallow-merge each provided block into the current stored JSON for that key
    (or defaults from defaults_cfg if no row), then upsert.
    """
    cur = conn.cursor()
    for key, patch in (
        ("http", http),
        ("scoring", scoring),
        ("enrichment", enrichment),
    ):
        if patch is None:
            continue
        if not isinstance(patch, dict):
            continue
        base_d = defaults_cfg.get(key)
        base_d = base_d if isinstance(base_d, dict) else {}
        current = _load_setting_json(conn, key)
        merged = _deep_merge_dict(
            _deep_merge_dict(base_d, current) if current is not None else base_d,
            patch,
        )
        cur.execute(
            """
            INSERT INTO discovery_settings (key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, json.dumps(merged, ensure_ascii=False)),
        )
    conn.commit()


def set_all_websites_enabled(conn: sqlite3.Connection, enabled: bool) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE websites SET enabled = ?, updated_at = datetime('now')
        """,
        (1 if enabled else 0,),
    )
    conn.commit()
    return cur.rowcount


def ensure_discovery_seeded(conn: sqlite3.Connection, cfg: dict[str, Any]) -> None:
    """If settings or websites tables are empty, copy defaults from cfg (merged YAML)."""
    if not discovery_settings_populated(conn):
        sync_settings_from_config(conn, cfg)
    if websites_row_count(conn) == 0:
        sync_websites_from_config(conn, cfg)


def _handler_cfg_from_website_row(
    row: sqlite3.Row,
    *,
    prefs_raw: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (handler_cfg, preferences) from a websites row."""
    key = str(row["source_key"])
    raw = row["config_json"] or "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("websites %s: invalid config_json, using empty dict", key)
        body = {}
    if not isinstance(body, dict):
        body = {}
    body.pop("preferences", None)
    sc: dict[str, Any] = dict(body)
    sc["type"] = str(row["type"] or "").strip()
    sc["enabled"] = True
    sl = row["source_label"]
    if sl is not None and str(sl).strip():
        sc["source_label"] = str(sl).strip()
    prefs = parse_website_preferences(prefs_raw)
    return sc, prefs


def fetch_website_source_for_crawl(
    conn: sqlite3.Connection, website_id: int
) -> tuple[int, str, dict[str, Any], dict[str, Any]] | None:
    """
    Load one website row for an on-demand crawl (e.g. UI re-check).
    Returns None if missing. Config always has enabled=True so the crawl runs even when
    the site is toggled off in the UI.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, source_key, type, config_json, source_label, preferences_json
        FROM websites
        WHERE id = ?
        """,
        (website_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    wid = int(row["id"])
    key = str(row["source_key"])
    sc, prefs = _handler_cfg_from_website_row(row, prefs_raw=row["preferences_json"])
    return wid, key, sc, prefs


def iter_enabled_website_sources(
    conn: sqlite3.Connection,
) -> Iterator[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    """
    Yield (website_id, source_key, handler_cfg, preferences) for enabled websites.
    handler_cfg merges config_json with type, enabled, and optional source_label.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, source_key, type, config_json, source_label, preferences_json
        FROM websites
        WHERE enabled = 1
        ORDER BY display_order ASC, source_key COLLATE NOCASE
        """
    )
    for row in cur.fetchall():
        wid = int(row["id"])
        key = str(row["source_key"])
        cfg, prefs = _handler_cfg_from_website_row(row, prefs_raw=row["preferences_json"])
        yield wid, key, cfg, prefs


def list_websites(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT w.id, w.source_key, w.enabled, w.type, w.config_json, w.source_label, w.display_order,
               w.created_at, w.updated_at, w.preferences_json,
               a.last_event_activity_at
        FROM websites w
        LEFT JOIN (
            SELECT website_id, MAX(last_seen_at) AS last_event_activity_at
            FROM discovered_events
            WHERE website_id IS NOT NULL
            GROUP BY website_id
        ) a ON a.website_id = w.id
        ORDER BY w.display_order ASC, w.source_key COLLATE NOCASE
        """
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        raw = row["config_json"] or "{}"
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg.pop("preferences", None)
        out.append(
            {
                "id": int(row["id"]),
                "source_key": str(row["source_key"]),
                "enabled": bool(row["enabled"]),
                "type": str(row["type"]),
                "config": cfg,
                "preferences": parse_website_preferences(row["preferences_json"]),
                "source_label": row["source_label"],
                "display_order": int(row["display_order"] or 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_event_activity_at": row["last_event_activity_at"],
            }
        )
    return out


_RESERVED_WEBSITE_JSON_KEYS = frozenset({"type", "enabled", "source_label", "preferences"})


def _website_config_for_storage(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip keys stored in dedicated columns so config_json stays consistent with sync_websites_from_config."""
    return {k: v for k, v in raw.items() if k not in _RESERVED_WEBSITE_JSON_KEYS}


def update_website_enabled(
    conn: sqlite3.Connection, website_id: int, enabled: bool
) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE websites SET enabled = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (1 if enabled else 0, website_id),
    )
    conn.commit()
    return cur.rowcount > 0


def patch_website(
    conn: sqlite3.Connection,
    website_id: int,
    *,
    enabled: bool | None = None,
    config: dict[str, Any] | None = None,
    site_type: str | None = None,
    source_label: str | None = None,
    preferences: dict[str, Any] | None = None,
) -> bool:
    """
    Partial update for a website row. Pass only fields to change.
    Raises ValueError if site_type is provided but empty after strip.
    """
    updates: list[str] = []
    params: list[Any] = []
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(1 if enabled else 0)
    if config is not None:
        body = _website_config_for_storage(dict(config))
        updates.append("config_json = ?")
        params.append(json.dumps(body, ensure_ascii=False))
    if preferences is not None:
        clean_prefs: dict[str, Any] = {}
        if isinstance(preferences, dict):
            for pk in WEBSITE_PREFERENCE_KEYS:
                block = preferences.get(pk)
                if isinstance(block, dict) and block:
                    clean_prefs[str(pk)] = dict(block)
        updates.append("preferences_json = ?")
        params.append(json.dumps(clean_prefs, ensure_ascii=False))
    if site_type is not None:
        st = site_type.strip()
        if not st:
            raise ValueError("type cannot be empty")
        updates.append("type = ?")
        params.append(st)
    if source_label is not None:
        sl = source_label.strip()
        updates.append("source_label = ?")
        params.append(sl if sl else None)
    if not updates:
        return False
    params.append(website_id)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE websites
        SET {", ".join(updates)}, updated_at = datetime('now')
        WHERE id = ?
        """,
        params,
    )
    conn.commit()
    return cur.rowcount > 0


def delete_website(
    conn: sqlite3.Connection,
    website_id: int,
    *,
    delete_events: bool = False,
) -> tuple[bool, int]:
    """
    Remove a website row for this account's database.

    If delete_events is True, delete discovered_events rows with this website_id first.
    If False, SQLite ON DELETE SET NULL clears website_id on remaining event rows when
    the website row is removed.

    Returns (removed_website, events_deleted_count). events_deleted_count is the number
    of rows removed from discovered_events (non-zero only when delete_events is True).
    """
    cur = conn.cursor()
    cur.execute("SELECT id FROM websites WHERE id = ?", (website_id,))
    if cur.fetchone() is None:
        return False, 0
    removed_events = 0
    if delete_events:
        cur.execute("DELETE FROM discovered_events WHERE website_id = ?", (website_id,))
        removed_events = cur.rowcount
    cur.execute("DELETE FROM websites WHERE id = ?", (website_id,))
    conn.commit()
    return True, removed_events


def reorder_websites(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Set display_order from ordered_ids (index = order). Must list every website id exactly once."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM websites")
    existing = {int(r["id"]) for r in cur.fetchall()}
    ordered_set = set(ordered_ids)
    if ordered_set != existing or len(ordered_ids) != len(existing):
        raise ValueError("ids must be a permutation of all website ids")
    for order, wid in enumerate(ordered_ids):
        cur.execute(
            """
            UPDATE websites SET display_order = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (order, wid),
        )
    conn.commit()


def sync_websites_from_config(conn: sqlite3.Connection, cfg: dict[str, Any]) -> int:
    """
    Upsert rows in websites from cfg['sources'] (YAML shape). Does not delete extra DB rows.
    Returns number of sources processed.
    """
    sources = cfg.get("sources") or {}
    if not isinstance(sources, dict):
        return 0
    order = cfg.get("source_order")
    keys_ordered: list[str] = []
    if isinstance(order, list):
        for k in order:
            if isinstance(k, str) and k in sources:
                keys_ordered.append(k)
        for k in sources:
            if k not in keys_ordered:
                keys_ordered.append(k)
    else:
        keys_ordered = list(sources.keys())

    cur = conn.cursor()
    n = 0
    for display_order, source_key in enumerate(keys_ordered):
        block = sources.get(source_key)
        if not isinstance(block, dict):
            continue
        st = str(block.get("type") or "").strip()
        if not st:
            log.warning("sync websites: skip %s (no type)", source_key)
            continue
        enabled = 1 if block.get("enabled", True) else 0
        label = block.get("source_label")
        label_s = str(label).strip() if label is not None and str(label).strip() else None
        pref_block = block.get("preferences")
        prefs_clean: dict[str, Any] = {}
        if isinstance(pref_block, dict):
            for pk in WEBSITE_PREFERENCE_KEYS:
                sub = pref_block.get(pk)
                if isinstance(sub, dict) and sub:
                    prefs_clean[str(pk)] = dict(sub)
        body = {
            k: v
            for k, v in block.items()
            if k not in ("type", "enabled", "source_label", "preferences")
        }
        config_json = json.dumps(body, ensure_ascii=False)
        preferences_json = json.dumps(prefs_clean, ensure_ascii=False)
        cur.execute(
            """
            INSERT INTO websites (
                source_key, enabled, type, config_json, source_label, display_order,
                preferences_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source_key) DO UPDATE SET
                enabled = excluded.enabled,
                type = excluded.type,
                config_json = excluded.config_json,
                source_label = excluded.source_label,
                display_order = excluded.display_order,
                preferences_json = excluded.preferences_json,
                updated_at = datetime('now')
            """,
            (source_key, enabled, st, config_json, label_s, display_order, preferences_json),
        )
        n += 1
    conn.commit()
    log.info("Synced %d website rows from config", n)
    return n


def open_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def allocate_unique_source_key(conn: sqlite3.Connection, base: str) -> str:
    """
    Return a slugified source_key based on `base` that is not already used in websites.
    Appends -2, -3, … as needed.
    """
    key = slugify_source_key(base)
    if not key:
        key = "source"
    candidate = key
    n = 2
    cur = conn.cursor()
    while True:
        cur.execute("SELECT 1 FROM websites WHERE source_key = ?", (candidate,))
        if cur.fetchone() is None:
            return candidate
        candidate = f"{key}-{n}"
        n += 1
        if n > 10_000:
            raise ValueError("Could not allocate a unique source id")


def create_website(
    conn: sqlite3.Connection,
    *,
    source_key: str,
    site_type: str,
    config: dict[str, Any],
    source_label: str | None,
    enabled: bool = False,
) -> int:
    """Insert a new website row. Raises ValueError if source_key exists."""
    key = source_key.strip()
    if not key:
        raise ValueError("Source id is required")
    st = (site_type or "").strip()
    if not st:
        raise ValueError("Source type is required")
    cur = conn.cursor()
    cur.execute("SELECT id FROM websites WHERE source_key = ?", (key,))
    if cur.fetchone() is not None:
        raise ValueError("A source with this id already exists. Choose a different id.")
    cur.execute("SELECT COALESCE(MAX(display_order), -1) + 1 AS n FROM websites")
    display_order = int(cur.fetchone()["n"])
    body = _website_config_for_storage(dict(config))
    cur.execute(
        """
        INSERT INTO websites (
            source_key, enabled, type, config_json, source_label, display_order,
            preferences_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            key,
            1 if enabled else 0,
            st,
            json.dumps(body, ensure_ascii=False),
            (source_label or "").strip() or None,
            display_order,
            "{}",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_crawl_job(
    conn: sqlite3.Connection,
    *,
    kind: str,
    website_id: int | None,
) -> int:
    """
    Insert a queued crawl job. When website_id is set, DB triggers require a matching websites row.
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO crawl_jobs (kind, website_id, status, summary_json)
        VALUES (?, ?, 'queued', '{}')
        """,
        (kind, website_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_crawl_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    event_count: int | None = None,
    error_message: str | None = None,
    summary_json: str | None = None,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        params.append(finished_at)
    if event_count is not None:
        fields.append("event_count = ?")
        params.append(event_count)
    if error_message is not None:
        fields.append("error_message = ?")
        params.append(error_message)
    if summary_json is not None:
        fields.append("summary_json = ?")
        params.append(summary_json)
    if not fields:
        return
    params.append(job_id)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE crawl_jobs SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    conn.commit()


def get_crawl_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, kind, website_id, status, created_at, started_at, finished_at,
               event_count, error_message, summary_json
        FROM crawl_jobs WHERE id = ?
        """,
        (job_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def list_crawl_jobs(conn: sqlite3.Connection, *, limit: int = 30) -> list[dict[str, Any]]:
    lim = max(1, min(limit, 200))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, kind, website_id, status, created_at, started_at, finished_at,
               event_count, error_message, summary_json
        FROM crawl_jobs
        ORDER BY id DESC
        LIMIT ?
        """,
        (lim,),
    )
    return [dict(r) for r in cur.fetchall()]


def persist_discovery(conn: sqlite3.Connection, events: list[DiscoveredEvent]) -> int:
    """Insert a discovery_runs row and upsert all events. Commits on success."""
    compact_series_duplicates(conn)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.cursor()
    cur.execute("INSERT INTO discovery_runs (started_at) VALUES (?)", (started,))
    run_id = cur.lastrowid
    assert run_id is not None

    upsert_sql = """
        INSERT INTO discovered_events (
            dedupe_key, title, url, source, website_id, start_at, end_at, venue, raw_snippet,
            relevance_score, relevance_reasons_json, first_seen_at, last_seen_at, last_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dedupe_key) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            source = excluded.source,
            website_id = excluded.website_id,
            start_at = COALESCE(NULLIF(trim(excluded.start_at), ''), discovered_events.start_at),
            end_at = COALESCE(NULLIF(trim(excluded.end_at), ''), discovered_events.end_at),
            venue = COALESCE(NULLIF(trim(excluded.venue), ''), discovered_events.venue),
            raw_snippet = excluded.raw_snippet,
            relevance_score = excluded.relevance_score,
            relevance_reasons_json = excluded.relevance_reasons_json,
            first_seen_at = discovered_events.first_seen_at,
            last_seen_at = excluded.last_seen_at,
            last_run_id = excluded.last_run_id
    """

    for e in events:
        dk = e.dedupe_key()
        reasons = json.dumps(e.relevance_reasons, ensure_ascii=False)
        cur.execute(
            upsert_sql,
            (
                dk,
                e.title,
                e.url,
                e.source,
                e.website_id,
                e.start,
                e.end,
                e.venue,
                e.raw_snippet,
                e.relevance_score,
                reasons,
                started,
                started,
                run_id,
            ),
        )

    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute(
        "UPDATE discovery_runs SET finished_at = ?, event_count = ? WHERE id = ?",
        (finished, len(events), run_id),
    )
    conn.commit()
    log.info("Persisted %d events (run id %s) to SQLite", len(events), run_id)
    return int(run_id)


def export_markdown(db_path: Path, output: Path | str) -> None:
    """Write a markdown table of discovered_events. Use output='-' for stdout."""
    conn = open_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT relevance_score, start_at, title, source, url, reviewed, rejected, notes
            FROM discovered_events
            ORDER BY relevance_score DESC, title COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Discovered Burlington-area events",
        "",
        f"_Exported UTC: {gen}_",
        "",
        "Review-only. See handbook §14.",
        "",
        "| Score | Start | Title | Source | Triage | URL |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        title = (r["title"] or "").replace("|", "\\|")
        url = (r["url"] or "").replace("|", "\\|")
        start = (r["start_at"] or "")[:19]
        if r["reviewed"]:
            triage = "accepted"
        elif r["rejected"]:
            triage = "rejected"
        else:
            triage = "pending"
        lines.append(
            f"| {r['relevance_score']} | {start} | {title} | {r['source']} | {triage} | {url} |"
        )
    text = "\n".join(lines) + "\n"
    if str(output) == "-":
        sys.stdout.write(text)
    else:
        Path(output).write_text(text, encoding="utf-8")
