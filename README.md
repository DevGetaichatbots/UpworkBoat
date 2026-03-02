# Upwork Job Scraper API — v7

A **FastAPI** server that scrapes live job listings from Upwork, automatically bypassing Cloudflare's **"Verify you are human"** Turnstile challenge using **SeleniumBase Undetected Chrome (UC) mode** — completely **free**, no paid services required.

---

## Table of Contents
1. [How It Works](#how-it-works)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Running the Server](#running-the-server)
5. [API Endpoints](#api-endpoints)
6. [Response Fields](#response-fields)
7. [Example Requests](#example-requests)
8. [Example Response](#example-response)
9. [Known Limitations](#known-limitations)
10. [Troubleshooting](#troubleshooting)

---

## How It Works

```
Your Request (Postman/curl)
       │
       ▼
  FastAPI Server (port 8006)
       │
       ▼
  SeleniumBase UC Mode
  (Undetected Chrome — patches Chrome binary to hide automation)
       │
       ▼
  Upwork loads → Cloudflare Turnstile appears
       │
       ▼
  uc_gui_click_captcha()  ← GUI mouse automation physically clicks the checkbox
       │
       ▼
  Jobs page loads (real DOM)
       │
       ▼
  DOM_JS extracts job cards via JavaScript
       │
       ▼
  JSON response returned to you
```

**Why SeleniumBase UC Mode?**
- Patches Chrome at binary level — no `"Chrome is controlled by automated software"` banner
- `uc_gui_click_captcha()` uses real mouse movement to click the Turnstile checkbox
- Works on Windows without asyncio issues (pure synchronous Selenium)
- 100% free — no API keys, no paid captcha services

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Google Chrome | Latest |
| OS | Windows 10/11 |

---

## Installation

### Step 1 — Create Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### Step 2 — Install Dependencies
```powershell
pip install fastapi uvicorn seleniumbase fasteners nest-asyncio mycdp beautifulsoup4 cssselect rich
```

### Step 3 — Verify SeleniumBase
```powershell
python -c "from seleniumbase import SB; print('OK')"
```

---

## Running the Server

```powershell
# Activate virtual environment first
.\venv\Scripts\activate

# Start the server
python -m uvicorn scrapper:app --host 0.0.0.0 --port 8006
```

The server starts at: **http://localhost:8006**

> ⚠️ **Important:** Run only ONE server at a time. If you get `[Errno 10048] address already in use`, kill the existing process:
> ```powershell
> Get-Process -Name "python" | Stop-Process -Force
> ```

---

## API Endpoints

### `GET /` — Health Check
Returns server info.

```
GET http://localhost:8006/
```

### `GET /scrape` — Scrape Jobs *(Main Endpoint)*

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | Upwork Accounting & Consulting | The Upwork search URL to scrape |
| `max_pages` | int | `3` | Number of pages to scrape (1 page = 10 jobs) |

```
GET http://localhost:8006/scrape?max_pages=3
```

Custom URL:
```
GET http://localhost:8006/scrape?url=https://www.upwork.com/nx/search/jobs/?q=python&sort=recency&max_pages=2
```

### `POST /scrape` — Same as GET

```
POST http://localhost:8006/scrape?max_pages=1
```

---

## Response Fields

```json
{
  "success": true,
  "total_jobs": 10,
  "jobs": [...],
  "source": "dom",
  "error": null,
  "execution_time": 59.1,
  "message": null
}
```

### Job Object Fields

| Field | Type | Available? | Description |
|---|---|---|---|
| `title` | string | ✅ Always | Job title |
| `url` | string | ✅ Always | Full URL to the job posting |
| `job_type` | string | ✅ Always | `"Hourly"` or `"Fixed price"` |
| `budget` | string | ✅ When shown | e.g. `"$10.00 - $20.00"` or `"$500"` |
| `experience_level` | string | ✅ Always | `"Entry Level"`, `"Intermediate"`, `"Expert"` |
| `description` | string | ✅ Always | First 500 chars of job description |
| `skills` | array | ✅ Always | List of required skills |
| `posted_time` | string | ✅ Most cards | e.g. `"Posted 25 minutes ago"` |
| `payment_verified` | boolean | ✅ Always | Whether client's payment is verified |
| `proposals` | string | ❌ Login required | Number of proposals — hidden by Upwork for visitors |
| `client_rating` | string | ❌ Login required | Client star rating — hidden for visitors |
| `client_spent` | string | ❌ Login required | Total client spend — hidden for visitors |
| `client_location` | string | ❌ Login required | Client country — hidden for visitors |

> **Note:** `proposals`, `client_rating`, `client_spent`, `client_location` are intentionally hidden by Upwork on search result pages for non-logged-in users. These fields would require logging in and visiting each individual job page separately.

---

## Example Requests

### PowerShell
```powershell
Invoke-RestMethod -Uri "http://localhost:8006/scrape?max_pages=1" -TimeoutSec 180 | ConvertTo-Json -Depth 5
```

### Postman
```
Method: GET
URL: http://localhost:8006/scrape?max_pages=3
```

### curl (Linux/Mac)
```bash
curl "http://localhost:8006/scrape?max_pages=1"
```

### Python
```python
import requests
response = requests.get("http://localhost:8006/scrape", params={"max_pages": 2}, timeout=180)
data = response.json()
print(f"Found {data['total_jobs']} jobs in {data['execution_time']}s")
for job in data['jobs']:
    print(f"  - {job['title']} | {job['job_type']} | {job['budget']}")
```

---

## Example Response

```json
{
    "success": true,
    "total_jobs": 10,
    "jobs": [
        {
            "title": "Experienced US Bookkeeper Needed for QuickBooks Online Management",
            "url": "https://www.upwork.com/jobs/Experienced-Bookkeeper-...",
            "posted_time": "Posted 25 minutes ago",
            "job_type": "Hourly",
            "budget": "$10.00 - $20.00",
            "experience_level": "Intermediate",
            "description": "We are seeking a detail-oriented US-based bookkeeper...",
            "skills": ["Bookkeeping", "Intuit QuickBooks", "Bank Reconciliation", "Accounting"],
            "proposals": null,
            "payment_verified": false,
            "client_rating": null,
            "client_spent": null,
            "client_location": null
        }
    ],
    "source": "dom",
    "error": null,
    "execution_time": 59.1,
    "message": null
}
```

---

## Known Limitations

| Issue | Reason |
|---|---|
| ~50–120 seconds per request | A real Chrome browser must open, load the page, solve Cloudflare, and render JS |
| Cloudflare may still block sometimes | Your IP (`125.209.76.106`) may be flagged on bad days — retry after a few minutes |
| Max 2 simultaneous requests | Server uses a 2-worker thread pool (`ThreadPoolExecutor(max_workers=2)`) |
| `proposals`, `client_*` always null | Upwork hides these from non-logged-in visitors on search pages |
| Chrome must be installed | SeleniumBase UC mode requires Google Chrome on the system |

---

## Troubleshooting

### Port Already in Use
```powershell
# Kill all Python processes and restart
Get-Process -Name "python" | Stop-Process -Force
python -m uvicorn scrapper:app --host 0.0.0.0 --port 8006
```

### Cloudflare Not Bypassing
- Chrome window will open automatically — **do not click anything**, let SeleniumBase handle it
- If it fails 3 times: wait 5 minutes and retry (IP cooldown)

### `ModuleNotFoundError: No module named 'seleniumbase'`
```powershell
.\venv\Scripts\activate
pip install seleniumbase fasteners nest-asyncio mycdp
```

### 0 Jobs Returned
- Upwork may require login for this category at peak times
- Try a different/simpler search URL:
  ```
  GET /scrape?url=https://www.upwork.com/nx/search/jobs/?q=python&sort=recency&max_pages=1
  ```

---

## File Structure

```
New folder/
├── scrapper.py       ← Main FastAPI + SeleniumBase scraper
├── patch_dom.py      ← Utility: patches DOM_JS selectors
├── venv/             ← Python virtual environment
└── README.md         ← This documentation
```

---

## Swagger UI (Auto-generated Docs)

FastAPI provides interactive API docs automatically:

```
http://localhost:8006/docs
```

Open this in your browser while the server is running to test the API visually.
