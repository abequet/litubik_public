"""Chantier 17b — automated accessibility audit (axe-core) of the main pages.

Runs the built front against a throwaway server with a seeded project and
injects axe-core (frontend/node_modules/axe-core/axe.min.js) on each page:
no violation of impact "serious" or "critical" may remain, and the full
report is written to the data dir as a11y_report.json for the conformance
statement (docs/ACCESSIBILITY.md).

Skipped unless LITUBIK_A11Y=1 and the pieces are there (a built
frontend/dist, the axe bundle, a Playwright browser — Chromium, or Edge on
Windows). CI runs it in the `a11y` job.
"""
import io
import json
import os
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AXE = ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
DIST = ROOT / "frontend" / "dist" / "index.html"
PORT = int(os.environ.get("LITUBIK_A11Y_PORT", "8793"))

pytestmark = pytest.mark.skipif(
    os.environ.get("LITUBIK_A11Y") != "1" or not AXE.exists() or not DIST.exists(),
    reason="set LITUBIK_A11Y=1 with a built frontend and axe-core installed")


def _launch(pw):
    """Chromium when installed (CI), else the system Edge (Windows dev box)."""
    try:
        return pw.chromium.launch()
    except Exception:
        return pw.chromium.launch(channel="msedge")


def _seed(client) -> dict:
    """A project with an included corpus, extraction cells and a quantitative
    outcome — enough for every audited page to render its real content."""
    from openpyxl import Workbook
    client.post("/api/auth/register", json={
        "email": "a11y@example.com", "password": "password123", "display_name": "Axe"})
    pid = client.post("/api/projects", json={"name": "A11y audit"}).json()["id"]
    for name in ("Events intervention", "N intervention", "Events control", "N control"):
        client.post(f"/api/projects/{pid}/extraction/columns",
                    json={"name": name, "col_type": "number"})
    wb = Workbook()
    ws = wb.active
    ws.append(["Title", "Authors", "Year", "DOI", "Events intervention", "N intervention",
               "Events control", "N control"])
    ws.append(["Gamified speed feedback", "Martin, A.", 2021, "10.1/a", 4, 123, 11, 139])
    ws.append(["Serious games in nursing", "Rossi, C.", 2019, "10.1/b", 3, 231, 11, 220])
    ws.append(["VR exposure for anxiety", "Nguyen, D.", 2022, "10.1/c", 62, 13598, 248, 12867])
    buf = io.BytesIO()
    wb.save(buf)
    preview = client.post(f"/api/projects/{pid}/extraction/import-table/preview",
                          files={"file": ("t.xlsx", buf.getvalue())}).json()
    client.post(f"/api/projects/{pid}/extraction/import-table",
                files={"file": ("t.xlsx", buf.getvalue())},
                data={"mapping": json.dumps(preview["headers"]), "create_missing": "true"})
    api = f"/api/projects/{pid}/synthesis"
    client.put(f"{api}/plan", json={"enabled": True, "certainty_framework": "grade"})
    studies = client.get(f"{api}/eligible-records").json()["studies"]
    outcome = client.post(f"{api}/outcomes", json={
        "label": "Crash involvement", "study_ids": [s["study_id"] for s in studies]}).json()
    cols = {c["name"]: c["id"] for c in client.get(f"{api}/effects/measures").json()["columns"]}
    client.put(f"{api}/outcomes/{outcome['id']}/effects", json={
        "measure": "RR", "mapping": {
            "events_i": cols["Events intervention"], "n_i": cols["N intervention"],
            "events_c": cols["Events control"], "n_c": cols["N control"]}})
    return {"pid": pid, "cookie": client.cookies.get("litubik_session")
            or next(iter(client.cookies.values()), "")}


PAGES = [
    ("projects", "/"),
    ("protocol", "/projects/{pid}/protocol"),
    ("equations", "/projects/{pid}/equations"),
    ("search", "/projects/{pid}/search"),
    ("screening", "/projects/{pid}/screening"),
    ("extraction", "/projects/{pid}/extraction"),
    ("results", "/projects/{pid}/results"),
    ("prisma", "/projects/{pid}/prisma"),
    ("reporting", "/projects/{pid}/reporting"),
    ("integrations", "/settings/integrations"),
    ("help", "/help/10-faq"),
]


def test_main_pages_have_no_serious_axe_violation(client):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app

    seed = _seed(client)
    cookie_name = next(iter(client.cookies.keys()))
    cookie_value = client.cookies.get(cookie_name)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.5)
    base = f"http://127.0.0.1:{PORT}"
    axe_js = AXE.read_text(encoding="utf-8")
    report: dict[str, list] = {}
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            for lang in ("en", "fr"):
                # the app's CSP forbids inline scripts: the axe bundle is
                # injected with the policy bypassed (test-only)
                ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                          bypass_csp=True)
                ctx.add_cookies([{"name": cookie_name, "value": cookie_value,
                                  "domain": "127.0.0.1", "path": "/"}])
                ctx.add_init_script(
                    f"localStorage.setItem('litubik-lang','{lang}'); "
                    "localStorage.setItem('litubik-theme','light'); "
                    "localStorage.setItem('litubik-tour-seen-1','1')")
                page = ctx.new_page()
                for key, path in PAGES:
                    page.goto(base + path.format(pid=seed["pid"]))
                    page.wait_for_selector("main")
                    page.wait_for_timeout(900)
                    page.add_script_tag(content=axe_js)
                    result = page.evaluate(
                        "() => axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']}})")
                    report[f"{lang}:{key}"] = [
                        {"id": v["id"], "impact": v["impact"], "help": v["help"],
                         "helpUrl": v["helpUrl"],
                         "nodes": [{"target": n["target"], "html": n["html"][:160]}
                                   for n in v["nodes"]][:5]}
                        for v in result["violations"]]
                ctx.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    out = Path(os.environ["LITUBIK_DATA_DIR"]) / "a11y_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    blocking = {page: [v for v in items if v["impact"] in ("serious", "critical")]
                for page, items in report.items()}
    blocking = {p: v for p, v in blocking.items() if v}
    assert not blocking, json.dumps(blocking, indent=2, ensure_ascii=False)
