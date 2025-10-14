"""
services/domain_checker.py

Async-friendly domain monitoring using a JSON-backed domain store.

Features:
- Query domain A records against a public resolver (Google 8.8.8.8) and an Iranian resolver (5.200.200.200).
- Analyze results and decide: "ok", "filtered", "inconclusive", "error".
- Persist last check status into domain_store.touch_last_check(...)
- Notify admins (settings.ADMINS) via aiogram.Bot when a domain is detected as filtered.
- periodic_worker(bot) runs forever and checks domains according to each domain's check_interval_minutes.
- safe concurrency (Semaphore) + ThreadPoolExecutor for blocking dnspython calls.

Usage:
- import and call asyncio.create_task(periodic_worker(bot)) when your bot starts,
  or call run_cycle(bot) to run a single full cycle.

Prereqs: pip install dnspython
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, Optional, List

import dns.resolver
import dns.exception
from aiogram import Bot

from services.domain_store import list_all_domains, touch_last_check
from utils.logger import logger        # optional; implement logger (loguru recommended)
from utils.config import settings     # expects settings.ADMINS (list of ints/strings)

# Constants
IR_DNS = "5.200.200.200"   # Iranian resolver to check against
PUBLIC_DNS = "8.8.8.8"     # Public resolver (Google)
DNS_TIMEOUT = 4.0          # per-query timeout seconds
MAX_CONCURRENCY = 6        # limit concurrent DNS checks
THREADPOOL_MAX = 10       # max workers for blocking DNS calls

# Thread executor and semaphore (module-level)
_executor = ThreadPoolExecutor(max_workers=THREADPOOL_MAX)
_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)


# ----------------------
# Blocking DNS query
# ----------------------
def _query_dns_blocking(domain: str, nameserver: str, timeout: float = DNS_TIMEOUT) -> Dict[str, Any]:
    """
    Blocking function that queries A records for `domain` using `nameserver`.
    Returns a dict with keys: answers (list), rcode (0 or textual), error (string or None).
    """
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [nameserver]
    resolver.timeout = timeout
    resolver.lifetime = timeout
    out: Dict[str, Any] = {"answers": [], "rcode": None, "error": None}
    try:
        answers = resolver.resolve(domain, "A")
        out["answers"] = [a.to_text() for a in answers]
        out["rcode"] = 0
    except dns.resolver.NXDOMAIN:
        out["rcode"] = "NXDOMAIN"
    except dns.resolver.NoAnswer:
        out["rcode"] = "NO_ANSWER"
    except dns.resolver.Timeout:
        out["error"] = "TIMEOUT"
    except dns.exception.DNSException as e:
        out["error"] = str(e)
    return out


async def query_dns(domain: str, nameserver: str, timeout: float = DNS_TIMEOUT) -> Dict[str, Any]:
    """
    Async wrapper for _query_dns_blocking using ThreadPoolExecutor.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _query_dns_blocking, domain, nameserver, timeout)


# ----------------------
# Analysis logic
# ----------------------
def analyze_results(public: Dict[str, Any], iran: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Compare public vs iran resolver responses and return:
      - "ok"           : public and iran answers match (sets equal)
      - "filtered"     : public has answers but iran lacks them or differs
      - "inconclusive" : public has no answers (or both no-answer/timeouts)
      - "error"        : both sides have errors
    Returns (result, details)
    """
    details = {"public": public, "iran": iran}
    pub_ans = public.get("answers") or []
    iran_ans = iran.get("answers") or []

    # both sides errors -> error
    if public.get("error") and iran.get("error"):
        return "error", details

    # if public has answers
    if pub_ans:
        # iran has answers too
        if iran_ans:
            # exact set equality -> ok
            if set(pub_ans) == set(iran_ans):
                return "ok", details
            # different IPs -> likely filtered / redirected
            return "filtered", details
        else:
            # public answered, iran didn't -> filtered
            return "filtered", details
    else:
        # public has no answers => inconclusive (can't decide)
        return "inconclusive", details


# ----------------------
# Helper: should we check now?
# ----------------------
def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        # Python 3.11+: fromisoformat supports Z? ensure UTC handling
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%f%z")
        except Exception:
            return None


def _should_check(domain_entry: Dict[str, Any]) -> bool:
    """
    Decide whether this domain should be checked now based on its check_interval_minutes
    and last_checked_at. Returns True if never checked or interval elapsed.
    """
    interval = int(domain_entry.get("check_interval_minutes") or 60)
    last_iso = domain_entry.get("last_checked_at")
    last_dt = _parse_iso(last_iso)
    if not last_dt:
        return True
    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()
    return elapsed >= (interval * 60)


# ----------------------
# Single domain check
# ----------------------
async def check_domain_entry(domain_entry: Dict[str, Any], bot: Optional[Bot] = None):
    """
    Check a single domain entry:
      - query public and iran DNS
      - analyze
      - persist status with touch_last_check
      - notify admins if filtered and notify_admins True
    """
    name = domain_entry.get("name")
    if not name:
        return

    async with _semaphore:
        try:
            # Run both queries concurrently (they each use threadpool)
            task_public = asyncio.create_task(query_dns(name, PUBLIC_DNS))
            task_iran = asyncio.create_task(query_dns(name, IR_DNS))
            public, iran = await asyncio.gather(task_public, task_iran)

            result, details = analyze_results(public, iran)

            # Persist status into JSON store
            try:
                touch_last_check(name, result, details)
            except Exception:
                logger.exception("Failed to touch_last_check for %s", name)

            # Notify admins if filtered
            if result == "filtered" and domain_entry.get("notify_admins", True):
                text = (
                    f"⚠️ Domain *{name}* appears FILTERED.\n\n"
                    f"Public answers: {public.get('answers')}\n"
                    f"Iran answers: {iran.get('answers') or iran.get('rcode') or iran.get('error')}\n"
                    f"Check time: {datetime.now(timezone.utc).isoformat()}"
                )
                # settings.ADMINS expected to be iterable of ids (int or str)
                admins = getattr(settings, "ADMINS", []) or []
                if bot:
                    for admin in admins:
                        try:
                            await bot.send_message(int(admin), text, parse_mode="Markdown")
                        except Exception:
                            logger.exception("Failed to notify admin %s about domain %s", admin, name)
                else:
                    # Bot not provided — log as fallback
                    logger.warning("Bot not provided: filtered domain %s — admins: %s", name, admins)

        except Exception as ex:
            logger.exception("Exception while checking domain %s: %s", name, ex)


# ----------------------
# Run a single full cycle (checks all domains but respects per-domain intervals)
# ----------------------
async def run_cycle(bot: Optional[Bot] = None, concurrency_limit: Optional[int] = None):
    """
    Run one checking cycle over all domains (using list_all_domains()).
    Only domains where _should_check(...) is True will be queried.
    """
    if concurrency_limit:
        global _semaphore
        _semaphore = asyncio.Semaphore(concurrency_limit)

    domains = list_all_domains()
    if not domains:
        logger.info("domain_checker: no domains to check")
        return

    tasks: List[asyncio.Task] = []
    for d in domains:
        try:
            if _should_check(d):
                tasks.append(asyncio.create_task(check_domain_entry(d, bot=bot)))
        except Exception:
            logger.exception("Failed to schedule check for domain entry: %s", d.get("name"))

    if tasks:
        # gather and swallow exceptions individually
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.exception("domain check task raised: %s", r)


# ----------------------
# Periodic worker
# ----------------------
async def periodic_worker(bot: Optional[Bot] = None, default_interval_minutes: int = 60):
    """
    Continuous worker that:
      - runs run_cycle()
      - sleeps default_interval_minutes between cycles
    Note: Each domain has its own check_interval_minutes; run_cycle will honor them.
    Start this at bot startup:
      asyncio.create_task(periodic_worker(bot))
    or run it as a separate process.
    """
    logger.info("domain_checker: periodic worker starting (default interval %s minutes)", default_interval_minutes)
    try:
        while True:
            try:
                await run_cycle(bot=bot)
            except Exception:
                logger.exception("domain_checker: run_cycle failed")
            await asyncio.sleep(default_interval_minutes * 60)
    except asyncio.CancelledError:
        logger.info("domain_checker: worker cancelled, exiting")
        raise
    except Exception:
        logger.exception("domain_checker: unexpected exception in worker")


# ----------------------
# Convenience: synchronous starter for debugging (not used in production)
# ----------------------
def start_blocking_worker(loop: asyncio.AbstractEventLoop, bot: Optional[Bot] = None, interval_minutes: int = 60):
    """
    For quick local debug: run periodic_worker in the provided loop.
    """
    asyncio.set_event_loop(loop)
    loop.create_task(periodic_worker(bot=bot, default_interval_minutes=interval_minutes))
    loop.run_forever()
