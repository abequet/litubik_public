# TEMPLATE — Section « Methods » d'une revue systématique avec snowballing

## 0. Instructions à l'IA (à lire avant génération)

**Rôle** : tu rédiges la section Méthodologie d'une revue systématique destinée à un journal à comité de lecture, conforme à PRISMA 2020 (Page et al., 2021).

**Entrées attendues de l'utilisateur** : chiffres bruts de screening, équations de recherche, dates, critères d'éligibilité, outils utilisés. Si une donnée manque, **écris `[À COMPLÉTER : <quoi>]` en gras dans le texte — n'invente jamais un chiffre, un κ, une date ou un nombre d'articles.**

**Langue de sortie** : `[LANG = EN | FR]`. Le squelette ci-dessous est en anglais (langue de soumission la plus fréquente) ; si `LANG = FR`, traduis les blocs de prose en conservant la terminologie du glossaire §9.

**Règles de style** : passé, voix passive ou « we » selon `[STYLE_VOIX]` ; pas d'interprétation ni de résultat de synthèse dans cette section ; chaque chiffre annoncé doit être cohérent avec le diagramme PRISMA ; toute décision méthodologique doit être **justifiée** (une phrase suffit) et non seulement déclarée.

**Cohérence arithmétique — vérification obligatoire avant de rendre** : `inclus + exclus + conflits = total screené` à chaque phase ; `corpus final = inclus base + inclus SB1 + inclus SB2 (+ …)`.

---

## 1. Study design and registration

> **Prose** — A systematic review was conducted following the PRISMA 2020 statement (Page et al., 2021). The protocol was pre-registered on `[REGISTRE : OSF / PROSPERO]` under the identifier `[ID_ENREGISTREMENT]` on `[DATE_ENREGISTREMENT]`. `[SI DÉVIATION : Deviations from the registered protocol are reported in §<x>.]`

*Consigne* : si aucun pré-enregistrement, l'écrire explicitement — c'est une limite, pas un silence à ménager. Préciser le type de revue si ce n'est pas une SR classique (scoping, rapid, umbrella — cf. Grant & Booth, 2009).

## 2. Eligibility criteria

> **Prose** — Inclusion and exclusion criteria were established prior to the search and are summarised in Table `[N_TABLE]`. Studies were included if they `[CRITÈRES_INCLUSION : design, période, objet, population]`. Studies were excluded if `[CRITÈRES_EXCLUSION]`.
>
> The `[DURÉE]`-year window (`[ANNÉE_DÉBUT]`–`[ANNÉE_FIN]`) was chosen because `[JUSTIFICATION_FENÊTRE]`. The inclusion of `[POPULATION_ÉLARGIE]` alongside `[POPULATION_CIBLE]` was a deliberate choice to `[JUSTIFICATION_POPULATION]`.

*Consigne* : produire la table à deux colonnes (Criterion / Description) avec critères lettrés (a), (b), (c)… Mentionner le cadre utilisé s'il y en a un (PICO / SPICE / SPIDER) ou dire qu'il a été adapté. Justifier obligatoirement : fenêtre temporelle, langues retenues, exclusion de la littérature grise et des designs qualitatifs.

## 3. Information sources and search strategy

### 3.1 Initial database search

> **Prose** — The search was conducted across `[N_BASES]` electronic databases: `[LISTE_BASES]`. Databases were selected to cover `[JUSTIFICATION_BASES : disciplines couvertes]`.
>
> `[N_CONCEPTS]` key concepts were derived from the research questions: `[CONCEPT_A]`, `[CONCEPT_B]`, `[CONCEPT_C]`… These were organised into `[N_BLOCS]` blocks combined with the Boolean operator AND; within each concept, synonyms and truncated terms were combined with OR (Table `[N_TABLE_TERMES]`). For each database, the equation was tailored to the constraints of the search engine and to the volume of initial results; the fields searched (title, abstract, or both) were adapted accordingly. The search was performed on `[DATE_RECHERCHE]` and yielded `[N_BRUT]` records (Table `[N_TABLE_ÉQUATIONS]`).

*Consigne* : deux tables — (i) concepts × termes de recherche, (ii) base × équation exacte × nombre de résultats, avec ligne de total. Reproduire les équations **verbatim**. Signaler les bases traitées différemment (langue, champ unique, fonctionnalité limitée) en note de table.

### 3.2 Snowballing search

> **Prose** — In addition to the database search, backward (reference lists) and forward (citing articles) snowballing was performed following the guidelines of Wohlin (2014), using `[OUTIL : Google Scholar / Citation Chaser (Haddaway et al., 2021)]`. Each iteration used the studies included in the previous step as the seed set. Iterations were conducted one at a time to preserve traceability, and were stopped when `[CRITÈRE_ARRÊT : aucune nouvelle étude incluse / N itérations planifiées]`. Snowballing was completed on `[DATE_SB]`.

*Consigne* : préciser que l'inclusion d'un article est décidée sur texte intégral **avant** qu'il n'entre comme graine dans l'itération suivante (Wohlin, 2014), et que la déduplication est faite au sein de et entre itérations.

## 4. Study selection

*Consigne globale* : une sous-section par phase, chacune sur le même patron (screené → inclus par les deux → exclus par les deux → conflits → résolution → κ → retenus). Reporter κ avec l'interprétation de Landis & Koch (1977).

### Phase 1 — Title and abstract screening (`[SOURCE : initial search / SB<i>]`)

> **Prose** — After deduplication, `[N_UNIQUES]` unique records were identified. Titles and abstracts were independently screened by `[N_REVIEWERS]` reviewers (`[INITIALES]`) against the eligibility criteria, each record receiving a binary decision. `[N_INCLUS_2]` records were included by both reviewers, `[N_EXCLUS_2]` were excluded by both, and `[N_CONFLITS]` generated disagreements, which were resolved through discussion. Inter-rater reliability was κ = `[KAPPA]`, indicating `[INTERPRÉTATION]` agreement (Landis & Koch, 1977). `[N_RETENUS]` records were retained for full-text screening.

### Phase 2 — Full-text screening

> **Prose** — `[N_FULLTEXT]` full-text articles were retrieved and independently assessed; `[N_NON_RETROUVÉS]` could not be retrieved. Each reviewer provided a binary decision together with the primary exclusion criterion. `[…mêmes placeholders que Phase 1…]`. The most frequent reasons for exclusion were: `[MOTIF_1]` (n = `[N1]`), `[MOTIF_2]` (n = `[N2]`)… `[PRÉCISER : décisions cumulées entre relecteurs ou articles uniques]`.

### Phase 3+ — Snowballing iterations

> **Prose** — Reference lists of the `[N_GRAINES]` seed studies were inspected and citing articles retrieved, yielding `[N_TOTAL_REF]` references (`[N_BACKWARD]` backward, `[N_FORWARD]` forward). `[N_EXCLUS_AUTO]` were removed as out of scope or outside the date range, leaving `[N_UNIQUES_SB]` unique records after deduplication. These were screened following the same two-phase procedure `[reprendre patron Phase 1 puis Phase 2]`, yielding `[N_INCLUS_SB]` additional studies.

*Consigne* : répéter le bloc pour SB2, SB3… La fréquence de nouvelles inclusions doit décroître ; si ce n'est pas le cas, le signaler et envisager une nouvelle équation avec synonymes (Wohlin, 2014, leçon 8).

### Final corpus

> **Prose** — The database search and snowballing procedure resulted in `[N_FINAL]` studies included in the synthesis (`[N_BASE]` from the database search, `[N_SB1]` from SB1, `[N_SB2]` from SB2). The selection process is summarised in the PRISMA flow diagram (Fig. `[N_FIG]`).

## 5. Data collection process

> **Prose** — Data extraction was performed independently by `[N_EXTRACTEURS]` reviewers using a standardised extraction form `[+ pilote sur N articles si applicable]`, then cross-checked; discrepancies were resolved through discussion until consensus. The form captured: (a) bibliographic details; (b) study characteristics; (c) population characteristics; (d) theoretical framework; (e) measurement instruments; (f) `[VARIABLES_SPÉCIFIQUES]`; (g) main outcomes; (h) limitations and future directions reported by the authors. The primary outcome domains were `[DOMAINES]`. Ambiguous or missing information was coded conservatively and the ambiguity noted. The complete extraction table is available as Supplementary Material `[N_SUPP]`.

## 6. Methodological quality assessment

> **Prose** — Methodological quality was assessed using `[OUTIL : JBI (Pearson & Jordan, 2010) / CASP (2018) / ROBIS / AMSTAR-2]`, applying the checklists for `[DESIGNS_CONCERNÉS]`. Appraisal was conducted by `[QUI]`. `[Studies were / were not]` excluded on the basis of quality; `[JUSTIFICATION]`. Ratings are reported in Supplementary Material `[N_SUPP2]`.

## 7. Synthesis methods

> **Prose** — A `[narrative / quantitative]` synthesis was conducted `[justification : hétérogénéité des designs et des mesures, etc.]` (Popay et al., 2006). Included studies were grouped according to `[CRITÈRE_REGROUPEMENT : questions de recherche / cadre théorique / type d'intervention]`. Themes were derived from `[MÉTHODE]`. `[SI OUTIL IA/RAG : décrire l'outil, la version, le rôle exact, la vérification humaine, et renvoyer au dépôt <URL>.]`

## 8. Checklist de sortie

- [ ] Tous les chiffres cohérents entre texte, tables et figure PRISMA
- [ ] Chaque κ accompagné de son interprétation et de sa référence
- [ ] Équations de recherche reproduites verbatim + date de recherche
- [ ] Chaque choix restrictif justifié (fenêtre, langues, designs, populations)
- [ ] Aucun chiffre inventé ; `[À COMPLÉTER]` visible pour toute donnée manquante
- [ ] Aucun résultat de synthèse dans la section Méthodes

## 9. Glossaire EN/FR

backward/forward snowballing → snowballing arrière/avant · seed set → ensemble de départ · screening → sélection/tri · title and abstract screening → tri sur titres et résumés · full-text screening → tri sur texte intégral · eligibility criteria → critères d'éligibilité · inter-rater reliability → accord inter-juges · risk of bias → risque de biais · narrative synthesis → synthèse narrative · grey literature → littérature grise · records → références/notices · deduplication → déduplication
