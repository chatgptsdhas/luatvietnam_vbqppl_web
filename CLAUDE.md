# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A system for tracking legal documents (văn bản quy phạm pháp luật) from luatvietnam.vn and syncing
review tasks into Microsoft Planner. It has three tiers that must be reasoned about together —
changes rarely stay confined to one tier:

1. **Google Apps Script backend** (`apps_script/`) — deployed as a Web App, uses a Google Sheet as
   the database. `WebApp.js` is the HTTP entry point (`doGet`/`doPost` action router),
   `Security.js` handles admin auth/session/token verification, `Module_HetHieuLuc.js` handles
   "hết hiệu lực" (expired document) status logic.
2. **Dashboard** (`Dashboard/index.html`) — a single static HTML file (no build step) that calls
   the Apps Script Web App via its public token, deployed to Vercel
   (`.vercelignore` excludes everything except `Dashboard/`).
3. **Python automation pipeline** (repo root) — Playwright-based crawler + Microsoft Graph/Planner
   sync scripts, meant to run on a schedule (Windows Task Scheduler via the `.ps1`/`.bat`/`.vbs`
   files at the root).

There is no `package.json`, no JS/TS build step, and no lockfile for Python deps — the numbered
`.py` files at the repo root are run directly with a system Python.

## Pipeline execution order

Scripts are numbered by execution order and are NOT a Python package (no imports between numbered
files except where noted). `run_luatvietnam_pipeline.ps1` runs the crawl leg (07→08→09):

- `01_save_session.py` — opens a real browser via Playwright so a human can log into
  luatvietnam.vn; saves the authenticated session to `auth/luatvietnam_state.json` (gitignored).
  Run manually first; later steps reuse this session file.
- `07_crawl_luatvietnam_list_by_field.py` — crawls document listing pages per `ma_linh_vuc`
  field in `config/scan_config.json`, writes `output/field_document_urls.json`.
- `08_process_field_documents_batch.py` — opens each URL from step 07, extracts document
  metadata, and POSTs it to the Apps Script Web App (action `import_vbqppl_nhap`) using
  `APPS_SCRIPT_SERVICE_TOKEN`. Writes `output/vbqppl_nhap_batch_payload.json`.
  **Stops immediately if `APPS_SCRIPT_SERVICE_TOKEN` is missing** — no fallback to the public token.
- `09_validate_pipeline_result.py` — cross-checks outputs of steps 07/08 against
  `config/scan_config.json` filters, writes `output/step09_validation_report.{txt,json}`.
- `10_create_planner_task_from_webapp.py` / `11_sync_webapp_to_planner.py` /
  `12_sync_planner_to_webapp.py` — bidirectional sync between the Sheet-backed Web App
  (`get_all_records` / `update_vbqppl_record` actions) and Microsoft Planner via `ms_planner.py`
  and Graph auth (`graph_auth.py`, `get_token_browser.py`, `ms_auth_init.py`).
- `13_generate_planner_reports.py` — generates CSV/report output from Planner+Sheet state into
  `output/reports/`.
- `14_notify_planner_escalation.py` — sends escalation notifications for overdue Planner tasks.

`planner_sync_server.py` is a separate long-running HTTP service (start via
`run_planner_sync_server.ps1` / the hidden-window `.bat`/`.vbs` wrappers) guarded by
`planner_sync_security.py` and `PLANNER_SYNC_SHARED_SECRET`.

## Security model (read before touching auth/token code)

`SECURITY.md`, `P0_MANUAL_ACTIONS.md`, and `P0_SECURITY_IMPLEMENTATION_REPORT.md` document a P0
hardening pass. The key invariant enforced by `tests/test_p0_static_checks.py` and CI: **two
separate tokens with different privilege levels**, and they must never be conflated again.

- `APPS_SCRIPT_TOKEN` — public, embedded directly in `Dashboard/index.html`. Only unlocks
  read-only actions (`get_pending_records`, `get_all_records`, ...). Cannot unlock any
  service/write/repair action.
- `APPS_SCRIPT_SERVICE_TOKEN` — private, required by `08_*.py`, `11_*.py`, `12_*.py` for
  action `import_vbqppl_nhap` / `update_vbqppl_record`. No fallback exists to the public token;
  Apps Script rejects with `SERVICE_TOKEN_INVALID` if the wrong token is used.
- Admin auth (`ADMIN_PASSWORD_HASH`/`ADMIN_PASSWORD_SALT`/`ADMIN_SESSION_SECRET`) lives only in
  Apps Script Script Properties, never in any `.env`.
- Secrets are generated via `scripts/generate_p0_secrets.py` and must be pasted into `.env`
  (local) or Apps Script Script Properties — never committed, never printed in full.

When editing `apps_script/WebApp.js`, `Security.js`, or `planner_sync_server.py`, keep in mind CI
statically greps for regressions (old hardcoded token/password values, `stack: err.stack` leaking
outside `appendDebugLog_`, etc.) — see `tests/test_p0_static_checks.py` for the exact assertions
before changing error-response shapes or auth helpers.

## Commands

Setup:
```
pip install -r requirements.txt
playwright install
cp .env.example .env   # then fill in secrets — see P0_MANUAL_ACTIONS.md
```

Run the full test suite (mirrors `.github/workflows/security.yml`):
```
python -m compileall -q .
node --check apps_script/WebApp.js
node --check apps_script/Security.js
python -m unittest discover -s tests -p "test_*.py" -v
node tests/test_webapp_security_boundaries.js
node tests/test_p0_script_property_management.js
python scripts/ci_secret_scan.py
```

Run a single Python test module or case:
```
python -m unittest tests.test_p0_static_checks
python -m unittest tests.test_p0_static_checks.TestWebAppJsStaticChecks.test_no_default_token_fallback
```

CI also rejects any tracked file matching secret/session/cache patterns (`.env`, `token_cache.json`,
`browser_session*.json`, `*.pem`, `*.key`, `credentials*.json`, `__pycache__/`, ...) — see the
"Reject forbidden files being tracked by Git" step in `.github/workflows/security.yml` for the
exact pattern before adding new local-state files.

Run pipeline steps individually (each expects `.env` and, for 07+, an `auth/luatvietnam_state.json`
from step 01):
```
python 07_crawl_luatvietnam_list_by_field.py
python 08_process_field_documents_batch.py
python 09_validate_pipeline_result.py
```
