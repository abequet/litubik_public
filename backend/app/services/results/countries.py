# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M10: deterministic country normalization for the Results stage.

The extraction table stores country as free text ("France", "USA / Germany",
"États-Unis"...). This module maps such strings to ISO 3166-1 alpha-3 codes
with a built-in alias table (English + French names, ISO2/ISO3 codes, common
variants) — no network, no LLM. Unrecognized parts are returned separately so
the UI can list them instead of silently dropping studies.
"""
import re
import unicodedata

# (iso3, iso2, name_en, name_fr, extra aliases). Alias keys are normalized at
# import time (lowercase, accents stripped) so "Corée du Sud" == "coree du sud".
COUNTRIES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("AFG", "AF", "Afghanistan", "Afghanistan", ()),
    ("ALB", "AL", "Albania", "Albanie", ()),
    ("DZA", "DZ", "Algeria", "Algérie", ()),
    ("AND", "AD", "Andorra", "Andorre", ()),
    ("AGO", "AO", "Angola", "Angola", ()),
    ("ATG", "AG", "Antigua and Barbuda", "Antigua-et-Barbuda", ("antigua",)),
    ("ARG", "AR", "Argentina", "Argentine", ()),
    ("ARM", "AM", "Armenia", "Arménie", ()),
    ("AUS", "AU", "Australia", "Australie", ()),
    ("AUT", "AT", "Austria", "Autriche", ()),
    ("AZE", "AZ", "Azerbaijan", "Azerbaïdjan", ()),
    ("BHS", "BS", "Bahamas", "Bahamas", ("the bahamas",)),
    ("BHR", "BH", "Bahrain", "Bahreïn", ()),
    ("BGD", "BD", "Bangladesh", "Bangladesh", ()),
    ("BRB", "BB", "Barbados", "Barbade", ()),
    ("BLR", "BY", "Belarus", "Biélorussie", ("belorussia", "byelorussia")),
    ("BEL", "BE", "Belgium", "Belgique", ()),
    ("BLZ", "BZ", "Belize", "Belize", ()),
    ("BEN", "BJ", "Benin", "Bénin", ()),
    ("BTN", "BT", "Bhutan", "Bhoutan", ()),
    ("BOL", "BO", "Bolivia", "Bolivie",
     ("bolivia (plurinational state of)", "plurinational state of bolivia")),
    ("BIH", "BA", "Bosnia and Herzegovina", "Bosnie-Herzégovine",
     ("bosnia", "bosnia-herzegovina", "bosnia & herzegovina")),
    ("BWA", "BW", "Botswana", "Botswana", ()),
    ("BRA", "BR", "Brazil", "Brésil", ("brasil",)),
    ("BRN", "BN", "Brunei", "Brunéi", ("brunei darussalam",)),
    ("BGR", "BG", "Bulgaria", "Bulgarie", ()),
    ("BFA", "BF", "Burkina Faso", "Burkina Faso", ("burkina",)),
    ("BDI", "BI", "Burundi", "Burundi", ()),
    ("CPV", "CV", "Cabo Verde", "Cap-Vert", ("cape verde",)),
    ("KHM", "KH", "Cambodia", "Cambodge", ()),
    ("CMR", "CM", "Cameroon", "Cameroun", ()),
    ("CAN", "CA", "Canada", "Canada", ()),
    ("CAF", "CF", "Central African Republic", "République centrafricaine",
     ("centrafrique",)),
    ("TCD", "TD", "Chad", "Tchad", ()),
    ("CHL", "CL", "Chile", "Chili", ()),
    ("CHN", "CN", "China", "Chine",
     ("people's republic of china", "mainland china", "prc")),
    ("COL", "CO", "Colombia", "Colombie", ()),
    ("COM", "KM", "Comoros", "Comores", ()),
    ("COG", "CG", "Congo", "Congo",
     ("republic of the congo", "congo-brazzaville", "republic of congo")),
    ("COD", "CD", "Democratic Republic of the Congo",
     "République démocratique du Congo",
     ("drc", "dr congo", "congo-kinshasa", "rdc",
      "democratic republic of congo",
      "the democratic republic of the congo", "congo, dem. rep.")),
    ("CRI", "CR", "Costa Rica", "Costa Rica", ()),
    ("CIV", "CI", "Côte d'Ivoire", "Côte d'Ivoire", ("ivory coast",)),
    ("HRV", "HR", "Croatia", "Croatie", ()),
    ("CUB", "CU", "Cuba", "Cuba", ()),
    ("CYP", "CY", "Cyprus", "Chypre", ()),
    ("CZE", "CZ", "Czechia", "Tchéquie",
     ("czech republic", "republique tcheque", "czechoslovakia")),
    ("DNK", "DK", "Denmark", "Danemark", ()),
    ("DJI", "DJ", "Djibouti", "Djibouti", ()),
    ("DMA", "DM", "Dominica", "Dominique", ()),
    ("DOM", "DO", "Dominican Republic", "République dominicaine", ()),
    ("ECU", "EC", "Ecuador", "Équateur", ()),
    ("EGY", "EG", "Egypt", "Égypte", ()),
    ("SLV", "SV", "El Salvador", "Salvador", ()),
    ("GNQ", "GQ", "Equatorial Guinea", "Guinée équatoriale", ()),
    ("ERI", "ER", "Eritrea", "Érythrée", ()),
    ("EST", "EE", "Estonia", "Estonie", ()),
    ("SWZ", "SZ", "Eswatini", "Eswatini", ("swaziland",)),
    ("ETH", "ET", "Ethiopia", "Éthiopie", ()),
    ("FJI", "FJ", "Fiji", "Fidji", ()),
    ("FIN", "FI", "Finland", "Finlande", ()),
    ("FRA", "FR", "France", "France", ()),
    ("GAB", "GA", "Gabon", "Gabon", ()),
    ("GMB", "GM", "Gambia", "Gambie", ("the gambia",)),
    ("GEO", "GE", "Georgia", "Géorgie", ()),
    ("DEU", "DE", "Germany", "Allemagne", ()),
    ("GHA", "GH", "Ghana", "Ghana", ()),
    ("GRC", "GR", "Greece", "Grèce", ()),
    ("GRD", "GD", "Grenada", "Grenade", ()),
    ("GTM", "GT", "Guatemala", "Guatemala", ()),
    ("GIN", "GN", "Guinea", "Guinée", ()),
    ("GNB", "GW", "Guinea-Bissau", "Guinée-Bissau", ()),
    ("GUY", "GY", "Guyana", "Guyana", ()),
    ("HTI", "HT", "Haiti", "Haïti", ()),
    ("HND", "HN", "Honduras", "Honduras", ()),
    ("HUN", "HU", "Hungary", "Hongrie", ()),
    ("ISL", "IS", "Iceland", "Islande", ()),
    ("IND", "IN", "India", "Inde", ()),
    ("IDN", "ID", "Indonesia", "Indonésie", ()),
    ("IRN", "IR", "Iran", "Iran",
     ("islamic republic of iran", "iran (islamic republic of)")),
    ("IRQ", "IQ", "Iraq", "Irak", ()),
    ("IRL", "IE", "Ireland", "Irlande", ("republic of ireland",)),
    ("ISR", "IL", "Israel", "Israël", ()),
    ("ITA", "IT", "Italy", "Italie", ()),
    ("JAM", "JM", "Jamaica", "Jamaïque", ()),
    ("JPN", "JP", "Japan", "Japon", ()),
    ("JOR", "JO", "Jordan", "Jordanie", ()),
    ("KAZ", "KZ", "Kazakhstan", "Kazakhstan", ()),
    ("KEN", "KE", "Kenya", "Kenya", ()),
    ("KIR", "KI", "Kiribati", "Kiribati", ()),
    ("PRK", "KP", "North Korea", "Corée du Nord",
     ("democratic people's republic of korea", "dprk", "korea, dpr")),
    ("KOR", "KR", "South Korea", "Corée du Sud",
     ("korea", "republic of korea", "korea, republic of", "s. korea",
      "coree")),
    ("KWT", "KW", "Kuwait", "Koweït", ()),
    ("KGZ", "KG", "Kyrgyzstan", "Kirghizistan", ("kyrgyz republic",)),
    ("LAO", "LA", "Laos", "Laos",
     ("lao people's democratic republic", "lao pdr")),
    ("LVA", "LV", "Latvia", "Lettonie", ()),
    ("LBN", "LB", "Lebanon", "Liban", ()),
    ("LSO", "LS", "Lesotho", "Lesotho", ()),
    ("LBR", "LR", "Liberia", "Libéria", ()),
    ("LBY", "LY", "Libya", "Libye", ()),
    ("LIE", "LI", "Liechtenstein", "Liechtenstein", ()),
    ("LTU", "LT", "Lithuania", "Lituanie", ()),
    ("LUX", "LU", "Luxembourg", "Luxembourg", ()),
    ("MDG", "MG", "Madagascar", "Madagascar", ()),
    ("MWI", "MW", "Malawi", "Malawi", ()),
    ("MYS", "MY", "Malaysia", "Malaisie", ()),
    ("MDV", "MV", "Maldives", "Maldives", ()),
    ("MLI", "ML", "Mali", "Mali", ()),
    ("MLT", "MT", "Malta", "Malte", ()),
    ("MHL", "MH", "Marshall Islands", "Îles Marshall", ()),
    ("MRT", "MR", "Mauritania", "Mauritanie", ()),
    ("MUS", "MU", "Mauritius", "Maurice", ("ile maurice",)),
    ("MEX", "MX", "Mexico", "Mexique", ()),
    ("FSM", "FM", "Micronesia", "Micronésie",
     ("federated states of micronesia",)),
    ("MDA", "MD", "Moldova", "Moldavie", ("republic of moldova",)),
    ("MCO", "MC", "Monaco", "Monaco", ()),
    ("MNG", "MN", "Mongolia", "Mongolie", ()),
    ("MNE", "ME", "Montenegro", "Monténégro", ()),
    ("MAR", "MA", "Morocco", "Maroc", ()),
    ("MOZ", "MZ", "Mozambique", "Mozambique", ()),
    ("MMR", "MM", "Myanmar", "Myanmar", ("burma", "birmanie")),
    ("NAM", "NA", "Namibia", "Namibie", ()),
    ("NRU", "NR", "Nauru", "Nauru", ()),
    ("NPL", "NP", "Nepal", "Népal", ()),
    ("NLD", "NL", "Netherlands", "Pays-Bas", ("the netherlands", "holland")),
    ("NZL", "NZ", "New Zealand", "Nouvelle-Zélande", ()),
    ("NIC", "NI", "Nicaragua", "Nicaragua", ()),
    ("NER", "NE", "Niger", "Niger", ()),
    ("NGA", "NG", "Nigeria", "Nigéria", ()),
    ("MKD", "MK", "North Macedonia", "Macédoine du Nord",
     ("macedonia", "fyrom")),
    ("NOR", "NO", "Norway", "Norvège", ()),
    ("OMN", "OM", "Oman", "Oman", ()),
    ("PAK", "PK", "Pakistan", "Pakistan", ()),
    ("PLW", "PW", "Palau", "Palaos", ()),
    ("PSE", "PS", "Palestine", "Palestine",
     ("state of palestine", "palestinian territories", "west bank and gaza")),
    ("PAN", "PA", "Panama", "Panama", ()),
    ("PNG", "PG", "Papua New Guinea", "Papouasie-Nouvelle-Guinée", ()),
    ("PRY", "PY", "Paraguay", "Paraguay", ()),
    ("PER", "PE", "Peru", "Pérou", ()),
    ("PHL", "PH", "Philippines", "Philippines", ("the philippines",)),
    ("POL", "PL", "Poland", "Pologne", ()),
    ("PRT", "PT", "Portugal", "Portugal", ()),
    ("QAT", "QA", "Qatar", "Qatar", ()),
    ("ROU", "RO", "Romania", "Roumanie", ()),
    ("RUS", "RU", "Russia", "Russie", ("russian federation", "ussr",
                                       "soviet union")),
    ("RWA", "RW", "Rwanda", "Rwanda", ()),
    ("KNA", "KN", "Saint Kitts and Nevis", "Saint-Kitts-et-Nevis", ()),
    ("LCA", "LC", "Saint Lucia", "Sainte-Lucie", ()),
    ("VCT", "VC", "Saint Vincent and the Grenadines",
     "Saint-Vincent-et-les-Grenadines", ()),
    ("WSM", "WS", "Samoa", "Samoa", ()),
    ("SMR", "SM", "San Marino", "Saint-Marin", ()),
    ("STP", "ST", "Sao Tome and Principe", "Sao Tomé-et-Principe",
     ("são tomé and príncipe",)),
    ("SAU", "SA", "Saudi Arabia", "Arabie saoudite", ("ksa",)),
    ("SEN", "SN", "Senegal", "Sénégal", ()),
    ("SRB", "RS", "Serbia", "Serbie", ()),
    ("SYC", "SC", "Seychelles", "Seychelles", ()),
    ("SLE", "SL", "Sierra Leone", "Sierra Leone", ()),
    ("SGP", "SG", "Singapore", "Singapour", ()),
    ("SVK", "SK", "Slovakia", "Slovaquie", ("slovak republic",)),
    ("SVN", "SI", "Slovenia", "Slovénie", ()),
    ("SLB", "SB", "Solomon Islands", "Îles Salomon", ()),
    ("SOM", "SO", "Somalia", "Somalie", ()),
    ("ZAF", "ZA", "South Africa", "Afrique du Sud", ()),
    ("SSD", "SS", "South Sudan", "Soudan du Sud", ()),
    ("ESP", "ES", "Spain", "Espagne", ()),
    ("LKA", "LK", "Sri Lanka", "Sri Lanka", ()),
    ("SDN", "SD", "Sudan", "Soudan", ()),
    ("SUR", "SR", "Suriname", "Suriname", ()),
    ("SWE", "SE", "Sweden", "Suède", ()),
    ("CHE", "CH", "Switzerland", "Suisse", ()),
    ("SYR", "SY", "Syria", "Syrie", ("syrian arab republic",)),
    ("TJK", "TJ", "Tajikistan", "Tadjikistan", ()),
    ("TZA", "TZ", "Tanzania", "Tanzanie", ("united republic of tanzania",)),
    ("THA", "TH", "Thailand", "Thaïlande", ()),
    ("TLS", "TL", "Timor-Leste", "Timor oriental", ("east timor",)),
    ("TGO", "TG", "Togo", "Togo", ()),
    ("TON", "TO", "Tonga", "Tonga", ()),
    ("TTO", "TT", "Trinidad and Tobago", "Trinité-et-Tobago", ("trinidad",)),
    ("TUN", "TN", "Tunisia", "Tunisie", ()),
    ("TUR", "TR", "Turkey", "Turquie", ("turkiye", "türkiye")),
    ("TKM", "TM", "Turkmenistan", "Turkménistan", ()),
    ("TUV", "TV", "Tuvalu", "Tuvalu", ()),
    ("UGA", "UG", "Uganda", "Ouganda", ()),
    ("UKR", "UA", "Ukraine", "Ukraine", ()),
    ("ARE", "AE", "United Arab Emirates", "Émirats arabes unis",
     ("uae", "emirates")),
    ("GBR", "GB", "United Kingdom", "Royaume-Uni",
     ("uk", "u.k.", "great britain", "england", "scotland", "wales",
      "northern ireland",
      "united kingdom of great britain and northern ireland")),
    ("USA", "US", "United States", "États-Unis",
     ("u.s.", "u.s.a.", "united states of america", "america",
      "etats-unis d'amerique")),
    ("URY", "UY", "Uruguay", "Uruguay", ()),
    ("UZB", "UZ", "Uzbekistan", "Ouzbékistan", ()),
    ("VUT", "VU", "Vanuatu", "Vanuatu", ()),
    ("VAT", "VA", "Vatican", "Vatican", ("holy see", "vatican city")),
    ("VEN", "VE", "Venezuela", "Venezuela",
     ("bolivarian republic of venezuela",
      "venezuela (bolivarian republic of)")),
    ("VNM", "VN", "Vietnam", "Viêt Nam", ("viet nam",)),
    ("YEM", "YE", "Yemen", "Yémen", ()),
    ("ZMB", "ZM", "Zambia", "Zambie", ()),
    ("ZWE", "ZW", "Zimbabwe", "Zimbabwe", ()),
    # Non-UN territories that appear as study locations
    ("TWN", "TW", "Taiwan", "Taïwan",
     ("chinese taipei", "taiwan, province of china", "republic of china")),
    ("HKG", "HK", "Hong Kong", "Hong Kong",
     ("hong kong sar", "hong kong, china")),
    ("MAC", "MO", "Macao", "Macao", ("macau",)),
    ("PRI", "PR", "Puerto Rico", "Porto Rico", ()),
    ("GRL", "GL", "Greenland", "Groenland", ()),
    ("NCL", "NC", "New Caledonia", "Nouvelle-Calédonie", ()),
    ("PYF", "PF", "French Polynesia", "Polynésie française", ("tahiti",)),
    ("REU", "RE", "Réunion", "La Réunion", ("reunion island",)),
    ("GLP", "GP", "Guadeloupe", "Guadeloupe", ()),
    ("MTQ", "MQ", "Martinique", "Martinique", ()),
    ("GUF", "GF", "French Guiana", "Guyane française", ("guyane",)),
    ("XKX", "XK", "Kosovo", "Kosovo", ()),
)

# Cell values that mean "not stated" — treated as missing, never as unmatched.
NONE_TOKENS = {"", "na", "n.a", "n/a", "none", "not reported", "not stated",
               "not specified", "unknown", "unclear", "nr", "ns", "-", "?"}

# Short codes too ambiguous to accept as aliases ("NA" = not applicable, not
# Namibia; a stray "and" from a bad split must not become Andorra).
_BLOCKED_KEYS = {"na", "and", "et"}


def _norm(s: str) -> str:
    """Normalization key: lowercase, accents stripped, straight apostrophes,
    collapsed whitespace, trailing punctuation/parentheticals removed."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").lower()
    s = re.sub(r"\([^)]*\)", " ", s)          # "France (Paris)" -> "France"
    s = re.sub(r"[\s ]+", " ", s).strip()
    s = s.strip(".,;:!? ")
    if s.startswith("the "):
        s = s[4:]
    return s


def _build_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for iso3, iso2, name_en, name_fr, extra in COUNTRIES:
        keys = {_norm(name_en), _norm(name_fr), iso3.lower(), iso2.lower()}
        keys |= {_norm(a) for a in extra}
        for key in keys:
            if key and key not in _BLOCKED_KEYS:
                aliases[key] = iso3
    return aliases


ALIASES: dict[str, str] = _build_aliases()
NAMES_EN: dict[str, str] = {iso3: name_en for iso3, _, name_en, _, _ in COUNTRIES}

_SPLIT_RE = re.compile(r"[,;/&|]|\bversus\b|\bvs\.?\b")
_AND_RE = re.compile(r"\band\b|\bet\b")


def country_name(iso3: str) -> str:
    return NAMES_EN.get(iso3, iso3)


def split_cell(text: str) -> list[str]:
    """Raw parts of a possibly multi-country cell, order-preserving dedup."""
    parts, seen = [], set()
    for part in _SPLIT_RE.split(text or ""):
        part = part.strip()
        key = _norm(part)
        if part and key and key not in seen:
            seen.add(key)
            parts.append(part)
    return parts


def normalize_cell(text: str) -> tuple[list[str], list[str]]:
    """Map a free-text cell to ([iso3...], [unmatched raw parts]).

    A full-cell match wins first so names containing "and" ("Trinidad and
    Tobago") survive; only then are parts split on strong delimiters, and an
    unresolved part gets one last chance as an "X and Y" enumeration.
    """
    full = _norm(text or "")
    if full in NONE_TOKENS:
        return [], []
    if full in ALIASES:
        return [ALIASES[full]], []

    matched: list[str] = []
    unmatched: list[str] = []

    def _push(iso3: str):
        if iso3 not in matched:
            matched.append(iso3)

    for part in split_cell(text):
        key = _norm(part)
        if key in NONE_TOKENS:
            continue
        if key in ALIASES:
            _push(ALIASES[key])
            continue
        # "France and Germany" — only accept the split if EVERY piece matches,
        # so "Trinidad and Tobago"-like names never end up half-matched.
        pieces = [_norm(p) for p in _AND_RE.split(key)]
        pieces = [p for p in pieces if p and p not in NONE_TOKENS]
        if len(pieces) > 1 and all(p in ALIASES for p in pieces):
            for p in pieces:
                _push(ALIASES[p])
        else:
            unmatched.append(part.strip())
    return matched, unmatched
