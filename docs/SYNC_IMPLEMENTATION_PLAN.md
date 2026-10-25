# Plan d'implémentation — Collaboration inter-instances (option B puis C)

> Décision du 2026-07-17 :
> **option B** (échange asynchrone par fichiers, topologie coordinateur/satellites)
> **puis option C** (transport automatisé via dossier partagé), plus le packaging
> « un clic » pour le mode local.

**Décisions produit actées :**

| Sujet | Décision |
|---|---|
| Clés API / accès institutionnels | Logique collaborative : chaque reviewer choisit, clé par clé, de la **garder privée** ou de la **partager avec le projet** (utilisable alors par les jobs du coordinateur : full-text, IA…). Toujours chiffré, jamais en clair. |
| Votes IA | Les satellites **peuvent** en générer localement ; ils voyagent dans les exports/imports avec leur provenance, pour le suivi. |
| Import de records | **Coordinateur (admin projet) uniquement** — les satellites ne peuvent pas importer de références (sinon la dédup diverge). |
| PDF dans l'instantané | **Inclus par défaut** (case cochée), désactivable à l'export. |
| Packaging local | Le plus simple pour l'utilisateur : **un clic → l'app s'ouvre dans le navigateur**. |

---

## Vue d'ensemble des phases

| Phase | Contenu | Dépend de | Estimation |
|---|---|---|---|
| **0** | Identité inter-instances (UUID, instance ID, horodatage) | — | 1-2 j |
| **1** | Instantané projet : export + import (= archive M11) | 0 | 4-6 j |
| **2** | Paquets de contributions : export + import + provenance | 1 | 3-5 j |
| **3** | Ressources partagées (clés API, accès institutionnels) | 2 | 2-3 j |
| **4** | Option C : sync automatique par dossier partagé | 2 (3 conseillé) | 4-5 j |
| **5** | Packaging « un clic » + Docker hébergé + doc diffusion | aucune (parallélisable) | 3-5 j |

**Ordre de livraison (révisé 2026-07-17, après livraison de B) : 0 → 1 → 2
(= option B) → 3 → 4 (= option C) → 5 (packaging).** Pas de diffusion imminente :
on termine le moteur de sync d'abord, le packaging ferme la marche pour n'être
fait qu'une fois.

**Fin de phase 2 = option B livrée** (parité ReviQ + multi-rounds/kappa/allocation).
**Fin de phase 4 = option C livrée.**

---

## Phase 0 — Identité inter-instances (fondation)

Les PK actuelles sont des entiers auto-incrémentés, sans signification hors de
l'instance. Tout ce qui est référencé entre instances doit porter un identifiant
stable.

**Schéma (une migration Alembic) :**

1. Colonne `uuid` (String(36), unique, indexée, backfill `uuid4()`) sur les tables
   structurelles et référencées : `projects`, `records`, `sources`, `imports`,
   `equations`, `concepts`, `protocols`, `golden_refs`, `extraction_columns`,
   `screening_configs`, `snowball_runs`. (Les tables de contribution — votes, JBI,
   extraction_values, annotations — n'ont pas besoin d'UUID : leur clé naturelle
   est `(uuid du record, étape, round, e-mail de l'auteur[, colonne])`.)
2. Les **utilisateurs sont appariés par e-mail** (déjà unique) — aucun changement.
3. `updated_at` sur `votes` et `pdf_annotations` (nécessaire à la règle
   « le plus récent gagne » ; les autres tables de contribution l'ont déjà).
4. Provenance des votes IA : colonne `generated_by` (String, e-mail de l'utilisateur
   dont l'instance a généré la suggestion, NULL = coordinateur/local historique).
5. Table `instance_meta` (ou entrée settings) : `instance_id` (uuid généré au premier
   démarrage), utilisé dans toutes les provenances.
6. Sur `projects` : `sync_role` (`coordinator` | `satellite`, défaut `coordinator`),
   `coordinator_email`, `coordinator_instance_id`, `snapshot_version` (int, version
   du dernier instantané publié/importé).

**Critère de fin :** migration appliquée sur une base existante sans perte ;
`instance_id` stable entre redémarrages ; tests unitaires du backfill.

---

## Phase 1 — Instantané projet (coordinateur → satellites)

Un seul artefact, deux usages : **bootstrap/mise à jour d'un satellite** et
**archive de réplication OSF-ready** (jalon M11 — même code, un livrable en avance).

### Format de l'archive (`.litubik.zip`)

```
manifest.json      # format_version, app_version, révision Alembic, project_uuid,
                   # snapshot_version (incrémenté à chaque export), exported_at,
                   # exporter (email + instance_id), content_flags {pdfs: bool}
data.json          # toutes les lignes du projet, sérialisées par UUID/e-mail :
                   #  - structurel : protocole(s), concepts, équations+counts,
                   #    golden refs, sources, imports, records (+dedup),
                   #    citation_edges, screening_configs, assignments,
                   #    extraction_columns/config, fulltext (statuts, chemins)
                   #  - contributions DE TOUS les reviewers : votes (humains + IA
                   #    avec generated_by), conflits+résolutions, JBI, extraction
                   #    values, annotations — le satellite voit l'état complet
                   #    (kappa, conflits) comme en instance partagée
                   #  - membres : e-mails + rôles (jamais les mots de passe)
                   #  - JAMAIS : credentials (phase 3 à part), jobs, tickets
files/
  ris_raw/...      # fichiers d'import bruts (audit PRISMA)
  protocol/...     # uploads du protocole
  pdfs/...         # optionnel — case « Inclure les PDF » cochée par défaut
```

Toutes les FK internes sont réécrites en UUID à l'export et résolues à l'import.
La sérialisation est générique (liste déclarative `SYNC_TABLES` : table → colonnes →
clés de résolution), pour que l'ajout d'une table future soit une ligne, pas un
nouveau sérialiseur.

### Import (deux modes)

- **Création** : le projet n'existe pas localement (par `project_uuid`) → création en
  `sync_role=satellite`. Les droits locaux = le rôle du membre dont l'e-mail
  correspond au compte connecté ; si l'importeur n'est pas membre → lecture seule +
  avertissement.
- **Mise à jour** : le projet existe → remplacement de l'état structurel et des
  contributions *des autres*, préservation des contributions locales de
  l'utilisateur : une ligne locale est conservée si son record existe toujours
  (remappage vers le canonique si le record a été fusionné par la dédup), sinon mise
  en **quarantaine** listée dans le rapport d'import. Pour les lignes présentes des
  deux côtés (mes votes revenus via l'instantané) : le plus récent `updated_at` gagne.

**Verrouillage satellite** (backend, pas seulement UI) : sur un projet
`sync_role=satellite`, les endpoints structurels (imports de records, dédup,
protocole, équations, configs, résolution de conflits, snowballing) renvoient 403
« Géré par le coordinateur » ; l'UI affiche le bandeau correspondant.

- **Garde-fou schéma** : l'import refuse une archive dont la révision Alembic est
  plus récente que celle de l'instance (« mettez LitUbik à jour »), accepte les plus
  anciennes (les migrations locales s'appliquent aux données importées).

### API & UI

- `POST /api/projects/{id}/sync/export-snapshot` (job + SSE, ZIP en téléchargement ;
  case PDF) ; `POST /api/projects/import-snapshot` (upload, job + SSE, rapport).
- UI : page **Synchronisation** dans le projet (visible admin/coordinateur ; les
  satellites y voient leur partie phase 2) ; bouton « Importer un projet » sur la
  liste des projets.

**Critère de fin :** aller-retour complet sur le projet de démo — export chez A,
import chez B (base vierge), ré-export chez B, diff des `data.json` = identique ;
mise à jour d'instantané préservant des votes locaux ; PRISMA/kappa identiques des
deux côtés ; import refusé proprement si révision schéma plus récente.

---

## Phase 2 — Paquets de contributions (satellite → coordinateur)

### Format (`.litubik-contrib.json`, zippé si annotations volumineuses)

```
manifest   : format_version, project_uuid, author (email + instance_id),
             seq (compteur croissant par projet/auteur), based_on_snapshot_version,
             exported_at
votes      : TOUS mes votes du projet (export complet, idempotent) + les votes IA
             générés sur mon instance (generated_by = mon e-mail)
jbi        : mes appréciations JBI
extraction : mes extraction_values
annotations: mes annotations PDF
skips      : mes assignments.skipped_at (état de file)
```

Export **complet** à chaque fois (pas de delta) : quelques centaines de Ko pour des
milliers de votes, et l'import devient trivialement idempotent — rejouer un vieux
paquet ne casse rien, le `seq` sert uniquement au suivi et à l'option C.

### Règles de fusion à l'import (par table)

| Données | Règle |
|---|---|
| Votes humains | Upsert sur `(record_uuid, stage, round, email)` ; le plus récent `updated_at` gagne ; jamais de suppression. |
| Votes IA | **Insertion si absent** sur `(record_uuid, stage, round, is_ai)` — s'il existe déjà un vote IA (généré par le coordinateur ou un autre satellite), l'existant est conservé et le doublon est listé dans le rapport avec sa provenance. |
| JBI, extraction values | Upsert, le plus récent `updated_at` gagne. |
| Annotations PDF | **Remplacement par auteur** : les annotations locales de cet auteur sont remplacées par le contenu du paquet (gère naturellement les suppressions, sans tombstones). |
| Skips | Upsert simple. |

Après import : **recalcul des conflits et de la progression** pour chaque
`(stage, round)` touché (réutilise la détection existante de
`services/screening/core.py`), recalcul kappa à l'affichage (déjà dérivé).
Chaque ligne importée porte `imported_from` (email/instance/seq/date) — l'équivalent
du `source_file` de ReviQ.

**Garde-fous :** paquet d'un non-membre → refus ; `based_on_snapshot_version` en
retard → avertissement (« Bob travaille sur la v2, vous êtes en v4 ») mais import
quand même, les UUID absents partant en quarantaine listée ; double import → no-op.

L'import de contributions est permis sur **toute** instance où l'utilisateur est
admin du projet — y compris un satellite important le paquet d'un autre satellite
(inoffensif : mêmes règles, mêmes résultats).

### UI

Page Synchronisation : « Exporter mes contributions » / « Importer des
contributions » + **journal des échanges** (qui, quand, quel seq, combien de lignes,
quarantaines) + rapport d'import détaillé après chaque import.

**Critère de fin :** test e2e à deux instances (deux data dirs/DB en pytest) —
scénario complet coordinateur/satellite (snapshot → votes des deux côtés →
paquet → import → conflits + kappa **identiques au même scénario joué sur une
instance unique**) ; idempotence (double import) ; paquet périmé avec dédup
intervenue entre-temps (remap + quarantaine corrects).

---

## Phase 3 — Ressources partagées (clés API & accès institutionnels)

### Modèle de partage

- `LLMCredential` et `DatabaseCredential` : + `owner_user_id`, + `shared` (bool,
  défaut **false** = privé). **Seules les clés en scope projet voyagent.**
- *Révision à l'implémentation (2026-07-17)* : les entrées `institutions` de
  `FulltextConfig` (identifiants EZProxy/CAS) sont **exclues du partage** — ce
  sont des identifiants personnels d'université (chartes d'usage) et leur
  gestion est locale à chaque instance. Le cas visé (clé API institutionnelle
  type Scopus/IEEE) est couvert par les clés de bases en scope projet.
- Résolution (jobs IA, connecteurs, full-text) mise à jour :
  explicite > projet-partagé > mes clés > globale d'instance. En mode hébergé,
  ce modèle s'applique immédiatement (aujourd'hui les clés projet sont de facto
  communes ; elles deviennent « privées sauf partage » — migration : les clés
  existantes restent au créateur du projet, partagées = true pour ne rien casser).
- UI (réglages IA / bases / full-text) : interrupteur par clé
  « **Partager avec les membres du projet** » + badge « partagée par bob@… » sur les
  clés reçues. Le propriétaire peut révoquer à tout moment.

### Transport chiffré

Le Fernet actuel est dérivé du secret d'instance → illisible ailleurs. Pour le
transport :

- Le coordinateur définit une **phrase secrète de projet** (communiquée oralement /
  par un canal séparé), stockée localement chiffrée par l'instance de chacun.
- Les clés partagées voyagent dans un bloc `credentials.enc` du paquet de
  contributions / de l'instantané : Fernet(clé dérivée PBKDF2-SHA256(phrase, sel,
  ≥600k itérations)). **Jamais en clair, ni au repos ni en transit.**
- À l'import : déchiffrement avec la phrase, re-chiffrement au Fernet local,
  provenance conservée. Sans phrase saisie : le bloc est ignoré (le reste du paquet
  s'importe normalement).
- Révocation : dé-partage → « tombstone » dans le prochain export → suppression chez
  les autres. Documenté honnêtement : partager une clé = faire confiance aux membres
  (quiconque a eu le fichier + la phrase a pu lire la clé).

**Critère de fin :** Bob partage sa clé Scopus ; Alice lance une recherche de counts
avec ; Bob révoque ; après le paquet suivant, la clé a disparu chez Alice. Aucun
octet de clé en clair dans aucun fichier échangé (test grep sur les artefacts).

---

## Phase 4 — Option C : dossier partagé

### Structure du dossier (Nextcloud / OneDrive / Drive / Dropbox…)

```
<dossier choisi>/
├── litubik-manifest.json        # project_uuid, coordinateur (email+instance),
│                                # snapshot_version courante, format_version
├── snapshots/v<N>.litubik.zip
└── contributions/<email>/<seq>.litubik-contrib.json
```

Le client de synchronisation de l'OS fait le transport ; LitUbik ne fait que
lire/écrire des fichiers locaux. Écritures atomiques (fichier `.tmp` puis renommage) ;
fichiers immuables une fois écrits (append-only par `seq`).

### Comportements

- **Réglage par projet** : chemin du dossier + interrupteur « publication
  automatique » (coordinateur).
- **Scanner périodique** : tâche de fond (extension légère du job runner : une tâche
  asyncio périodique, toutes les 5 min + bouton « Synchroniser maintenant ») :
  - toute instance : dépose mes contributions si elles ont changé depuis le dernier
    dépôt (hash) ; importe les nouveaux paquets des autres (curseur par auteur dans
    une table `sync_state`) ;
  - coordinateur : publie un instantané quand l'état structurel a changé
    (compteur de révision incrémenté par les endpoints structurels) — automatique si
    l'interrupteur est actif, sinon badge « instantané en retard » + bouton
    « Publier » ;
  - satellite : nouvel instantané détecté → notification « Mise à jour disponible »,
    application **sur confirmation** (l'update préserve les contributions locales,
    mais on ne change pas l'état sous les pieds de l'utilisateur sans prévenir).
- **UI** : bandeau d'état par projet (« Dernière sync il y a 4 min · 1 paquet
  importé · instantané v5 ») + historique (le journal de la phase 2, alimenté
  automatiquement).

**Critère de fin :** deux instances pointées sur un même dossier local (simulé en
test) convergent sans action manuelle : votes de B visibles chez A ≤ 1 cycle de
scan ; coupure/reprise du « cloud » (fichiers partiels) sans corruption ;
double-coordinateur impossible (le manifest fait foi, avertissement sinon).

---

## Phase 5 — Packaging & diffusion

### Mode local « un clic »

- **Livrable** : une application de bureau par OS (PyInstaller ; Windows d'abord —
  `LitUbik.exe` + installeur Inno Setup, puis macOS `.app`, Linux AppImage/pipx) qui :
  1. crée/ouvre le répertoire de données utilisateur (`%LOCALAPPDATA%/LitUbik`) ;
  2. **génère et persiste un `LITUBIK_SECRET_KEY` aléatoire au premier lancement**
     (remplace le défaut dev — indispensable avant diffusion, les clés API stockées
     en dépendent) ;
  3. applique les migrations Alembic ;
  4. démarre uvicorn sur `127.0.0.1:<port libre>` (frontend `dist/` déjà servi par
     le backend — `app/main.py`) ;
  5. ouvre le navigateur ; icône de zone de notification « Quitter LitUbik ».
- Variante développeurs/serveurs : `pipx install litubik && litubik run`.
- Premier lancement : écran de création du premier compte (existant — premier compte
  = admin d'app).

### Mode hébergé

- Image Docker unique multi-stage (build Node du frontend → image Python) publiée
  en registry ; `docker-compose.yml` finalisé avec option Postgres ; doc HTTPS
  (reverse proxy), sauvegardes, variables d'env.

### Diffusion

- CI GitHub Actions : tests + build des artefacts (exe/app/image) à chaque release.
- Doc utilisateur courte : « Collaborer entre deux universités » (scénarios B et C
  pas à pas), « Héberger LitUbik », FAQ sécurité (que contient un paquet, que
  voyage-t-il, où sont les clés).
- **Licence : AGPLv3** (actée 2026-07-17) — copyleft adapté aux apps serveur :
  quiconque héberge une version modifiée doit publier ses modifications. Ajouter
  `LICENSE` + en-têtes + mention dans le README lors de cette phase.

**Critère de fin :** sur une machine Windows vierge (sans Python/Node/Docker) :
télécharger, double-cliquer, créer un compte, importer un instantané, voter,
exporter ses contributions. Zéro terminal.

---

## Risques & points de vigilance

- **Horloges** : les règles « le plus récent gagne » comparent des horodatages de
  machines différentes. Acceptable ici (on compare presque toujours des versions de
  la *même* personne sur la *même* machine) ; le `seq` par auteur couvre l'ordre des
  paquets. À documenter, pas à sur-ingénierer.
- **Dédup mouvante** : un vote satellite sur un record devenu doublon → remap vers le
  canonique ; si un vote y existe déjà, le plus récent gagne, l'autre part au rapport.
  Cas testé explicitement (e2e phase 2).
- **Divergence de schéma** : manifest = révision Alembic ; import refusé si
  l'archive vient d'un LitUbik plus récent. Les migrations doivent rester linéaires.
- **Poids des instantanés** : PDF inclus par défaut → archives potentiellement
  volumineuses ; export en job + streaming, et la case reste décochable.
- **Données personnelles** : les paquets contiennent des e-mails ; à mentionner dans
  la doc (RGPD : données de collaboration scientifique, base légitime, mais le dire).

## Stratégie de test

- Unitaires : sérialisation aller-retour par table, résolution UUID/e-mail, règles
  de fusion (chaque ligne du tableau phase 2), dérivation de clé phase 3.
- **E2E deux instances** (pytest, deux data dirs + DB) : le scénario
  coordinateur/satellite complet, avec l'assertion clé : *conflits, kappa et PRISMA
  strictement identiques au même scénario joué sur une instance unique*.
- Idempotence et rejeu systématiques (double import de tout).
- Smoke test manuel scripté avant chaque release (checklist dans la doc).

---

## Décisions

| Date | Sujet | Décision |
|---|---|---|
| 2026-07-17 | Architecture | B puis C, topologie coordinateur/satellites |
| 2026-07-17 | Clés API | Partage opt-in par le propriétaire, chiffré |
| 2026-07-17 | Votes IA | Générables sur satellite, synchronisés avec provenance |
| 2026-07-17 | Records | Import par le coordinateur uniquement |
| 2026-07-17 | PDF | Inclus dans l'instantané par défaut (décochable) |
| 2026-07-17 | Packaging | Un clic → navigateur (PyInstaller), Docker pour l'hébergé |
| 2026-07-17 | Ordre de livraison | ~~0 → 1 → 2 (B) → 5 → 3 → 4~~ révisé après B : **0 → 1 → 2 → 3 → 4 → 5** (packaging en dernier, pas de diffusion imminente) |
| 2026-07-17 | Transport des clés | Phrase secrète de projet (PBKDF2 + Fernet), saisie une fois par instance |
| 2026-07-17 | Licence | **AGPLv3** |
| 2026-07-17 | **Livraison** | **Toutes les phases (0→5) livrées** sur la branche Synchronisation. Institutions EZProxy exclues du partage (identifiants personnels) ; exe packagé sans playwright (tiers full-text optionnels). |
