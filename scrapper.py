"""
Upwork Job Scraper API v7
=========================
Uses SeleniumBase UC (Undetected Chrome) mode to automatically bypass
the Cloudflare 'Verify you are human' Turnstile checkbox. 100% free.

SeleniumBase UC mode:
  - Patches Chrome at the binary level to remove all automation fingerprints
  - Has built-in uc_click() specifically for Cloudflare Turnstile
  - Works on Windows with no asyncio issues (pure sync Selenium)
"""

import asyncio
import json
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

app = FastAPI(
    title="Upwork Job Scraper v7 - SeleniumBase UC",
    description="Scrapes Upwork using SeleniumBase Undetected Chrome mode to bypass Cloudflare Turnstile for free",
    version="7.0.0",
)

executor = ThreadPoolExecutor(max_workers=2)

UPWORK_URL = (
    "https://www.upwork.com/nx/search/jobs/"
    "?category2_uid=531770282584862721&sort=recency"
)


# --------------------------------------------------------------------------- #
#  Models                                                                     #
# --------------------------------------------------------------------------- #
class JobListing(BaseModel):
    job_id: Optional[str] = None
    title: str
    url: Optional[str] = None
    posted_time: Optional[str] = None
    job_type: Optional[str] = None
    budget: Optional[str] = None
    experience_level: Optional[str] = None
    estimated_time: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    proposals: Optional[str] = None
    payment_verified: Optional[bool] = None
    client_rating: Optional[str] = None
    client_spent: Optional[str] = None
    client_location: Optional[str] = None
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ScrapeResponse(BaseModel):
    success: bool
    total_jobs: int
    jobs: List[JobListing]
    source: Optional[str] = None
    error: Optional[str] = None
    execution_time: float
    message: Optional[str] = None


class ScrapeRequest(BaseModel):
    """JSON body for POST /scrape/run — only the URL is required."""
    url: str = (
        "https://www.upwork.com/nx/search/jobs/"
        "?category2_uid=531770282584862721&sort=recency"
    )


# --------------------------------------------------------------------------- #
#  DOM extraction JS                                                            #
# --------------------------------------------------------------------------- #
DOM_JS = """
var jobs = [];
var trySelectors = [
    'article.job-tile',
    '[data-test="job-tile"]',
    'div[data-job-id]',
    'li[data-job-id]',
    'article[data-ev-label]',
    'section[data-test="job-tile"]'
];
var cards = [];
for (var i = 0; i < trySelectors.length; i++) {
    cards = Array.from(document.querySelectorAll(trySelectors[i]));
    if (cards.length > 0) break;
}
cards.forEach(function(card) {
    function g() {
        var sels = Array.from(arguments);
        for (var i = 0; i < sels.length; i++) {
            try {
                var el = card.querySelector(sels[i]);
                if (el) {
                    var t = (el.innerText || el.textContent || el.getAttribute('datetime') || '').trim();
                    if (t) return t;
                }
            } catch(e) {}
        }
        return null;
    }
    function has(sel) { try { return !!card.querySelector(sel); } catch(e) { return false; } }

    var aEl = card.querySelector('a[data-test="job-title-link"], h2 a, h3 a, [class*="job-title"] a, a[href*="/jobs/"]');
    if (!aEl) return;
    var title = (aEl.innerText || aEl.textContent || '').trim();
    if (!title) return;
    var href = aEl.getAttribute('href') || '';
    var url = href.indexOf('http') === 0 ? href : (href ? 'https://www.upwork.com' + href : null);

    // Posted time: Upwork uses data-test="job-pubilshed-date" (their typo!) on a <small> tag
    // Structure: <small data-test="job-pubilshed-date"><span>Posted</span><span>18 minutes ago</span></small>
    var posted_time = (function() {
        // Primary: Upwork's actual (typo'd) selector
        var smallEl = card.querySelector(
            'small[data-test="job-pubilshed-date"], small[data-test="job-published-date"]'
        );
        if (smallEl) {
            var spans = Array.from(smallEl.querySelectorAll('span'));
            if (spans.length >= 2) {
                return (spans[0].textContent || '').trim() + ' ' + (spans[1].textContent || '').trim();
            }
            var t = (smallEl.innerText || smallEl.textContent || '').trim();
            if (t) return t;
        }
        // Fallback: full text scan for "Posted X ago" pattern
        var allEls = Array.from(card.querySelectorAll('small, span, time'));
        for (var ei = 0; ei < allEls.length; ei++) {
            var txt = (allEls[ei].innerText || allEls[ei].textContent || '').trim();
            if (txt && /^Posted\s+/i.test(txt)) return txt;
            if (txt && /(\d+\s+(minute|hour|day|week|month)s?\s+ago)/i.test(txt)) return 'Posted ' + txt;
        }
        return null;
    })();

    // Job type + budget split
    var job_type_raw = g(
        '[data-test="job-type-label"]',
        '[data-test="is-fixed-price"]',
        'li[data-test="job-type"]',
        'span[class*="job-type"]'
    );
    var budget_raw = g(
        '[data-test="budget"]',
        '[data-test="hourly-rate"]',
        '[data-test="price-label"]',
        'li[data-test="rate"]',
        '[class*="budget"]'
    );
    var budget = budget_raw;
    var job_type = job_type_raw;
    if (!budget && job_type_raw && job_type_raw.indexOf('$') >= 0) {
        var parts = job_type_raw.split(':');
        if (parts.length >= 2) {
            budget = parts.slice(1).join(':').trim();
            job_type = parts[0].trim();
        }
    }

    var experience_level = g(
        '[data-test="experience-level"]',
        '[data-test="contractor-tier-label"]',
        'li[data-test="experience-level"]'
    );

    // Description: target the exact Upwork JobDescription container -> p
    var descEl = card.querySelector(
        '[data-test="UpCLineClamp JobDescription"] p,' +
        '[data-test="JobDescription"] p,' +
        'p.text-body-sm.rr-mask,' +
        'p.mb-0.text-body-sm'
    );
    var description = descEl ? (descEl.innerText || descEl.textContent || '').trim() : null;

    // Estimated time  e.g. "More than 6 months, 30+ hrs/week"
    var estimated_time = null;
    var durEl = card.querySelector('li[data-test="duration-label"]');
    if (durEl) {
        var strongs = Array.from(durEl.querySelectorAll('strong'));
        // Last <strong> holds the value; first one is the label "Est. time:"
        for (var di = strongs.length - 1; di >= 0; di--) {
            var dt = (strongs[di].innerText || strongs[di].textContent || '').trim();
            if (dt && dt !== 'Est. time:') { estimated_time = dt; break; }
        }
    }

    var skillEls = Array.from(card.querySelectorAll(
        '[data-test="token"], .air3-token, [data-test="skill"], [class*="skill-badge"]'
    ));
    var skills = [], seen = {};
    skillEls.forEach(function(s) {
        var t = (s.innerText || s.textContent || '').trim();
        if (t && !seen[t]) { seen[t] = 1; skills.push(t); }
    });

    var proposals = g(
        '[data-test="proposals-bid"]',
        '[data-test="proposals"]',
        'li[data-test="proposals"]',
        '[class*="proposals"]'
    );

    var payment_verified = has('[data-test="payment-verified"]') ||
                           has('[data-test="is-payment-verified"]');

    var client_rating = g(
        '[data-test="client-rating"] .air3-rating-value-text',
        '.air3-rating-value-text',
        '[data-test="rating"]',
        '[data-test="review-score"]'
    );

    var client_spent = g(
        '[data-test="client-spendings"]',
        '[data-test="total-spent"]',
        'li[data-test="client-spendings"]'
    );

    var client_location = g(
        '[data-test="client-country"]',
        '[data-test="location"]',
        '[data-test="client-location"]',
        'li[data-test="location"]'
    );

    jobs.push({
        title: title,
        url: url,
        posted_time: posted_time,
        job_type: job_type || null,
        budget: budget || null,
        experience_level: experience_level || null,
        estimated_time: estimated_time,
        description: description || null,
        skills: skills.length ? skills : null,
        proposals: proposals,
        payment_verified: payment_verified,
        client_rating: client_rating,
        client_spent: client_spent,
        client_location: client_location
    });
});
return jobs;
"""


def _extract_from_api(data) -> List[dict]:
    def find(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find(item, key)
                if r is not None:
                    return r
        return None

    raw = find(data, "jobs") or find(data, "results") or find(data, "jobPostings") or []
    if not isinstance(raw, list):
        return []

    exp_map = {
        "1": "Entry Level", "2": "Intermediate", "3": "Expert",
        "ENTRY_LEVEL": "Entry Level", "INTERMEDIATE": "Intermediate", "EXPERT_LEVEL": "Expert",
    }
    jobs = []
    for job in raw:
        if not isinstance(job, dict):
            continue
        title = (job.get("title") or job.get("jobTitle") or "").strip()
        if not title:
            continue
        job_id = job.get("id") or job.get("ciphertext") or ""
        skills = []
        for s in (job.get("skills") or job.get("ontologySkills") or []):
            n = s.get("name") or s.get("prefLabel") if isinstance(s, dict) else s
            if n:
                skills.append(n)
        client = job.get("client") or {}
        loc    = client.get("location") or {}
        hourly = job.get("hourlyBudget") or {}
        fixed  = job.get("amount") or job.get("budget") or {}
        if isinstance(hourly, dict) and (hourly.get("min") or hourly.get("max")):
            budget, jtype = "${}--{}/hr".format(hourly.get("min","?"), hourly.get("max","?")), "Hourly"
        elif isinstance(fixed, dict) and fixed.get("amount"):
            budget, jtype = "${}".format(fixed["amount"]), "Fixed price"
        else:
            budget, jtype = str(job.get("budget") or "") or None, None
        jobs.append(dict(
            title=title,
            url="https://www.upwork.com/jobs/~{}".format(job_id) if job_id else None,
            posted_time=str(job.get("publishedOn") or job.get("createTime") or "") or None,
            job_type=jtype, budget=budget,
            experience_level=exp_map.get(str(job.get("contractorTier") or job.get("experienceLevel") or "")),
            description=(job.get("description") or job.get("snippet") or "")[:500] or None,
            skills=skills or None,
            proposals=str(job.get("proposalsTier") or "") or None,
            payment_verified=client.get("paymentVerificationStatus") == "VERIFIED",
            client_rating=str(client.get("feedbackScore") or "") or None,
            client_spent=str(client.get("totalSpent") or "") or None,
            client_location=(loc.get("country") if isinstance(loc, dict) else None),
        ))
    return jobs


# --------------------------------------------------------------------------- #
#  Core scraper — SeleniumBase UC mode                                         #
# --------------------------------------------------------------------------- #
def _scrape_sync(url: str, max_pages: int) -> dict:
    print("\n" + "="*60)
    print("[INFO] Upwork Scraper v7 -- SeleniumBase UC Mode")
    print("[INFO] URL   : {}".format(url))
    print("[INFO] Pages : {}".format(max_pages))
    print("="*60)

    result = {"success": False, "jobs": [], "source": None, "error": None, "message": None}

    try:
        from seleniumbase import SB
    except ImportError:
        result["error"] = "seleniumbase not installed. Run: pip install seleniumbase"
        return result

    # SeleniumBase SB context manager with UC (Undetected Chrome) mode
    # uc=True patches Chrome to remove automation indicators
    # headless=False is REQUIRED for Cloudflare bypass
    with SB(uc=True, xvfb=True, headless=False, incognito=False) as sb:

        all_jobs: List[dict] = []
        current_url = url

        for page_num in range(1, max_pages + 1):
            print("\n[PAGE {}/{}] {}".format(page_num, max_pages, "-"*45))
            print("[INFO] Navigating to: {}".format(current_url))

            try:
                # UC mode open — patches Chrome to look like real user
                sb.uc_open_with_reconnect(current_url, reconnect_time=4)
            except Exception as e:
                print("[WARN] uc_open_with_reconnect error: {}".format(e))
                try:
                    sb.open(current_url)
                except Exception as e2:
                    print("[ERROR] open() also failed: {}".format(e2))
                    result["error"] = str(e2)
                    break

            print("[INFO] Page loaded — handling Cloudflare...")

            # --- Auto-click Cloudflare Turnstile checkbox ---
            # uc_gui_click_captcha() uses mouse GUI automation to physically
            # click the "Verify you are human" checkbox inside the CF iframe.
            # This works even with shadow DOM / sandboxed iframes.
            for cf_attempt in range(3):
                try:
                    page_source = sb.get_page_source()
                    page_title  = sb.get_title()
                    is_cloudflare = (
                        "Just a moment" in page_title
                        or "Verify you are human" in page_source
                        or "cf-turnstile" in page_source
                        or "challenge-platform" in page_source
                        or "up-challenge-container" in page_source
                    )

                    if not is_cloudflare:
                        print("[CF] No challenge detected -- good!")
                        break

                    print("[CF] Challenge detected (attempt {}) -- using uc_gui_click_captcha...".format(cf_attempt + 1))
                    time.sleep(2)

                    # PRIMARY: uc_gui_click_captcha -- moves mouse + clicks visually
                    try:
                        sb.uc_gui_click_captcha()
                        print("[CF] uc_gui_click_captcha() fired")
                        time.sleep(6)  # wait for CF JS to verify
                        # Check if passed
                        new_title = sb.get_title()
                        if "Just a moment" not in new_title:
                            print("[CF] Challenge passed!")
                            break
                    except Exception as gui_err:
                        print("[CF] uc_gui_click_captcha failed: {} -- trying uc_click fallbacks".format(gui_err))

                    # FALLBACK 1: uc_click on span.mark
                    try:
                        sb.uc_click("span.mark", timeout=5)
                        print("[CF] Clicked via span.mark")
                        time.sleep(5)
                        if "Just a moment" not in sb.get_title():
                            break
                    except Exception:
                        pass

                    # FALLBACK 2: uc_click on checkbox input
                    try:
                        sb.uc_click('input[type="checkbox"]', timeout=5)
                        print("[CF] Clicked via checkbox input")
                        time.sleep(5)
                        if "Just a moment" not in sb.get_title():
                            break
                    except Exception:
                        pass

                except Exception as cf_err:
                    print("[CF] Attempt {} error: {}".format(cf_attempt + 1, cf_err))
                    time.sleep(3)

            # Wait for job tiles to appear
            print("[INFO] Waiting for job listings to load...")
            jobs_found = False
            for sec in range(20):
                time.sleep(1)
                try:
                    title = sb.get_title()
                    # Check if jobs are visible
                    try:
                        job_count = sb.execute_script("""
                            var sels = ['article.job-tile','[data-test="job-tile"]','[data-job-id]'];
                            for (var i=0; i<sels.length; i++) {
                                if (document.querySelector(sels[i])) return true;
                            }
                            return false;
                        """)
                    except Exception:
                        job_count = False

                    still_cf = "Just a moment" in title or "Verifying" in (sb.get_page_source()[:500] if sec < 5 else "")

                    print("  [{:02d}s] jobs={} cloudflare={} title={}".format(
                        sec + 1, job_count, still_cf, title[:50]
                    ))

                    if job_count:
                        print("[INFO] Job tiles found!")
                        jobs_found = True
                        break
                    if not still_cf and sec >= 15:
                        print("[INFO] Waited 15s -- no jobs found yet, continuing anyway")
                        break
                except Exception:
                    pass

            # Dismiss cookie / tracking consent popup
            cookie_selectors = [
                "#onetrust-accept-btn-handler",
                ".air3-btn[aria-label='Close']",
                "button[aria-label='Close']",
                "[data-test='close-modal']",
            ]
            for csel in cookie_selectors:
                try:
                    if sb.is_element_visible(csel):
                        sb.click(csel)
                        print("[INFO] Cookie popup dismissed via: {}".format(csel))
                        time.sleep(1)
                        break
                except Exception:
                    pass
            # JS fallback: hide overlay
            try:
                sb.execute_script(
                    "document.querySelectorAll('#onetrust-consent-sdk,"
                    ".fe-privacy,.cookie-banner').forEach(e=>e.remove());"
                )
            except Exception:
                pass

            time.sleep(2)

            # --- Extract jobs ---
            jobs_on_page: List[dict] = []
            source = "dom"

            # Strategy 1: DOM scrape
            try:
                dom_result = sb.execute_script(DOM_JS)
                if dom_result and isinstance(dom_result, list):
                    jobs_on_page = dom_result
                    source = "dom"
                    print("[INFO] DOM -> {} jobs".format(len(dom_result)))
            except Exception as dom_err:
                print("[ERROR] DOM scrape: {}".format(dom_err))

            # Strategy 2: Page source for __NEXT_DATA__ or embedded JSON
            if not jobs_on_page:
                print("[INFO] DOM found 0 -- checking page source for embedded JSON...")
                try:
                    page_src = sb.get_page_source()
                    # Look for __NEXT_DATA__
                    import re as _re
                    m = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_src, _re.DOTALL)
                    if m:
                        nd = json.loads(m.group(1))
                        parsed = _extract_from_api(nd)
                        if parsed:
                            jobs_on_page = parsed
                            source = "next_data"
                            print("[INFO] __NEXT_DATA__ -> {} jobs".format(len(parsed)))
                except Exception as e:
                    print("[ERROR] page source parse: {}".format(e))

            if not jobs_on_page:
                try:
                    pg_title = sb.get_title()
                    pg_url   = sb.get_current_url()
                    body_snip = sb.execute_script("return document.body ? document.body.innerText.slice(0,400) : 'EMPTY'")
                    print("[DEBUG] Title: {}".format(pg_title))
                    print("[DEBUG] URL  : {}".format(pg_url))
                    print("[DEBUG] Body : {}".format(body_snip))
                except Exception:
                    pass

            valid = [j for j in jobs_on_page if isinstance(j, dict) and j.get("title")]
            all_jobs.extend(valid)
            if result["source"] is None and valid:
                result["source"] = source

            print("[INFO] Valid jobs this page : {}".format(len(valid)))
            print("[INFO] Total collected      : {}".format(len(all_jobs)))

            if not valid:
                print("[WARN] 0 jobs -- stopping pagination")
                break

            # Pagination
            if page_num < max_pages:
                clicked = False
                for sel in [
                    "[data-test='pagination-button-next']:not([disabled])",
                    "button[aria-label='Next page']:not([disabled])",
                    "a[data-test='pagination-button-next']",
                ]:
                    try:
                        if sb.is_element_present(sel) and sb.is_element_visible(sel):
                            sb.click(sel)
                            time.sleep(3)
                            clicked = True
                            print("[INFO] Next page clicked via: {}".format(sel))
                            break
                    except Exception:
                        continue
                if not clicked:
                    offset = page_num * 10
                    if "paging=" in current_url:
                        current_url = re.sub(r"paging=\d+", "paging={}".format(offset), current_url)
                    else:
                        sep = "&" if "?" in current_url else "?"
                        current_url = current_url + sep + "paging={}".format(offset)

        result["success"] = True
        result["jobs"]    = all_jobs
        if not all_jobs:
            result["message"] = "0 jobs found. Chrome opened but Cloudflare may still be blocking."
        print("\n[INFO] Done -- {} total jobs".format(len(all_jobs)))

    return result


# --------------------------------------------------------------------------- #
#  FastAPI endpoints                                                            #
# --------------------------------------------------------------------------- #
@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Upwork Job Scraper v7",
        "engine" : "SeleniumBase Undetected Chrome (UC mode)",
        "cf_solver": "Built-in uc_click() -- Free",
        "usage_get" : "GET /scrape?max_pages=3",
        "usage_post": "POST /scrape/run  (JSON body: {url, max_pages})",
    }


# ── shared helper ──────────────────────────────────────────────────────────── #
async def _run_scrape(url: str, max_pages: int) -> ScrapeResponse:
    start  = time.time()
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _scrape_sync, url, max_pages)
    elapsed = round(time.time() - start, 2)
    jobs = []
    for j in result["jobs"]:
        if not j.get("title"):
            continue
        # Extract job_id from URL: the digits after ~0 in the path
        job_id = None
        raw_url = j.get("url") or ""
        m = re.search(r'~0(\d+)', raw_url)
        if m:
            job_id = m.group(1)
        j["job_id"] = job_id
        jobs.append(JobListing(**j))
    return ScrapeResponse(
        success        = result["success"],
        total_jobs     = len(jobs),
        jobs           = jobs,
        source         = result.get("source"),
        error          = result.get("error"),
        message        = result.get("message"),
        execution_time = elapsed,
    )


@app.get("/scrape", response_model=ScrapeResponse, tags=["Scraper"])
async def scrape_jobs_get(
    url: str = UPWORK_URL,
    max_pages: int = 3,
):
    """
    Scrape Upwork jobs via **query parameters**.

    - `url` — Upwork search URL (optional, has sensible default)
    - `max_pages` — how many pages to scrape (1 page = 10 jobs)
    """
    return await _run_scrape(url, max_pages)


@app.post("/scrape/run", response_model=ScrapeResponse, tags=["Scraper"])
async def scrape_jobs_post(body: ScrapeRequest):
    """
    Scrape Upwork jobs via **JSON body**.

    Send a POST request with only the URL:
    ```json
    {
        "url": "https://www.upwork.com/nx/search/jobs/?category2_uid=531770282584862721&sort=recency"
    }
    ```
    - `url` — Upwork search URL to scrape (required)
    """
    return await _run_scrape(body.url, max_pages=1)


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
