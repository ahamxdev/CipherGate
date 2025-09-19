# services/domain_store.py
"""
JSON-backed domain store (categorized):
  domains:
    management: [ ... ]
    subscription: [ ... ]
    countries:
      NL: [ ... ]
      US: [ ... ]

Provides:
 - load_domains()
 - save_domains()
 - list_all_domains()           # flat list across all sections
 - list_by_section(section)     # 'management'|'subscription'
 - list_countries()             # list of country codes available
 - list_by_country(code)
 - find_domain(name)            # search across all places
 - add_domain(section, ...)     # section='management'|'subscription'|'countries'
 - remove_domain(name)          # removes all occurrences
 - update_domain(name, **fields)
 - touch_last_check(name, status, details)
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from filelock import FileLock, Timeout
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DOMAINS_FILE = ROOT / "domains.json"
LOCK_FILE = ROOT / "domains.json.lock"
LOCK_TIMEOUT = 5  # seconds

DEFAULT_SCHEMA = {"domains": {"management": [], "subscription": [], "countries": {}}}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_file_exists():
    if not DOMAINS_FILE.exists():
        DOMAINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DOMAINS_FILE.write_text(json.dumps(DEFAULT_SCHEMA, indent=2, ensure_ascii=False))


def load_domains() -> Dict[str, Any]:
    """Load the whole JSON structure safely."""
    _ensure_file_exists()
    lock = FileLock(str(LOCK_FILE))
    try:
        with lock.acquire(timeout=LOCK_TIMEOUT):
            with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # normalize structure
                if "domains" not in data:
                    return DEFAULT_SCHEMA.copy()
                dom = data["domains"]
                # ensure keys exist
                dom.setdefault("management", [])
                dom.setdefault("subscription", [])
                dom.setdefault("countries", {})
                return {"domains": dom}
    except Timeout:
        raise RuntimeError("Could not acquire file lock to read domains.json")


def save_domains(struct: Dict[str, Any]):
    """Atomically save the whole structure."""
    _ensure_file_exists()
    lock = FileLock(str(LOCK_FILE))
    try:
        with lock.acquire(timeout=LOCK_TIMEOUT):
            tmp = DOMAINS_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(struct, f, indent=2, ensure_ascii=False)
                f.flush()
            tmp.replace(DOMAINS_FILE)
    except Timeout:
        raise RuntimeError("Could not acquire file lock to write domains.json")


# ---- listing helpers ----
def list_all_domains() -> List[Dict[str, Any]]:
    """Return flat list of all domain objects (deduplicated by name, first seen wins)."""
    data = load_domains()["domains"]
    seen = set()
    out = []
    # management
    for d in data.get("management", []):
        name = d.get("name")
        if name and name not in seen:
            out.append(d)
            seen.add(name)
    # subscription
    for d in data.get("subscription", []):
        name = d.get("name")
        if name and name not in seen:
            out.append(d)
            seen.add(name)
    # countries (each country list)
    for country_list in data.get("countries", {}).values():
        for d in country_list:
            name = d.get("name")
            if name and name not in seen:
                out.append(d)
                seen.add(name)
    return out


def list_by_section(section: str) -> List[Dict[str, Any]]:
    s = section.lower()
    data = load_domains()["domains"]
    if s in ("management", "subscription"):
        return data.get(s, [])
    raise ValueError("Invalid section. Use 'management' or 'subscription'.")


def list_countries() -> List[str]:
    data = load_domains()["domains"]
    return list(data.get("countries", {}).keys())


def list_by_country(code: str) -> List[Dict[str, Any]]:
    data = load_domains()["domains"]
    return data.get("countries", {}).get(code, [])


# ---- find/add/remove/update ----
def find_domain(name: str) -> Optional[Dict[str, Any]]:
    """Search across all sections and countries, return first match."""
    for d in list_all_domains():
        if d.get("name") == name:
            return d
    return None


def _ensure_domain_entry(name: str, label: Optional[str], purpose: str,
                         check_interval_minutes: int, notify_admins: bool, notes: str) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label or name,
        "purpose": purpose,
        "check_interval_minutes": int(check_interval_minutes),
        "notify_admins": bool(notify_admins),
        "last_checked_at": None,
        "last_status": None,
        "last_details": None,
        "notes": notes or ""
    }


def add_domain(section: str,
               name: str,
               label: Optional[str] = None,
               country: Optional[str] = None,
               purpose: str = "other",
               check_interval_minutes: int = 60,
               notify_admins: bool = True,
               notes: str = "") -> Dict[str, Any]:
    """
    Add a domain into a section.
    section: 'management', 'subscription', or 'countries'
    if section == 'countries', country must be provided (country code string)
    """
    struct = load_domains()
    data = struct["domains"]

    entry = _ensure_domain_entry(name, label, purpose, check_interval_minutes, notify_admins, notes)

    s = section.lower()
    if s in ("management", "subscription"):
        # check duplicate in this list
        if any(d.get("name") == name for d in data.get(s, [])):
            raise ValueError(f"Domain {name} already exists in {s}")
        data[s].append(entry)
    elif s == "countries":
        if not country:
            raise ValueError("country code required when adding to 'countries' section")
        country = country.upper()
        cdict = data.setdefault("countries", {})
        lst = cdict.setdefault(country, [])
        if any(d.get("name") == name for d in lst):
            raise ValueError(f"Domain {name} already exists in countries.{country}")
        lst.append(entry)
    else:
        raise ValueError("Invalid section. Use 'management','subscription' or 'countries'")

    save_domains(struct)
    return entry


def remove_domain(name: str) -> int:
    """
    Remove occurrences of `name` across all sections.
    Returns number of removals.
    """
    struct = load_domains()
    data = struct["domains"]
    removed = 0

    # management
    m = data.get("management", [])
    new_m = [d for d in m if d.get("name") != name]
    removed += len(m) - len(new_m)
    data["management"] = new_m

    # subscription
    s = data.get("subscription", [])
    new_s = [d for d in s if d.get("name") != name]
    removed += len(s) - len(new_s)
    data["subscription"] = new_s

    # countries
    countries = data.get("countries", {})
    for code, lst in list(countries.items()):
        new_lst = [d for d in lst if d.get("name") != name]
        removed += len(lst) - len(new_lst)
        if new_lst:
            countries[code] = new_lst
        else:
            # keep empty list or remove key? remove key for cleanliness
            countries.pop(code, None)
    data["countries"] = countries

    if removed > 0:
        save_domains(struct)
    return removed


def update_domain(name: str, **fields) -> Optional[Dict[str, Any]]:
    """
    Update first found domain (search order: management, subscription, countries).
    fields allowed: label, purpose, check_interval_minutes, notify_admins, notes
    """
    struct = load_domains()
    data = struct["domains"]

    def _update_in_list(lst):
        for i, d in enumerate(lst):
            if d.get("name") == name:
                for k, v in fields.items():
                    if k in d:
                        d[k] = v
                lst[i] = d
                return d
        return None

    for place in ("management", "subscription"):
        res = _update_in_list(data.get(place, []))
        if res:
            save_domains(struct)
            return res

    # countries
    for code, lst in data.get("countries", {}).items():
        res = _update_in_list(lst)
        if res:
            save_domains(struct)
            return res

    return None


def touch_last_check(name: str, status: str, details: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Update last_checked_at/status/details for all occurrences of name and save."""
    struct = load_domains()
    data = struct["domains"]
    updated = None
    now = _now_iso()

    def _touch(lst):
        nonlocal updated
        for i, d in enumerate(lst):
            if d.get("name") == name:
                d["last_checked_at"] = now
                d["last_status"] = status
                if details is not None:
                    d["last_details"] = details
                lst[i] = d
                updated = d

    _touch(data.get("management", []))
    _touch(data.get("subscription", []))
    for lst in data.get("countries", {}).values():
        _touch(lst)

    if updated is not None:
        save_domains(struct)
    return updated
