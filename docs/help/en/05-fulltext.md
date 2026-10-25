# Retrieving and reading full texts

## Automatic retrieval

The **FT retrieval** step tries to download the PDF of every record included
at title/abstract screening. It goes through the sources in order and stops at
the first that answers:

1. **Crossref** — resolves the DOI and gives the publisher's declared links;
2. **Unpaywall** — the open-access copy when one is registered;
3. **PubMed Central / Europe PMC**;
4. **the publisher's own open-access page**;
5. **your institutional access**, if you configured one (see below).

Nothing else is tried: no shadow library, no paywall circumvention. When every
source fails, the record is marked *not retrieved* — that count feeds the
PRISMA diagram directly — and you can upload the PDF by hand.

The status of each record shows whether a PDF was found, is pending, or failed.
Any member of the project can launch retrieval, not just admins.

## My institutional access (paywalled PDFs)

Articles behind a paywall can often be fetched through your library's proxy
(EZproxy, OpenAthens, CAS). Add your institution from **My institutional
access** in the sidebar (also available on the Full-text page of a project,
and in *Project settings → Institutional access*): start typing its name and
pick it from the built-in directory — the proxy URL fills in automatically —
then enter your usual library username and password.

**If your university logs in through a federated CAS** — several institutions
sharing one proxy, as in Toulouse — the login page asks you to pick your
establishment from a menu. The built-in directory only knows the proxy URL, not
that choice, so you have to fill the **scope** field yourself. Left empty, the
login goes ahead with the menu's default establishment and fails. Run a
retrieval once: the error shown on the record lists the accepted values (for
Université Toulouse II Jean Jaurès it is `ut2`).

The directory search tolerates accents, hyphens and the proxy domain, so
`université gustave eiffel`, `univ-eiffel` and `ucly` all find their
institution. It is a public directory, not an exhaustive one: if yours is not
listed, keep the name you typed and paste the proxy login URL yourself — it
looks like `https://<something>/login?url=$@` and your library can give it to
you (`$@` is where the app inserts the article URL).

**Where your credentials live depends on how you added them**, and the
difference matters:

- **My institutional access** (sidebar) keeps them **in your browser only**.
  They are sent once with each retrieval you launch, used to fetch the PDFs,
  and forgotten server-side. By default the password is kept until the tab
  closes; tick *Remember on this device* to keep it in this browser.
- **Project settings → Institutional access** and the app-wide *Institutional
  access (app)* page **store them on the server**, encrypted, and every project
  on the instance can use them. That is the point — it lets a team share one
  library account — but it does mean your password leaves your machine and that
  the instance administrator holds the key that decrypts it.

Automated retrieval through a library proxy is a bulk download from the
publisher's point of view. Most subscription agreements forbid "systematic or
substantial" downloading, and the usual sanction falls on the whole institution,
not on the individual. Check what your library's terms allow before running
large batches, and keep the retrieved PDFs inside the review team.

If you join a project as a reviewer and some PDFs are still missing, add your
own institution and press *Retrieve missing PDFs*: anything your subscription
covers is downloaded and shared with the whole project.

## Shared access (server-stored)

Besides your personal credentials, LitUbik can hold **shared** proxies on the
server, encrypted, tried for every retrieval:

- **app-wide** — *Administration → Institutional access (app)* (application
  admin); inherited by every project of the instance;
- **project-specific** — *Full-text page → Settings* (project admin).

Both are listed in *Project settings → Institutional access*, next to your own
browser-held ones, so you can see at a glance which access is already
configured and where to change it. Use shared access for a subscription the
whole team may use, and personal access for credentials that must stay yours.

## Manual upload and replacement

For papers the automatic tier cannot reach (paywalled, scanned…), drop the
PDF manually on the record, or use the *Replace PDF* button if the retrieved
file is wrong (e.g. supplementary material instead of the article).

Every project member can upload or replace a PDF — not only admins — so a
reviewer who meets a missing or wrong file fixes it on the spot, from any
of three places:

- the **Full-text** page (*Upload PDF* / *Replace* on the record's row);
- the **PDF library** drawer (*Replace PDF* next to each entry);
- the **full-text screening** screen itself (*Upload PDF* in the empty
  viewer, *Replace PDF* under the title), where the viewer reloads the new
  file at once.

Removing a PDF altogether remains an admin action.

## Bulk PDF import

Already have the PDFs — say, from the platform where the review started, or
a Zotero folder? On the **Full-text** page, the project admin can use **Bulk
PDF import** and select many files at once. Each file is linked to its
article automatically: by DOI printed inside the PDF, by DOI embedded in the
filename, or by matching the title (in the text, then in the filename).
Files matched with confidence are stored immediately; the rest are listed
with their best candidates and a dropdown to assign each one by hand — or to
replace an existing PDF. Articles imported with an external extraction
table are part of the library too, so their PDFs can be imported (or
auto-retrieved) the same way.

## The PDF library

The sidebar's **Downloaded PDFs** entry lists every PDF of the project.
PDFs open in the built-in viewer, which supports highlighting and
annotations shared with the team; a PDF can also be opened in a separate
window to read while screening. Select some text and right-click: **Copy**
puts it on the clipboard, **Add comment / highlight** shares it with the
team — once the report's full-text screening is complete; until then each
reviewer sees only their own highlights, so the blind holds.

Each entry is colour-coded by its full-text decision (included, excluded,
to assess). The chips above the list filter it: press **included** to see
only the PDFs you kept, **All** to see everything again; the list can also
be sorted by author, year or decision.

Each entry has a checkbox, and **Download selection** at the bottom of the
panel bundles what you ticked into a zip — **Select all** takes the whole
library, or only the entries shown when a filter is active (so "all the
included PDFs" is one chip plus one checkbox). Inside the zip, every file is renamed to
`Author_Year_five_first_title_words.pdf` (first author's family name, year
of publication, first five words of the title), so the archive drops
straight into your own folders or into Zotero.

## Downloading papers outside a project

Need a few PDFs without setting up a review? **Download papers**, in the
*Workspace* section of the sidebar (under *Projects*), works on its own:
paste DOIs — one per line, or separated by commas or spaces; `doi:` prefixes
and `doi.org` links are fine — and press **Download**.

The module is **closed by default**: an application admin opens it user by
user, by ticking *Download papers* in **Administration → Users**. Until then
the entry does not appear in your sidebar. Once it is open, you can request
**5 papers per hour** (a paper that could not be found is not counted); the
page shows how many you have left and when the next slot frees up.
Application admins always have the module and no hourly limit (200 DOIs per
run at most).

Application admins also see **what the module was used for**: the same
**Administration → Users** page lists, under *Downloaded papers*, every user
who ran it, with the number of runs and PDFs retrieved; opening a user shows
each run and each paper requested — title, DOI, whether a PDF was found and
from which source. The PDFs themselves are not kept beyond 24 hours; only this
record of the requests is.

The same sources as a project's retrieval are tried, including your own
institutional access and the app-wide one. When the run ends, your browser
downloads the result: **the PDF itself if one paper was found, a zip if there
are several**. Files are named `Author_Year_first_title_words.pdf`, like the
batch retrieval. Papers that could not be found are listed with the reason
and, when known, a link to the publisher page.

Nothing is added to any project. The run happens on the server, so you can
leave the page and come back; the files stay available for 24 hours, and only
you can fetch them.

## Sharing PDFs across the team

PDFs travel with project snapshots (see *Collaboration and sync*), so a
full text retrieved by one member becomes available to all.
