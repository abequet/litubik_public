# Conformité de LitUbik aux standards de revue systématique

> Établi le 2026-08-13, à partir de trois documents de référence fournis par
> l'utilisateur. Ce document est **la référence de recette** du chantier de
> conformité : chaque ligne marquée ✗ ou ◐ doit passer à ✅ avec le chemin du
> fichier qui la couvre.

## Les trois sources

| Source | Ce qu'elle normalise |
|---|---|
| **SWiM** — Campbell M, McKenzie JE, Sowden A, *et al.* Synthesis without meta-analysis (SWiM) in systematic reviews: reporting guideline. *BMJ* 2020;368:l6890. doi:10.1136/bmj.l6890 | 9 items de **rapport** de la synthèse quand la méta-analyse d'estimations d'effet n'est pas possible. Extension de PRISMA, pas un guide de conduite. |
| **GRADE** — Brignardello-Petersen R, Guyatt GH. Assessing the certainty of the evidence in systematic reviews: importance, process, and use. *Am J Epidemiol* 2025;194(6):1681–6. doi:10.1093/aje/kwae332 | Les 5 étapes de l'évaluation de la **certitude de la preuve**, par résultat. Attendu méthodologique Cochrane ; adopté par plus de 110 organisations. |
| **CREST_Triage** — Whaley P. CREST_Triage: Appraisal Tool for Systematic Reviews (Word Version). 2022. https://osf.io/u4j5m/ | Grille de **triage éditorial** en 6 domaines notés 1–5, plus une liste de problèmes récurrents. Un score de 1 ou 2 conduit généralement au rejet. |

Les trois se recoupent : CREST domaine 5 ≈ SWiM, CREST domaine 6 ≈ GRADE. Le
constat commun est que la partie **aval** d'une revue — comment les études sont
groupées, par quelle méthode elles sont synthétisées, avec quelle confiance les
conclusions sont énoncées — est la moins bien rapportée et la plus souvent
sanctionnée.

## Synthèse du diagnostic

LitUbik couvre l'amont mieux que le standard ne l'exige et s'arrête avant
l'aval. Les domaines 1 à 3 de CREST (objectifs, recherche, screening) sont
tenus par des données mesurées, pas par des déclarations ; les domaines 5 et 6
(synthèse, certitude) n'existent pas dans le modèle de données.

```
CREST 1 Objectifs     ████████████████████ conforme
CREST 2 Recherche     ████████████████████ conforme (au-delà du standard)
CREST 3 Screening     ████████████████████ conforme
CREST 4 Appraisal     ████████████████████ conforme (chantier B)
CREST 5 Synthèse      ████████████████████ conforme (chantier C)
CREST 6 Certitude     ████████████████████ conforme (chantier C)
```

---

## 1. CREST_Triage — les six domaines, item par item

### Domaine 1 · Formulation et justification des objectifs — ✅

| Problème listé par CREST | État | Où |
|---|---|---|
| Justification ou valeur de l'objectif | ✅ | `Protocol.protocol_md` → section Background, extraite du protocole pré-enregistré ([protocol/service.py](../backend/app/services/protocol/service.py)) |
| Faisabilité de l'objectif | ✅ (indirect) | `EquationCount` donne le volume réel par base avant de lancer la revue — la faisabilité est mesurée, pas estimée |
| Clarté et focalisation de l'objectif | ✅ | `research_questions` + `objectives` structurés ; `Project.question_framework` impose un cadre (PICO, PICOS, SPIDER, SPICE, PEO ou « libre assumé ») — [framing.py](../backend/app/services/framing.py) |

**Rien à faire.** Réserve mineure : le cadre de question choisi pilote le
vocabulaire de l'extraction IA, mais le protocole ne stocke pas un champ par
slot du cadre. La conformité n'en dépend pas.

### Domaine 2 · Exhaustivité et reproductibilité de la recherche — ✅

| Problème listé par CREST | État | Où |
|---|---|---|
| Reproductibilité de la stratégie | ✅ **au-delà du standard** | `Equation.translations` conserve la requête traduite **et** les surcharges écrites à la main, et `audit._search()` publie la requête *effectivement exécutée* par base. `Equation.status=frozen` + `frozen_at` datent le gel. `Import.filename` archive le fichier d'export brut. |
| La recherche peut manquer des preuves | ◐ | `GoldenRef` + `Equation.golden_results` = validation par rappel relatif sur un jeu de référence ; `SnowballRun` couvre les citations avant/arrière. **Manque** : pas de suivi de la littérature grise ni des registres d'essais (hors périmètre v1, ticket connu) |
| Validation de la stratégie | ✅ | le jeu doré nomme les références retrouvées et manquées par variante d'équation |

**Rien à faire dans ce chantier.** La littérature grise reste un ticket ouvert
indépendant.

### Domaine 3 · Critères d'éligibilité et processus de screening — ✅

| Problème listé par CREST | État | Où |
|---|---|---|
| Ajustement critères ↔ objectif | ✅ | les critères `I*`/`E*` sont dérivés du protocole et servent de codes de motif d'exclusion — un motif ne peut pas exister hors du protocole ([screening/reasons.py](../backend/app/services/screening/reasons.py)) |
| Garde-fous contre l'erreur de relecteur | ✅ **au-delà du standard** | `ScreeningConfig` : `n_reviewers`, `allocation` (all / dual / single_overlap), `decision_rule`, `maybe_policy`, `conflict_resolution` (consensus / arbitre) ; les votes des autres sont **invisibles avant le sien, verrouillé côté serveur** ; κ calculé sur les notices double-lues (`agreement_stats`) ; l'IA produit une suggestion, jamais un vote, et le triage en masse produit une liste validée item par item |
| Ambiguïté ou flou des critères | ◐ | rien ne teste l'ambiguïté. Le calibrage se fait de fait via κ et via les rounds, mais aucun **round pilote** formel n'est proposé |

**Rien de bloquant.** Un round pilote explicite serait un confort, pas une
condition de conformité : κ sur le round réel remplit la même fonction de
preuve.

### Domaine 4 · Appraisal critique des études incluses — ✅ *(chantier B)*

| Problème listé par CREST | État | Où / manque |
|---|---|---|
| Aucun instrument appliqué | ✅ | catalogue JBI complet par devis ([extraction/jbi.py](../backend/app/services/extraction/jbi.py)), sélectionné par `Record.study_design` |
| Instrument inapproprié (critères FEAT) | ✅ | registre d'instruments ([appraisal/instruments.py](../backend/app/services/appraisal/instruments.py)) : JBI et MMAT 2018 livrés, et une équipe déclare le sien (`AppraisalInstrument`, onglet Évaluation des paramètres). LitUbik n'embarque pas d'autre instrument tiers — c'est une question de licence, pas d'empaquetage |
| Instrument mal appliqué | ✅ | `AppraisalConfig` exige deux évaluateurs indépendants, `AppraisalConsensus` porte l'évaluation retenue **sans écraser** ce que chacun a dit (même séparation que `Conflict`/`Vote`), portée du désaccord et mode de résolution paramétrables ([appraisal/core.py](../backend/app/services/appraisal/core.py)). Le dossier d'audit énonce l'évaluation en double *ou son absence* |
| — | ✅ | Le jugement **par domaine de biais** est passé en tête de l'onglet ([appraisal/summary.py](../backend/app/services/appraisal/summary.py)) ; le « % de critères remplis » subsiste plus bas, étiqueté pour ce qu'il est — un indicateur de complétude, pas un classement de qualité |

**Fait : chantier B.**

### Domaine 5 · Validité des méthodes de synthèse — ✅ *(chantier C)*

| Problème listé par CREST | État |
|---|---|
| Décisions de groupement des preuves | ✅ `SynthesisPlan.grouping_md` / `grouping_changes_md` (SWiM 1a/1b) |
| Méthodes quantitatives | ✅ `SynthesisOutcome.synthesis_method` prise du tableau 2 de SWiM, avec sa justification et la question qu'elle peut traiter |
| Cadre narratif | ✅ la narrative IA reçoit désormais le plan déclaré et écrit dans ses limites ([narrative.py](../backend/app/services/results/narrative.py), `_synthesis_block`) |
| Méthodes qualitatives | ✅ méthode `thematic` disponible, avec le rappel que SWiM et GRADE ne couvrent pas la synthèse qualitative |

⚠ **Le point le plus sévère, corrigé.** `ReviewType.synthesis_method` affirmait,
pour toute revue de type `systematic`, `"narrative synthesis (Popay et al.,
2006)"`, et le §7 du prompt Methods ordonnait de le citer *verbatim*. Une équipe
ayant fait du comptage de votes lisait donc dans son propre manuscrit une
méthode qu'elle n'avait jamais employée — le grief que CREST classe en « autres
problèmes » (*« self-declared compliance with standard rather than analysis
thereof »*). Le dossier d'audit distingue maintenant `methods_declared` de
`method_default`, et le prompt écrit un `[TO COMPLETE]` visible quand rien n'est
déclaré au lieu de reprendre le défaut à son compte.

**Fait : chantier C.**

### Domaine 6 · Validité de l'évaluation de la certitude — ✅ *(chantier C)*

| Problème listé par CREST | État |
|---|---|
| Aucun cadre de certitude employé | ✅ registre de cadres (`none` \| `grade`, place laissée à CERQual) — [grade.py](../backend/app/services/synthesis/grade.py) |
| L'évaluation ne cible pas les bons critères | ✅ étapes 1 et 2 stockées (`intent`, `target`, `thresholds_md`) ; avertissement quand le cadre de question du projet indique une synthèse qualitative |
| Garde-fous contre l'erreur d'évaluateur | ✅ notation par évaluateur + ligne de consensus réservée à un admin ; les preuves de chaque domaine (appraisals des seules études contributives, dossier de recherche) sont affichées en regard du jugement |
| Critères mal interprétés / instrument mal appliqué | ✅ les 5 domaines de dégradation et les 3 de rehaussement sont explicités, chacun avec son aide ; la proposition arithmétique est affichée mais jamais appliquée |
| Méthode de résumé de la certitude globale | ✅ note finale par résultat + énoncé informatif GRADE guideline 26, et table Summary of Findings ([sof.py](../backend/app/services/synthesis/sof.py)) |

**Fait : chantier C.**

### « Autres problèmes » de CREST

| Item | État | Commentaire |
|---|---|---|
| Vérification linguistique recommandée | n/a | affaire de manuscrit |
| Accessibilité (perception des couleurs) | ✅ | palette Okabe-Ito sûre pour les daltonismes (`#0072b2`, `#009e73`, `#d55e00`) dans [palette.ts](../frontend/src/components/results/palette.ts) ; depuis le 14 oct. 2026 lint jsx-a11y, skip link, `prefers-reduced-motion`, régions `aria-live`, raccourcis désactivables, contraste AA ; déclaration WCAG 2.1 AA par critère dans [ACCESSIBILITY.md](ACCESSIBILITY.md) et audit axe-core automatisé (`tests/test_a11y_axe.py`, job CI `a11y`) depuis le 14 oct. 2026 |
| Standard de rapport présenté à tort comme guide de conduite | ◐ | à surveiller dans le prompt Methods : PRISMA rapporte, il ne conduit pas |
| Conformité auto-déclarée plutôt que démontrée | ✅ *(chantier E)* | les 42 items de PRISMA 2020 résolus contre la piste d'audit ([checklists/prisma2020.py](../backend/app/services/reporting/checklists/prisma2020.py)), export CSV, checklist SWiM quand elle s'applique. L'état **« pas fait »** est ce qui fait la valeur du fichier : une case vide se lit comme un oubli |
| Table des caractéristiques clés exigée | ✅ | item 17 de la checklist, résolu sur la table d'extraction ; une alerte se déclenche si aucune table n'existe pour un corpus inclus |
| Table Summary of Findings exigée | ✅ *(chantier C)* | une ligne par résultat, effectifs lus dans la table d'extraction, export CSV. Un résultat non noté affiche « non notée » plutôt qu'une cellule vide |
| Déclaration CRediT recommandée | ✗ | les contributions sont pourtant traçables : qui a screené, extrait, évalué. Candidat naturel à une génération depuis la piste d'audit — noté comme piste, hors périmètre de ce chantier |
| Résumé structuré exigé | ✗ | affaire de manuscrit (item 2, « à vous d'écrire ») |

---

## 2. SWiM — les neuf items de rapport

Rappel de périmètre : SWiM vise les revues d'**effets d'interventions** où la
méta-analyse d'estimations d'effet n'est pas possible pour au moins un résultat.
Ses items 1, 4, 7 et 9 restent cependant pertinents pour toute synthèse, ce que
le papier dit explicitement (« SWiM promotes the core principles needed for
transparent reporting of all synthesis methods including meta-analysis »).

| # | Item | État | Couverture prévue |
|---|---|---|---|
| 1a | Description et justification des groupes de synthèse | ✅ | `SynthesisPlan.grouping_md` |
| 1b | Changements de groupes postérieurs au protocole, et leur raison | ✅ | `SynthesisPlan.grouping_changes_md` + registre d'écarts ([deviations.py](../backend/app/services/reporting/deviations.py)), dont quatre détecteurs automatiques |
| 2 | Métrique standardisée par résultat, et méthode de transformation | ✅ | `SynthesisOutcome.metric` / `metric_rationale` |
| 3 | Méthode de synthèse employée et sa justification | ✅ | `SynthesisOutcome.synthesis_method` / `method_rationale`, valeurs prises du tableau 2 de SWiM ([methods.py](../backend/app/services/synthesis/methods.py)) |
| 4 | Critères de priorisation des études pour la synthèse | ✅ | `SynthesisPlan.prioritisation_md` |
| 5 | Méthode d'examen de l'hétérogénéité | ✅ | `SynthesisPlan.heterogeneity_md` |
| 6 | Méthode d'évaluation de la certitude | ✅ | `CertaintyAssessment` (GRADE, 5 étapes) |
| 7 | Méthodes de présentation (tables, forest/harvest plots…) | ✅ | `SynthesisPlan.presentation_md` déclare ce qui est employé et l'ordre de tri |
| 8 | Résultats : énoncé + certitude + études contributives | ✅ | table SoF + `SynthesisOutcome.record_ids` + narrative IA nourrie du plan |
| 9 | Limites de la synthèse | ✅ | `SynthesisPlan.limitations_md`, et la question que chaque méthode peut traiter est affichée au moment du choix |

**Le tableau 2 de SWiM est structurant** et sera repris tel quel dans l'UI :
chaque méthode de synthèse répond à une question différente, et confondre les
deux est l'erreur que l'item 9 demande de rapporter comme limite.

| Méthode | Question à laquelle elle répond | Données minimales |
|---|---|---|
| Méta-analyse et extensions | Quel est l'effet commun / moyen ? Quel modérateur ? | estimation + variance |
| Résumé des estimations d'effet | Quelle est l'étendue et la distribution des effets observés ? | estimation |
| Combinaison de valeurs *p* | Y a-t-il une preuve d'effet dans au moins une étude ? | direction + *p* précis |
| Comptage de votes sur la direction | Y a-t-il une preuve d'un effet quelconque ? | direction |

---

## 3. GRADE — les cinq étapes

| Étape | Ce qu'elle exige | État | Couverture prévue |
|---|---|---|---|
| 1 · Clarifier l'intention de la question | Causalité ou association ? Le papier montre que la même preuve donne « très faible » en causalité et « modérée » en association (exemple nocturie / mortalité) | ✅ | `SynthesisOutcome.intent` |
| 2 · Définir la cible de la notation | Sur quoi note-t-on : un effet quelconque, un effet important, une magnitude ? Seuils **pré-spécifiés** pour éviter le biais | ✅ | `SynthesisOutcome.target` + `thresholds_md` |
| 3 · Point de départ selon les devis | `high` si le devis disponible est le plus approprié à la question, `low` sinon | ✅ | proposé depuis `Record.study_design` × `intent` avec les décomptes qui le motivent, jamais appliqué sans validation |
| 4 · Évaluer chaque domaine | 5 domaines de dégradation (risque de biais, incohérence, imprécision, caractère indirect, biais de publication) × {aucune / sérieuse / très sérieuse préoccupation} ; 3 de rehaussement (grande magnitude, confusion résiduelle en sens inverse, relation dose-réponse) | ✅ | `CertaintyAssessment.domains` / `.upgrades` ; les appraisals des seules études contributives et le dossier de recherche sont affichés en regard des domaines qu'ils informent |
| 5 · Établir la note finale | high / moderate / low / very low, **par résultat**, avec transparence sur les décisions | ✅ | `CertaintyAssessment.final` — la proposition arithmétique est affichée à côté, et la divergence signalée plutôt que tue |
| + | Énoncés informatifs standardisés (GRADE guideline 26) | ✅ | gabarit selon `final` × `intent` × direction, éditable |

Deux points du papier qui contraignent l'implémentation :

- **La certitude est propre à chaque résultat**, calculée sur les seules études
  qui contribuent à ce résultat (6 études pour un résultat, 14 pour un autre
  dans l'exemple du papier). D'où `SynthesisOutcome.record_ids` : sans lui,
  l'évaluation porterait sur le corpus entier, ce qui serait faux.
- **La recherche exhaustive est ce qui fonde le domaine biais de publication.**
  LitUbik dispose du dossier de recherche : il sera affiché en regard du domaine
  plutôt que laissé à la mémoire de l'évaluateur.

---

## 3 bis. Contrainte : le cadre de question n'est plus supposé PICO

Le commit `72f3780` (« stop assuming PICO — a review says what it is ») fait du
type de revue et du cadre de question deux réglages de projet
([framing.py](../backend/app/services/framing.py)) : PICO, PICOS, SPIDER, SPICE,
PEO ou libre. Trois conséquences directes sur ce chantier.

**GRADE et SWiM ne couvrent pas tout ce que LitUbik sait décrire.** SWiM annonce
lui-même son périmètre : *« SWiM is not intended for use in reviews that
synthesise qualitative data »* (ENTREQ et eMERGe existent pour cela). GRADE note
la certitude d'estimations quantitatives d'effet ou d'association ; son
équivalent pour la synthèse qualitative est **GRADE-CERQual**. Imposer GRADE à
une revue cadrée SPIDER tomberait précisément sous le grief CREST *« the
assessment does not adequately target appropriate certainty criteria »*.

Le cadre de certitude est donc un **registre** (`none` | `grade`, extensible à
`cerqual`) et non un interrupteur, et l'UI signale l'inadéquation quand le cadre
de question du projet indique une synthèse qualitative — sans l'interdire :
c'est un avertissement, pas un verrou, l'équipe reste juge.

**Le vocabulaire du résultat de synthèse suit le cadre du projet.** « Résultat »
et « comparaison » sont du PICO ; SPIDER dit « Evaluation », PEO dit
« Outcome », SPICE dit « Evaluation », et SPIDER comme PEO n'ont pas de
comparateur. Le libellé de l'entité et la présence du champ « comparaison » se
lisent dans `framing.framework(project).slots`, comme le fait déjà
`extraction_schema()`.

**La méthode de synthèse déclarée prime sur celle du type de revue.** Le dossier
d'audit porte déjà `framing.synthesis_method`, et le prompt Methods ordonne de
le citer verbatim. Pour `review_type=systematic` ce libellé vaut en dur
« narrative synthesis (Popay et al., 2006) » : une équipe ayant fait du comptage
de votes verrait sa méthode mal nommée dans son propre manuscrit. Le chantier C
ajoute `synthesis.method_declared`, qui prend le pas, et laisse le libellé du
type de revue comme défaut explicite.

## 4. Ce qui est décidé

Cinq chantiers, tous **activables par projet et éteints par défaut** — un projet
existant ne change pas de comportement.

| Chantier | Comble | Statut |
|---|---|---|
| **A** · Enregistrement de la revue (registre, numéro, date, URL) | PRISMA 24a, CREST « autres » | ✅ fait |
| **B** · Appraisal : double évaluation paramétrable, résolution de désaccord, jugement par domaine, registre d'instruments ouvert | CREST domaine 4 | ✅ fait |
| **C** · Déclaration de synthèse (SWiM) + certitude (GRADE) + table SoF | CREST domaines 5 et 6, SWiM 1–9, GRADE 1–5 | ✅ fait |
| **D** · Registre des écarts au protocole (détectés + déclarés) | SWiM 1b, PRISMA 24c, cohérence protocole ↔ méthodes appliquées exigée par CREST | ✅ fait |
| **E** · Checklists PRISMA 2020 / SWiM pré-remplies par la piste d'audit + alertes CREST | CREST « conformité auto-déclarée » | ✅ fait |

Le plan d'implémentation détaillé est dans le fichier de plan de session ; ce
document-ci est la grille de recette.

### Ce qui est explicitement écarté

- **Reproduire la notation 1–5 de CREST dans l'app.** La note est un jugement
  éditorial, pas une propriété mesurable du projet ; l'auto-attribuer serait
  précisément la conformité auto-déclarée que l'outil sanctionne. LitUbik
  signale les *déclencheurs* que CREST énumère, pas des scores.
- **Le résumé structuré et la vérification linguistique** : affaires de
  manuscrit, hors du périmètre d'un outil de pipeline.
- **La littérature grise et les registres d'essais** : ticket indépendant,
  déjà identifié comme *future work* dans la roadmap.
- **La déclaration CRediT** : techniquement dérivable de la piste d'audit, gardée
  comme piste pour plus tard.

---

## 5. Ce que les chantiers ont ajouté, et ce qu'ils ont refusé d'ajouter

Trois refus valent d'être notés, parce qu'ils sont des décisions et non des
oublis.

**Aucune note CREST auto-attribuée.** Reproduire la notation 1–5 aurait
transformé un instrument d'éditeur en instrument d'auteur. LitUbik signale les
*problèmes* que CREST énumère — aucun instrument d'évaluation appliqué, aucun
cadre de certitude, évaluateur unique, équation jamais gelée — et seulement
quand ils sont présents. Une note est un jugement ; une évaluation manquante
est un fait.

**Aucun instrument tiers au-delà de JBI et du MMAT.** Ces deux-là sont
embarqués parce que leurs conditions d'utilisation le permettent, avec leur
citation (voir NOTICE). Embarquer RoB 2 ou AMSTAR-2 dans un dépôt AGPL diffusé
publiquement dépend de l'accord de leurs auteurs, pas de l'outillage. Le
registre accueille ces instruments ; c'est le constructeur d'instrument maison
qui couvre le besoin hors santé sans redistribuer le travail d'un tiers.

**Aucun détecteur d'écart sur les colonnes d'extraction.** `ExtractionColumn`
n'a pas d'horodatage : le seul « signal » disponible se serait déclenché pour
tout projet ayant commencé une extraction, changement ou non. Un registre qui
crie au loup est un registre que personne ne lit. Ce changement-là se déclare à
la main, et la documentation le dit.

### Le principe commun

Partout où l'application sait quelque chose, elle le montre avec sa provenance
et s'arrête là. Le point de départ GRADE est *proposé* depuis les devis des
études contributives, avec les décomptes qui le motivent ; la note arithmétique
est *affichée à côté* de la décision de l'évaluateur, et la divergence signalée
plutôt que tue ; un signal d'écart est une *question* — « ceci s'est produit,
pourquoi ? » — que seul un humain convertit en écart déclaré. La raison est
toujours la part que l'équipe seule détient, et c'est précisément celle que les
trois standards réclament.
