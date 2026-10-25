# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Batch downloader d'articles scientifiques par DOI.

Provenance : repris de DOIbatchDownloader, outil antérieur du même auteur, et
adapté pour LitUbik ; distribué sous la licence de LitUbik (voir NOTICE).

Pipeline : CrossRef -> Unpaywall -> PMC/EuropePMC -> Publisher OA
           -> Playwright (OA bot-protégé) -> Institutions (EZProxy).

Un module d'extension local optionnel (`private/`, hors de cette distribution)
peut ajouter des tiers ou régler le navigateur ; il est chargé paresseusement par
`_private()` et son absence est le cas normal.
"""
import subprocess
import sys

_REQUIRED = {
    "requests": "requests",
    "bs4": "beautifulsoup4",
}

def _ensure_dependencies():
    missing = []
    for module, package in _REQUIRED.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if not missing:
        return
    # L4: never run `pip install` from a server worker at import time (network
    # fetch + arbitrary code execution from a package). The hosted image ships
    # these deps pre-installed; auto-install stays opt-in for the standalone
    # desktop tool via LITUBIK_FULLTEXT_AUTOINSTALL=1.
    import os
    if os.environ.get("LITUBIK_FULLTEXT_AUTOINSTALL") == "1":
        print(f"[auto-install] Librairies manquantes : {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("[auto-install] Installation terminée.")
    else:
        print(f"[doibatch] Dépendances manquantes ({', '.join(missing)}) — "
              "installez-les ou activez LITUBIK_FULLTEXT_AUTOINSTALL=1")

_ensure_dependencies()

import json
import os
import re
import unicodedata
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.core import polite

# --- SSRF guard (injected by the server wrapper) -----------------------------
# The standalone desktop tool navigates any URL. Run inside the hosted server,
# downloader.py sets `_url_guard` to app.core.ssrf.validate_public_url, which
# raises on a URL resolving to a private/internal address. Every navigation to
# a user-supplied host (an EZProxy entry point) is gated by it.
_url_guard = None


def _url_allowed(url: str) -> bool:
    if _url_guard is None:
        return True
    try:
        _url_guard(url)
        return True
    except Exception:
        return False


# --- Extension locale optionnelle --------------------------------------------
# `private/` ne fait pas partie de cette distribution et n'est référencé nulle
# part ailleurs qu'ici. Import paresseux (et non au chargement du module) pour
# deux raisons : casser le cycle extension -> `doibatch`, et ne rien initialiser
# tant qu'aucun appel ne le demande.
_EXTENSION_UNSET = object()
_extension = _EXTENSION_UNSET


def _private():
    """Renvoie le module d'extension local, ou None s'il n'est pas installé."""
    global _extension
    if _extension is _EXTENSION_UNSET:
        try:
            from . import private as ext
        except ImportError:
            ext = None
        _extension = ext
    return _extension


# --- Configuration -----------------------------------------------------------
# UA poli pour les APIs (CrossRef) : `polite.user_agent()`, avec l'adresse de
# contact de l'instance quand elle est configurée, sans adresse sinon
# UA navigateur pour les téléchargements PDF (certains éditeurs bloquent les bots)
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
TIMEOUT_SHORT = 15
TIMEOUT_LONG = 90

# --- Accès institutionnel (EZProxy) ------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "institutions.json")
PROXIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.json")

# Cache en mémoire des mots de passe non persistés (saisis pour la session uniquement).
# Clé : nom d'institution ; valeur : password. Effacé au redémarrage du serveur.
_SESSION_PASSWORDS: dict[str, str] = {}

def load_institutions() -> list[dict]:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("institutions", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_institutions(institutions: list[dict]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"institutions": institutions}, f, ensure_ascii=False, indent=2)


# --- Utilitaires -------------------------------------------------------------
def normalize_doi(raw: str) -> str:
    """Enlève les préfixes courants et nettoie le DOI."""
    s = raw.strip()
    s = re.sub(r"^(doi:\s*|https?://(dx\.)?doi\.org/)", "", s, flags=re.IGNORECASE)
    return s.strip().rstrip(".,;")


def sanitize_filename(s: str) -> str:
    """Translittération ASCII + suppression caractères interdits."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "untitled"


def clean_title(title: str) -> str:
    """Nettoie un titre CrossRef (HTML, balises JATS, espaces)."""
    # Retire les balises JATS XML que CrossRef laisse parfois passer
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def build_filename(meta: dict) -> str:
    """premier_auteur_annee_4_premiers_mots.pdf"""
    author = sanitize_filename(meta["first_author"])
    year = meta["year"] or "ND"
    words = re.findall(r"\w+", meta["title"])[:4]
    title_part = sanitize_filename("_".join(words)) if words else "untitled"
    return f"{author}_{year}_{title_part}.pdf"


def is_pdf_response(resp: requests.Response) -> bool:
    """Vérifie qu'on a bien un PDF, pas une page HTML déguisée."""
    ctype = resp.headers.get("Content-Type", "").lower()
    if "pdf" in ctype:
        return True
    # Magic bytes : %PDF
    return resp.content[:4] == b"%PDF"


# --- Étape 1 : CrossRef ------------------------------------------------------
def fetch_crossref(doi: str) -> dict | None:
    """Récupère auteur / année / titre depuis l'API CrossRef."""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(url, headers=polite.headers(), timeout=TIMEOUT_SHORT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        msg = r.json().get("message", {})
    except Exception:
        return None

    # Auteur : priorité au premier auteur ayant un "family"
    first_author = "Anonymous"
    for a in msg.get("author", []) or []:
        if a.get("family"):
            first_author = a["family"]
            break
        if a.get("name"):  # auteur institutionnel
            first_author = a["name"]
            break

    # Année : essaie published > issued > created
    year = None
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = msg.get(key, {}).get("date-parts") if isinstance(msg.get(key), dict) else None
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break

    title_list = msg.get("title") or ["untitled"]
    title = clean_title(title_list[0]) if title_list else "untitled"

    return {"first_author": first_author, "year": year, "title": title}


_PMC_RE = re.compile(r"pmc/articles/(?:PMC)?(\d+)", re.IGNORECASE)


def _extract_pmc_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _PMC_RE.search(url)
    return m.group(1) if m else None


# --- Étape 2 : Unpaywall -----------------------------------------------------
def fetch_unpaywall_pdf(doi: str, email: str) -> tuple[bytes | None, str | None, list[str]]:
    """
    Tente de télécharger le PDF OA via Unpaywall.
    Retourne (pdf_bytes, oa_landing_url, pmc_ids) :
    - oa_landing_url : URL éditeur pour fallback manuel (renseigné même si échec).
    - pmc_ids : liste des PMC IDs trouvés dans les oa_locations (sert à l'étape PMC).
    """
    url = f"https://api.unpaywall.org/v2/{doi}"
    try:
        r = requests.get(url, params={"email": email}, timeout=TIMEOUT_SHORT)
        if r.status_code != 200:
            return None, None, []
        data = r.json()
    except Exception:
        return None, None, []

    # URL de la page éditeur pour le fallback manuel
    best = data.get("best_oa_location") or {}
    oa_landing: str | None = best.get("url_for_landing_page") or best.get("url") or None

    # best_oa_location en priorité, puis on parcourt oa_locations
    candidates = []
    if data.get("best_oa_location"):
        candidates.append(data["best_oa_location"])
    candidates.extend(data.get("oa_locations") or [])

    # Extraction des PMC IDs (pour l'étape PMC en cas d'échec direct)
    pmc_ids: list[str] = []
    for loc in candidates:
        if not loc:
            continue
        pid = _extract_pmc_id(loc.get("url") or loc.get("url_for_pdf"))
        if pid and pid not in pmc_ids:
            pmc_ids.append(pid)

    seen: set[str] = set()
    for loc in candidates:
        if not loc:
            continue
        pdf_url = loc.get("url_for_pdf") or (loc.get("url") if (loc.get("url") or "").endswith(".pdf") else None)
        if not pdf_url or pdf_url in seen:
            continue
        seen.add(pdf_url)
        pdf_bytes = download_pdf(pdf_url)
        if pdf_bytes:
            return pdf_bytes, oa_landing, pmc_ids
    return None, oa_landing, pmc_ids


# --- Étape 2.5 : PMC / EuropePMC ---------------------------------------------
def fetch_pmc_pdf(doi: str, hint_pmc_ids: list[str] | None = None) -> bytes | None:
    """
    Télécharge via EuropePMC (accès ouvert, simple requête HTTP, très fiable).
    - hint_pmc_ids : PMC IDs trouvés via Unpaywall (économise un appel API).
    - Sinon : interroge le NCBI ID Converter pour résoudre le DOI en PMC ID.
    """
    pmc_ids: list[str] = list(dict.fromkeys(hint_pmc_ids or []))

    if not pmc_ids:
        try:
            r = requests.get(
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"ids": doi, "format": "json", **polite.ncbi_params()},
                timeout=TIMEOUT_SHORT,
            )
            if r.status_code == 200:
                for rec in r.json().get("records", []) or []:
                    pmcid = rec.get("pmcid")
                    if pmcid:
                        pmc_ids.append(pmcid.replace("PMC", ""))
        except Exception:
            pass

    # EuropePMC est parfois lent / saturé : on lui donne un timeout court (30s)
    # pour ne pas bloquer le pipeline parallèle quand il rate-limit.
    PMC_TIMEOUT = 30
    for pmc_id in pmc_ids:
        # EuropePMC fournit le PDF directement, sans page intermédiaire
        pdf = download_pdf(
            f"https://europepmc.org/articles/PMC{pmc_id}?pdf=render",
            referer=f"https://europepmc.org/article/PMC{pmc_id}",
            timeout=PMC_TIMEOUT,
        )
        if pdf:
            return pdf
        # Fallback : NCBI direct (parfois disponible)
        pdf = download_pdf(
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/",
            timeout=PMC_TIMEOUT,
        )
        if pdf:
            return pdf
    return None


# --- Étape 3 : Publisher OA --------------------------------------------------
def fetch_publisher_pdf(doi: str) -> tuple[bytes | None, str | None]:
    """
    Télécharge le PDF depuis le site de l'éditeur si l'article est en open access.
    Retourne (pdf_bytes, publisher_url).
    publisher_url est renseigné même en cas d'échec (403 au client HTTP) pour que
    le pipeline puisse déclencher Playwright (étape 4) sur cette URL.
    Stratégies : (1) meta citation_pdf_url, (2) liens <a> vers PDF, (3) suffixe /pdf.
    """
    publisher_url: str | None = None
    # Résolution DOI → URL éditeur
    try:
        r = requests.get(
            f"https://doi.org/{doi}",
            headers={"User-Agent": BROWSER_UA},
            timeout=TIMEOUT_SHORT,
            allow_redirects=True,
        )
        publisher_url = r.url
    except Exception:
        return None, None

    # Récupération de la page éditeur
    try:
        r = requests.get(
            publisher_url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            timeout=TIMEOUT_SHORT,
        )
        if r.status_code in (403, 429):
            # Refusé au client HTTP simple — un vrai navigateur (Playwright) pourra peut-être l'ouvrir
            return None, publisher_url
        if r.status_code != 200:
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None, publisher_url

    parsed_base = urlparse(publisher_url)
    base = f"{parsed_base.scheme}://{parsed_base.netloc}"

    def try_pdf(url: str) -> bytes | None:
        if url.startswith("//"):
            url = parsed_base.scheme + ":" + url
        elif url.startswith("/"):
            url = base + url
        elif not url.startswith("http"):
            return None
        return download_pdf(url, referer=publisher_url)

    # 1) Meta citation_pdf_url (standard Scholar — MDPI, Frontiers, PeerJ, etc.)
    meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
    if meta and meta.get("content"):
        pdf = try_pdf(meta["content"])
        if pdf:
            return pdf, publisher_url

    # 2) Liens <a> avec "pdf" dans le href ou le texte visible (bouton "Download PDF")
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        text = a.get_text(strip=True).lower()
        if not ("pdf" in href.lower() or "pdf" in text):
            continue
        if href in seen:
            continue
        seen.add(href)
        pdf = try_pdf(href)
        if pdf:
            return pdf, publisher_url

    # 3) Suffixe /pdf (MDPI, ScienceDirect OA, etc.)
    pdf = try_pdf(publisher_url.rstrip("/") + "/pdf")
    if pdf:
        return pdf, publisher_url

    return None, None


# --- Étape 4 : Playwright (OA bot-protégé) ------------------------------------
_playwright_available: bool | None = None  # None = pas encore vérifié


_playwright_error: str = ""


def _ensure_playwright() -> bool:
    """Un navigateur Playwright utilisable est-il disponible ? Testé une fois.

    Importer le paquet ne suffit pas : `pip install playwright` n'installe que
    la partie Python, le navigateur est un téléchargement séparé. L'image Docker
    a longtemps eu le paquet sans le binaire — le lancement échouait alors à
    chaque récupération, à l'intérieur d'un `except` qui l'avalait, et l'échec
    ressortait comme « aucun PDF trouvé ». On lance donc réellement un
    navigateur, et on retient pourquoi si ça ne marche pas.

    L4/§1.12 : jamais de `pip install` depuis un worker serveur — l'installation
    est documentée dans requirements.txt et faite par le Dockerfile.
    """
    global _playwright_available, _playwright_error
    if _playwright_available is not None:
        return _playwright_available
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _playwright_available = False
        _playwright_error = ("le paquet playwright n'est pas installé sur cette "
                             "instance")
        return False
    try:
        with sync_playwright() as pw:
            # même stratégie que _pw_launch : le Chrome du système d'abord
            try:
                browser = pw.chromium.launch(headless=True, channel="chrome")
            except Exception:
                browser = pw.chromium.launch(headless=True)
            browser.close()
        _playwright_available = True
    except Exception as e:
        _playwright_available = False
        _playwright_error = (
            "aucun navigateur Chromium ne démarre sur cette instance "
            f"({str(e).splitlines()[0][:120]}) — lancez "
            "`python -m playwright install chromium`")
    return _playwright_available


def playwright_unavailable_reason() -> str:
    """Pourquoi les tiers Playwright sont hors service, ou '' s'ils marchent."""
    _ensure_playwright()
    return _playwright_error


def _pw_download_pdf(page, url: str) -> bytes | None:
    """
    Récupère un PDF via Playwright en gérant tous les modes de service :
      - PDF inline (Content-Type: application/pdf) → page.request.get
      - PDF en attachment (Content-Disposition: attachment) → expect_download
      - Page intermédiaire qui exige JavaScript → la navigation JS la franchit
    Utilise la session du navigateur (cookies déjà posés par l'éditeur).
    """
    # 1) Tentative rapide : page.request.get (fonctionne pour PDF inline)
    try:
        resp = page.request.get(
            url,
            headers={"Referer": page.url or url},
            timeout=30_000,
        )
        if resp.ok:
            data = resp.body()
            if data[:4] == b"%PDF":
                return data
    except Exception:
        pass

    # 2) Fallback : déclencher download navigateur via JS-navigation.
    # page.goto crashe sur Content-Disposition:attachment, mais window.location
    # déclenche le download proprement (capturé par expect_download).
    try:
        with page.expect_download(timeout=30_000) as dl_info:
            try:
                page.evaluate("(u) => { window.location.href = u; }", url)
            except Exception:
                pass
        dl_path = dl_info.value.path()
        if dl_path:
            with open(dl_path, "rb") as f:
                data = f.read()
            if data[:4] == b"%PDF":
                return data
    except Exception:
        pass

    return None


def _pw_launch(pw, *, accept_downloads: bool = True,
               use_extensions: bool = True):
    """
    Lance un navigateur Playwright. Préfère le Chrome réellement installé
    (channel='chrome'), qui rend mieux les pages éditeur ; repli sur le Chromium
    bundlé. Retourne (browser, context).

    Une extension locale peut fournir des arguments et un script d'initialisation ;
    sinon (ou avec `use_extensions=False`) on lance un navigateur standard.
    """
    ext = _private() if use_extensions else None
    args = ext.browser_args() if ext else []
    try:
        browser = pw.chromium.launch(headless=True, channel="chrome", args=args)
    except Exception:
        browser = pw.chromium.launch(headless=True, args=args)
    ctx = browser.new_context(
        user_agent=BROWSER_UA,
        accept_downloads=accept_downloads,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,fr;q=0.8"},
    )
    init = ext.init_script() if ext else None
    if init:
        ctx.add_init_script(init)
    return browser, ctx


def fetch_playwright_pdf(doi: str, oa_url: str | None = None,
                         use_extensions: bool = True) -> bytes | None:
    """
    Fallback Chromium headless : ouvre les pages d'éditeur qui n'envoient le PDF
    qu'après exécution de JavaScript. Réservé aux articles OA dont le download
    HTTP direct échoue (403).
    oa_url : URL éditeur de départ (depuis Unpaywall ou Publisher OA bloqué).
             Si None, utilise doi.org/{doi}.
    Stratégies : (1) interception réponse PDF, (2) lien PDF + event download (ACM etc.),
                 (3) réutilisation des cookies browser dans requests.
    """
    if not _ensure_playwright():
        return None
    try:
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as _PWTimeout
    except ImportError:
        return None

    pdf_bytes: list[bytes | None] = [None]

    def _on_response(response) -> None:
        if pdf_bytes[0]:
            return
        try:
            ctype = response.headers.get("content-type", "").lower()
            if "pdf" in ctype:
                body = response.body()
                if body[:4] == b"%PDF":
                    pdf_bytes[0] = body
        except BaseException:
            pass

    start_url = oa_url or f"https://doi.org/{doi}"
    # ACM : l'URL de landing DOI est refusée au navigateur headless ;
    # l'ePDF viewer (epdf/) est accessible et contient le lien de téléchargement.
    if "dl.acm.org" in start_url and "/epdf/" not in start_url:
        start_url = f"https://dl.acm.org/doi/epdf/{doi}"

    # Si Unpaywall a renvoyé directement une URL PDF (cas MDPI, BMJ...),
    # certains éditeurs (MDPI…) servent le PDF avec Content-Disposition:attachment,
    # ce qui fait crasher page.goto. On dérive donc une landing page article et on
    # gardera l'URL PDF comme hint pour fetcher via page.request.get().
    landing_url = start_url
    pdf_hint: str | None = None
    _url_low = start_url.lower().split("?")[0]
    if _url_low.endswith(".pdf") or "/pdf" in _url_low:
        pdf_hint = start_url
        derived = re.sub(r"\.full\.pdf$", "", start_url)
        derived = re.sub(r"\.pdf(\?.*)?$", r"\1", derived)
        derived = re.sub(r"/pdf(?=[/?]|$)", "", derived)
        landing_url = derived if derived != start_url else f"https://doi.org/{doi}"

    try:
        with sync_playwright() as pw:
            browser, ctx = _pw_launch(pw, use_extensions=use_extensions)
            page = ctx.new_page()
            page.on("response", _on_response)

            # 1) Charger la landing page (JavaScript exécuté, cookies de l'éditeur posés)
            try:
                page.goto(landing_url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_load_state("networkidle", timeout=8_000)
            except _PWTimeout:
                pass
            except Exception:
                # Cas rare : la landing elle-même déclenche un download. On poursuit.
                pass

            # 1.5) Si Unpaywall a donné un url_for_pdf direct, on l'essaie tout de suite
            # avec la session déjà établie (cookies de l'éditeur).
            if pdf_hint and not pdf_bytes[0]:
                data = _pw_download_pdf(page, pdf_hint)
                if data:
                    pdf_bytes[0] = data

            if pdf_bytes[0]:
                browser.close()
                return pdf_bytes[0]

            landing_url = page.url

            # ACM fast-path : page.request utilise la session du navigateur (cookies valides)
            # ?download=true répond avec Content-Disposition:attachment → body = PDF bytes
            if "dl.acm.org" in landing_url and not pdf_bytes[0]:
                try:
                    acm_pdf_url = f"https://dl.acm.org/doi/pdf/{doi}?download=true"
                    resp = page.request.get(
                        acm_pdf_url,
                        headers={"Referer": landing_url},
                        timeout=30_000,
                    )
                    if resp.ok:
                        data = resp.body()
                        if data[:4] == b"%PDF":
                            pdf_bytes[0] = data
                except Exception:
                    pass

            if pdf_bytes[0]:
                browser.close()
                return pdf_bytes[0]

            # 2) Trouver le lien PDF sur la page chargée
            try:
                pdf_link: str | None = page.evaluate("""() => {
                    const meta = document.querySelector('meta[name="citation_pdf_url"]');
                    if (meta && meta.content) return meta.content;
                    for (const a of document.querySelectorAll('a[href]')) {
                        const h = a.href.toLowerCase();
                        const t = a.textContent.trim().toLowerCase();
                        if (h.includes('/pdf') || h.includes('download=true') || h.includes('epdf')
                            || h.includes('stamp.jsp')
                            || t === 'pdf' || t.includes('download pdf'))
                            return a.href;
                    }
                    return null;
                }""")
            except Exception:
                pdf_link = None

            # Construire la liste de candidats : lien trouvé + patterns éditeurs + suffixe /pdf
            candidates: list[str] = []
            if pdf_link:
                candidates.append(pdf_link)
            # ACM Open Access : dl.acm.org/doi/{doi} → dl.acm.org/doi/pdf/{doi}?download=true
            if "dl.acm.org" in landing_url:
                candidates.append(f"https://dl.acm.org/doi/pdf/{doi}?download=true")
            # IEEE Xplore : ieeexplore.ieee.org/document/{arnumber} → stamp/stamp.jsp
            if "ieeexplore.ieee.org" in landing_url:
                _m = re.search(r"/document/(\d+)", landing_url)
                if _m:
                    candidates.append(
                        f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={_m.group(1)}"
                    )
            candidates.append(landing_url.rstrip("/") + "/pdf")

            for target in candidates:
                if pdf_bytes[0]:
                    break
                # _pw_download_pdf gère les 3 cas : PDF inline / attachment / interstitiel
                data = _pw_download_pdf(page, target)
                if data:
                    pdf_bytes[0] = data

            # 3) Si réponse pas encore interceptée : extraire les cookies du browser
            #    et réutiliser dans requests (les tokens bot sont déjà validés)
            if not pdf_bytes[0]:
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                for url in filter(None, [pdf_link, landing_url.rstrip("/") + "/pdf"]):
                    try:
                        r = requests.get(
                            url,
                            headers={"User-Agent": BROWSER_UA, "Referer": landing_url},
                            cookies=cookies,
                            timeout=TIMEOUT_LONG,
                            allow_redirects=True,
                        )
                        if r.status_code == 200 and is_pdf_response(r):
                            pdf_bytes[0] = r.content
                            break
                    except Exception:
                        pass

            browser.close()
    except Exception:
        pass

    return pdf_bytes[0]


# --- Étape 5 : Accès institutionnel (EZProxy) --------------------------------
def _try_ezproxy(target_url: str, inst: dict, diag: list[str] | None = None
                 ) -> bytes | None:
    """Tente le téléchargement via un proxy EZProxy avec login Playwright.

    `diag` recueille une raison lisible quand ça échoue. Sans elle, une
    passphrase erronée, un compte expiré, un navigateur absent et un article
    réellement indisponible produisent tous le même résultat vide, et
    l'utilisateur n'a aucun moyen de faire la différence.
    """
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as _PWTimeout

    name = inst.get("name") or "institution"

    def note(msg: str) -> None:
        if diag is not None:
            diag.append(f"{name} : {msg}")

    ezproxy_base = (inst.get("ezproxy_url") or "").strip()
    username = inst.get("username", "")
    password = inst.get("password", "")
    scope = inst.get("scope", "").strip()
    if not ezproxy_base or not username or not password:
        note("configuration incomplète (URL du proxy, identifiant ou mot de "
             "passe manquant)")
        return None

    ezproxy_entry = ezproxy_base.replace("$@", target_url) if "$@" in ezproxy_base else ezproxy_base + target_url

    # C1: never navigate a user-supplied URL that resolves to an internal host
    if not _url_allowed(ezproxy_entry):
        note("l'URL du proxy pointe vers une adresse interne — refusée")
        return None

    captured: list[bytes | None] = [None]

    def _on_resp(resp) -> None:
        if captured[0]:
            return
        try:
            ctype = resp.headers.get("content-type", "").lower()
            if "pdf" in ctype:
                body = resp.body()
                if body and body[:4] == b"%PDF":
                    captured[0] = body
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser, ctx = _pw_launch(pw)
            page = ctx.new_page()
            page.on("response", _on_resp)

            # 1) Charger l'URL EZProxy
            try:
                page.goto(ezproxy_entry, wait_until="domcontentloaded", timeout=25_000)
            except _PWTimeout:
                pass

            # Shibboleth (UCLY, etc.) : la page d'entrée est un formulaire SAML
            # auto-submitté en JS. On attend la navigation complète vers l'IdP.
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except _PWTimeout:
                pass

            if captured[0]:
                browser.close()
                return captured[0]

            # 2) Login EZProxy si formulaire présent — on attend que le champ password
            # soit là (un peu plus longuement pour les flows Shibboleth qui rebondissent).
            try:
                # BibCNRS : le formulaire « Code d'accès de votre unité » est masqué
                # (class hidden/opacity-0) derrière un toggle #bibapi_toggle. Sans ce
                # clic, on remplirait un form invisible et le 1er <button> de la page
                # serait le login Janus/RENATER → échec silencieux.
                try:
                    toggle = page.query_selector("#bibapi_toggle")
                    if toggle:
                        toggle.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass

                pwd_field = None
                try:
                    page.wait_for_selector("input[type='password']", timeout=10_000)
                    pwd_field = page.query_selector("input[type='password']")
                except _PWTimeout:
                    pass

                if pwd_field:
                    # CAS fédéré (UFTMiP…) : la page porte un <select> d'établissement.
                    # Son défaut est la ComUE, pas un établissement précis — se
                    # connecter sans le renseigner échoue. L'annuaire intégré ne
                    # fournit que {name, url}, donc quelqu'un qui choisit son
                    # institution dans la liste déroulante n'a AUCUN moyen de
                    # deviner qu'il faut aussi un « scope », ni lequel : on lui
                    # rend donc les valeurs acceptées.
                    sel_el = page.query_selector("select")
                    if sel_el:
                        options = sel_el.evaluate(
                            "s => [...s.options].map(o => o.value).filter(Boolean)")
                        allowed = ", ".join(options[:16]) or "aucune"
                        if not scope:
                            note("cette connexion demande de choisir un "
                                 f"établissement — renseignez le champ « scope » "
                                 f"avec l'une de ces valeurs : {allowed}")
                        elif scope not in options:
                            note(f"établissement « {scope} » inconnu de cette "
                                 f"page — valeurs acceptées : {allowed}")
                        else:
                            try:
                                sel_el.select_option(value=scope)
                            except Exception:
                                note(f"impossible de sélectionner l'établissement "
                                     f"« {scope} »")

                    # Couvre : EZProxy standard (user/pass), CAS (j_username, id=username),
                    # adAS (Spanish CAS — USAL identidad.usal.es), OCLC, OAuth générique.
                    user_field = (
                        page.query_selector("input[name='user']")
                        or page.query_selector("input[id='username']")
                        or page.query_selector("input[name='username']")
                        or page.query_selector("input[name='j_username']")
                        or page.query_selector("input[name='adAS_username']")
                        or page.query_selector("input[name='login']")
                        or page.query_selector("input[id='login']")
                        or page.query_selector("input[type='email']")
                        or page.query_selector("input[type='text']")
                    )
                    if user_field:
                        user_field.click()
                        user_field.fill(username)
                    pwd_field.click()
                    pwd_field.fill(password)

                    # Cherche le bouton submit DANS le formulaire du champ password
                    # (le bouton « Connexion » de BibCNRS n'a pas type=submit ; sans
                    # ce scoping on retomberait sur le 1er <button> de la page = Janus).
                    try:
                        form_el = pwd_field.evaluate_handle("el => el.form").as_element()
                    except Exception:
                        form_el = None
                    scope_q = form_el or page
                    submit = (
                        scope_q.query_selector("input[type='submit']")
                        or scope_q.query_selector("button[type='submit']")
                        or scope_q.query_selector("button")
                    )
                    if submit:
                        submit.click()
                    else:
                        pwd_field.press("Enter")

                    try:
                        page.wait_for_load_state("networkidle", timeout=20_000)
                    except _PWTimeout:
                        pass
                else:
                    note("aucun formulaire de connexion trouvé sur la page "
                         "d'entrée du proxy")
            except Exception as e:
                note(f"échec pendant la connexion ({type(e).__name__})")

            if captured[0]:
                browser.close()
                return captured[0]

            # 3) Page article : chercher l'URL du PDF
            landing_url = page.url
            _AUTH_HINTS = ("login", "/auth", "/cas", "shib", "idp", "/sso")
            still_authenticating = any(m in landing_url.lower()
                                       for m in _AUTH_HINTS)
            if still_authenticating:
                note("connexion refusée — toujours sur la page "
                     "d'authentification après envoi du formulaire")
            try:
                pdf_link: str | None = page.evaluate("""() => {
                    const m = document.querySelector('meta[name="citation_pdf_url"]');
                    if (m && m.content) return m.content;
                    const kw = ['download pdf', 'télécharger', 'descargar pdf', 'get pdf', '/pdf', 'pdfft'];
                    for (const a of document.querySelectorAll('a[href]')) {
                        const h = a.href.toLowerCase(), t = a.textContent.toLowerCase();
                        if (kw.some(k => h.includes(k) || t.includes(k))) return a.href;
                    }
                    return null;
                }""")
            except Exception:
                pdf_link = None

            if pdf_link:
                # _pw_download_pdf gère PDF inline + attachment + interstitiels
                data = _pw_download_pdf(page, pdf_link)
                if data:
                    captured[0] = data

                if not captured[0]:
                    # Fallback : cookies du navigateur (session EZProxy) + requests
                    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                    try:
                        r = requests.get(
                            pdf_link,
                            headers={"User-Agent": BROWSER_UA, "Referer": landing_url},
                            cookies=cookies,
                            timeout=TIMEOUT_LONG,
                            allow_redirects=True,
                        )
                        if r.status_code == 200 and is_pdf_response(r):
                            captured[0] = r.content
                    except Exception:
                        pass

            # Fallback page.pdf() : render HTML de la page article en PDF
            # (utilisé quand le lien PDF direct est refusé au navigateur headless, ex. ScienceDirect)
            if not captured[0]:
                cur_url = page.url
                cur_low = cur_url.lower()
                # Liste élargie des marqueurs d'URL d'auth : on évite de "capturer"
                # une page de login en PDF (UCLy/Shibboleth via id.ucly.fr, etc.)
                AUTH_MARKERS = (
                    "login", "auth", "cas", "shib", "idp", "/sso",
                    "id.ucly.fr", "identidad.usal.es", "renater", "openathens",
                )
                is_article_page = (
                    cur_url != ezproxy_entry
                    and not any(m in cur_low for m in AUTH_MARKERS)
                    # C1: refuse to render an internal page (a redirect could
                    # have landed us on a private host) into a downloadable PDF
                    and _url_allowed(cur_url)
                )
                if is_article_page:
                    try:
                        # Revenir sur la landing page article si on a navigué ailleurs
                        if page.url != landing_url:
                            page.goto(landing_url, wait_until="domcontentloaded", timeout=15_000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=8_000)
                            except _PWTimeout:
                                pass
                        pdf_data = page.pdf(format="A4", print_background=True)
                        if pdf_data[:4] == b"%PDF":
                            captured[0] = pdf_data
                    except Exception:
                        pass

            if not captured[0] and not pdf_link and not still_authenticating:
                # only meaningful once we know we got past the login: on an auth
                # page there is obviously no PDF link, and saying "article page
                # reached" there would be plainly false
                note("page article atteinte, mais aucun lien PDF trouvé "
                     "(abonnement ne couvrant pas ce titre ?)")
            browser.close()
    except Exception as e:
        note(f"échec du navigateur ({type(e).__name__}: "
             f"{str(e).splitlines()[0][:100]})")

    return captured[0]


def fetch_institutional_pdf(doi: str, institutions: list[dict],
                            diag: list[str] | None = None
                            ) -> tuple[bytes | None, str | None]:
    """Essaie chaque institution EZProxy configurée. Retourne (pdf_bytes, nom_institution)."""
    active = [i for i in institutions if i.get("username") and i.get("password") and i.get("ezproxy_url")]
    if not active:
        if diag is not None and institutions:
            diag.append("accès institutionnel : aucune institution n'a "
                        "identifiant ET mot de passe renseignés")
        return None, None
    if not _ensure_playwright():
        if diag is not None:
            diag.append(f"accès institutionnel indisponible — "
                        f"{playwright_unavailable_reason()}")
        return None, None

    target_url = f"https://doi.org/{doi}"
    for inst in active:
        pdf = _try_ezproxy(target_url, inst, diag=diag)
        if pdf:
            return pdf, inst.get("name", "Institution")
    return None, None


# --- Téléchargement PDF -----------------------------------------------------
def download_pdf(url: str, referer: str | None = None, timeout: int | None = None) -> bytes | None:
    headers = {"User-Agent": BROWSER_UA}
    if referer:
        headers["Referer"] = referer
    try:
        r = requests.get(url, headers=headers, timeout=timeout or TIMEOUT_LONG, allow_redirects=True)
        if r.status_code != 200:
            return None
        if not is_pdf_response(r):
            return None
        return r.content
    except Exception:
        return None


def _run_tier_parallel(tasks: list[tuple[str, "callable[[], object]"]]) -> tuple[bytes | None, str | None]:
    """
    Exécute plusieurs sources de PDF en parallèle (ThreadPoolExecutor).
    Retourne (pdf_bytes, source_label) dès qu'une tâche fournit un PDF.
    Les autres tâches continuent en arrière-plan (threads daemon) mais leurs
    résultats sont ignorés — c'est volontaire : la sync HTTP/Playwright ne peut
    pas être interrompue proprement, mais le gain de latence l'emporte.

    tasks : liste de (label, callable). La callable doit retourner soit `bytes`,
    soit `(bytes, extra_label)` ; un retour falsy = échec.
    """
    import concurrent.futures
    if not tasks:
        return None, None
    pdf_bytes: bytes | None = None
    winner: str | None = None
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="tier")
    futures = {ex.submit(fn): label for label, fn in tasks}
    try:
        for fut in concurrent.futures.as_completed(futures):
            label = futures[fut]
            try:
                res = fut.result()
            except Exception:
                continue
            if isinstance(res, tuple):
                pdf = res[0]
                extra = res[1] if len(res) > 1 else None
            else:
                pdf, extra = res, None
            if pdf:
                pdf_bytes = pdf
                winner = f"{label} ({extra})" if extra else label
                break
    finally:
        for f in futures:
            f.cancel()
        ex.shutdown(wait=False)
    return pdf_bytes, winner


def _resolve_institutions(payload_institutions: list[dict] | None) -> list[dict]:
    """
    Reconstitue la liste effective des institutions :
    - si le payload fournit une liste : on l'utilise (formulaire UI)
    - sinon : on charge depuis institutions.json
    - pour chaque institution sans password : on tente le cache session puis le disque
    Ne renvoie que les institutions ayant un nom, une URL et un password utilisable.
    """
    persisted = {i.get("name", ""): i for i in load_institutions()}
    base = payload_institutions if payload_institutions is not None else list(persisted.values())

    out: list[dict] = []
    for src in base:
        name = (src.get("name") or "").strip()
        ezproxy_url = (src.get("ezproxy_url") or "").strip()
        if not name or not ezproxy_url:
            continue
        password = (src.get("password") or "").strip()
        if not password:
            password = _SESSION_PASSWORDS.get(name) or (persisted.get(name, {}) or {}).get("password", "")
        if not password:
            continue
        out.append({
            "name": name,
            "ezproxy_url": ezproxy_url,
            "scope": (src.get("scope") or "").strip(),
            "username": (src.get("username") or "").strip(),
            "password": password,
        })
    return out


# --- Pipeline principal ------------------------------------------------------
def process_doi(
    doi_raw: str,
    email: str,
    institutions: list[dict] | None = None,
    use_extensions: bool = True,
    browser: bool = True,
) -> tuple[dict, bytes | None]:
    """Résout un DOI en PDF via la cascade de sources.

    `use_extensions` ne concerne que l'extension locale optionnelle
    (cf. `_private()`) : sans elle, le paramètre est sans effet.
    `browser=False` retire le tier navigateur headless (Playwright) : seuls
    les téléchargements HTTP directs restent (visiteurs d'une démo publique).
    """
    doi = normalize_doi(doi_raw)
    result = {
        "doi": doi,
        "input": doi_raw,
        "status": "failed",
        "source": None,
        "filename": None,
        "title": None,
        "error": None,
        "oa_url": None,   # URL éditeur pour téléchargement manuel si OA mais non téléchargeable
    }
    if not doi:
        result["error"] = "DOI vide"
        return result, None

    # 1) Métadonnées
    meta = fetch_crossref(doi)
    if not meta:
        result["error"] = "CrossRef : DOI introuvable"
        return result, None
    result["title"] = meta["title"]
    filename = build_filename(meta)
    result["filename"] = filename

    pdf_bytes = None
    pmc_ids: list[str] = []

    # --- TIER 1 (séquentiel) : Unpaywall (rapide + fournit les hints PMC/landing) -
    if email:
        pdf_bytes, oa_landing, pmc_ids = fetch_unpaywall_pdf(doi, email)
        if oa_landing:
            result["oa_url"] = oa_landing
        if pdf_bytes:
            result["status"] = "success"
            result["source"] = "unpaywall"
            return result, pdf_bytes

    # --- TIER 2 (parallèle) : sources OA — PMC, Publisher OA, Playwright ---------
    def _tier2_publisher() -> tuple[bytes | None, str | None]:
        pdf, _pub_url = fetch_publisher_pdf(doi)
        return pdf, None

    def _tier2_playwright() -> bytes | None:
        # Utilise l'oa_url Unpaywall si présent, sinon laisse fetch_playwright_pdf
        # repartir de doi.org/{doi}
        return fetch_playwright_pdf(doi, oa_url=result.get("oa_url"),
                                    use_extensions=use_extensions)

    tier2_tasks: list[tuple[str, callable]] = [
        ("europepmc",   lambda: fetch_pmc_pdf(doi, hint_pmc_ids=pmc_ids)),
        ("publisher_oa", _tier2_publisher),
    ]
    if browser:
        tier2_tasks.append(("playwright", _tier2_playwright))
    pdf_bytes, src = _run_tier_parallel(tier2_tasks)
    if pdf_bytes:
        result["status"] = "success"
        result["source"] = src
        return result, pdf_bytes

    # --- TIER 3 (parallèle) : accès institutionnel (+ extension si présente) ----
    # `diagnostics` remonte jusqu'à result["error"] : sans lui, un navigateur
    # absent, des identifiants refusés et un article vraiment indisponible sont
    # indiscernables côté utilisateur.
    diagnostics: list[str] = []
    ext = _private() if use_extensions else None
    active_institutions = _resolve_institutions(institutions)
    tier3_tasks: list[tuple[str, callable]] = []
    if active_institutions:
        tier3_tasks.append(("institution",
                            lambda: fetch_institutional_pdf(
                                doi, active_institutions, diag=diagnostics)))
    if ext is not None:
        tier3_tasks += ext.tier3_tasks(doi)

    pdf_bytes, src = _run_tier_parallel(tier3_tasks)
    if pdf_bytes:
        result["status"] = "success"
        result["source"] = src
        return result, pdf_bytes

    # --- TIER 4 (tout dernier recours) : fourni par l'extension ----------------
    if ext is not None:
        pdf_bytes, src = ext.tier4_last_resort(doi)
        if pdf_bytes:
            result["status"] = "success"
            result["source"] = src
            return result, pdf_bytes

    tried = ("Unpaywall + PMC + Publisher OA + Playwright" if browser
             else "Unpaywall + PMC + Publisher OA")
    if active_institutions:
        tried += " + Institutions"
    elif browser and (reason := playwright_unavailable_reason()):
        # no institution configured, but say once that the browser tiers were
        # skipped rather than tried and failed
        diagnostics.append(f"tiers Playwright ignorés — {reason}")
    message = f"Aucun PDF trouvé ({tried})"
    if diagnostics:
        message += " — " + " ; ".join(dict.fromkeys(diagnostics))
    result["error"] = message
    return result, None




