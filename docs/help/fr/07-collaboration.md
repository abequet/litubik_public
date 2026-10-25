# Collaboration et synchronisation

Deux façons de travailler en équipe :

## Même instance (le plus simple)

Si tout le monde peut atteindre le même serveur LitUbik (serveur de labo,
machine partagée), invitez simplement les membres au projet — tout le monde
travaille sur les mêmes données en direct.

## Instances séparées (coordinateur / satellites)

Quand chaque reviewer fait tourner son propre LitUbik (p. ex. l'exe Windows
sur son portable), une instance est le **coordinateur** — elle possède la
structure du projet (protocole, équations, rounds, réglages) — et les
autres tiennent des copies **satellites** (marquées *sat*).

- Le coordinateur **publie des snapshots** du projet ; les satellites les
  importent et récupèrent structure, références et PDF à jour.
- Les satellites **exportent leurs contributions** (votes, notes,
  annotations, extraction) vers le coordinateur, qui les fusionne.
- Sur un satellite, les actions structurelles (modifier le protocole,
  lancer des recherches…) sont verrouillées — elles appartiennent au
  coordinateur.
- Les **lots** de screening (lots pondérés, voir *Screening*) font partie
  de la structure : le coordinateur les prévisualise et les démarre ; les
  satellites reçoivent les lots et les attributions de chaque relecteur avec
  le snapshot, et leurs votes remontent comme d'habitude. Le CSV de
  répartition se télécharge sur n'importe quelle instance.

## Deux modes de transport

- **Dossier partagé** (recommandé) : le coordinateur lie le projet à un
  dossier synchronisé par Nextcloud/Drive/Dropbox ; publication et import
  deviennent automatiques en arrière-plan. Un reviewer rejoint en une étape
  avec *Join via a shared folder* sur la page d'accueil.
- **Zips manuels** : exportez un snapshot en `.zip`, envoyez-le comme vous
  voulez, l'autre côté utilise *Import a project*. Fonctionne sans aucune
  infrastructure (e-mail, clé USB).

## Phrase secrète du projet (sécurité du dossier partagé)

Définissez une **phrase secrète de projet** sur la page Synchronisation et
communiquez-la à chaque co-reviewer hors du dossier (chat, téléphone — pas via
le dossier lui-même). Elle sert à deux choses :

- elle authentifie chaque paquet déposé dans le dossier partagé : seules les
  contributions des vrais co-reviewers sont importées automatiquement — un
  fichier déposé par quelqu'un d'autre ayant accès au dossier est refusé ;
- elle chiffre les clés API partagées qui circulent entre les instances.

Sans phrase secrète, l'import automatique depuis le dossier partagé est
désactivé (l'import manuel de zip reste possible). Choisissez au moins 12
caractères — le blob chiffré voyage dans le dossier, donc une phrase faible
pourrait être attaquée hors-ligne par quiconque peut la lire.

Seul l'administrateur de l'instance peut rattacher les clés IA globales de
l'app à un projet comme clés partagées (boutons *Partager ma clé …*) : ce sont
ses clés. Un autre admin de projet partage plutôt une clé à lui.

## Temps de travail (admin du projet)

LitUbik mesure le **temps actif** que chaque membre passe sur les pages de
travail — screening (titre/résumé, texte intégral, conflits), dédoublonnage,
extraction et évaluation. Tant qu'une de ces pages est ouverte, visible et
utilisée, le navigateur se signale au serveur toutes les 30 secondes ; le
serveur regroupe ces battements en sessions par étape. Rien sur la référence
à l'écran n'est enregistré : seulement l'étape et la durée.

Tout le monde en est informé : le panneau **Membres** de la carte du projet
explique la mesure et montre à chaque membre son **propre total**. Le détail
par reviewer est réservé à l'**admin du projet**, sur la page *Temps de
travail* de la barre latérale :

- un tableau reviewer × étape, avec le total et le **temps médian par
  référence criblée** (titre/résumé et texte intégral), le chiffre
  habituellement rapporté quand on évalue un outil de screening ;
- les minutes actives par semaine ;
- une bascule **mesuré / estimé**. *Estimé* reconstitue les sessions à
  partir des horodatages que les reviewers laissent déjà (votes, arbitrages,
  cellules extraites, évaluations) : un silence plus long que la *coupure
  d'inactivité* (10 min par défaut) ferme une session, et chaque acte est
  crédité au plus du *temps max par acte* (5 min). Utile pour le travail
  antérieur à cette fonctionnalité, ou comme contrôle de la mesure ;
- un export CSV (reviewer × étape × jour).

Les sessions voyagent avec les contributions du reviewer entre un satellite
et le coordinateur, comme les votes. Jamais un temps par référence
individuelle n'est affiché, exporté ni synchronisé — seulement des agrégats.

## Sauvegardes et restauration

Un snapshot est aussi une sauvegarde complète du projet. Exportez-en un depuis
la page Synchronisation à chaque étape importante (fin d'un round de tri,
avant une réinitialisation…) et gardez le `.zip` en lieu sûr.

Pour revenir à une sauvegarde :

- **Le projet est encore sur l'instance** : Synchronisation → *Restaurer
  depuis un instantané (sauvegarde)*. Le projet entier est remplacé par le
  contenu de l'archive — tout ce qui a été fait depuis cet export est perdu —
  et il reste l'instance de référence (coordinateur).
- **Projet supprimé, ou instance neuve** : page Projets → *Import a project*
  → choisissez *Ma propre sauvegarde — la restaurer*. Le projet est recréé
  comme coordinateur.

Les deux cas concernent des archives exportées depuis **votre propre**
projet. Pour recevoir la mise à jour d'un coordinateur sur une copie
satellite, utilisez plutôt *Apply a received snapshot* — ce chemin conserve
vos votes locaux ; une restauration, volontairement, non.

## Archive de réplication publique (à publier avec un article)

Un instantané est une copie de travail pour votre équipe. Il contient des
contenus que vous pouvez utiliser mais pas redistribuer : les PDF des textes
intégraux, les résumés (ils appartiennent aux éditeurs, même quand un index
ouvert les diffuse), les exports bruts des bases commerciales (Scopus, Web of
Science, IEEE Xplore, ACM… interdisent leur redistribution) et vos clés d'API
partagées. Ne le publiez pas.

Pour déposer la revue sur OSF ou Zenodo, ou en matériel supplémentaire,
utilisez Synchronisation → **Archive de réplication publique** → *Exporter
l'archive publique*. L'archive (`…_public.zip`) garde :

- les métadonnées bibliographiques (titre, auteurs, année, revue, DOI) ;
- le protocole, les équations, les décomptes et le rappel ;
- le dédoublonnage, les votes, les conflits, les motifs et les suggestions IA ;
- l'évaluation critique, l'extraction, les déviations et le journal d'usage de l'IA.

Elle exclut les PDF, les résumés et leurs traductions IA, les exports bruts des
bases, les passages cités par les annotations de PDF (vos notes restent), les
clés d'API partagées et les invitations en attente. Elle retire aussi des
traces qui en disent plus sur les personnes que sur la revue : les sessions de
travail des relecteurs, les diagnostics de récupération, le nom de
l'établissement dont l'accès a récupéré un article (le type de source
« institution » reste) et toute adresse e-mail qu'une base a laissée dans un
champ auteur. Elle ne change pas la version de l'instantané.

Un `README.txt` à la racine du zip indique ce que contient l'archive, ce qui en
a été retiré et comment la réimporter. LitUbik ne choisit pas de licence pour
l'archive : indiquez à côté la licence de votre propre contribution (décisions,
codage, protocole), par exemple CC BY 4.0. Les métadonnées bibliographiques
restent soumises aux conditions des bases interrogées.

Importée dans LitUbik (*Import a project* → *Ma propre sauvegarde — la
restaurer*), elle reproduit les décomptes PRISMA et les statistiques d'accord.
Les textes intégraux apparaissent « à récupérer » : qui reproduit la revue les
récupère avec ses propres accès.

**Pseudonymiser les relecteurs** est une option, car les revues diffèrent.
Elle remplace chaque adresse e-mail de l'archive par
`reviewer-N@pseudonymized.invalid` et le nom des relecteurs par « Reviewer N ».
Les noms que vous avez saisis vous-même dans les notes libres (notes de
résolution de conflit, déviations, commentaires) ne sont pas détectés :
relisez-les avant de publier.

### Sauvegarde de l'instance entière (admin de l'application)

Les snapshots de projet couvrent un projet à la fois. La page **Sauvegarde de
l'instance** (section Administration de la barre latérale) télécharge toute
l'instance en un zip : la base de données complète (tous les projets et tous
les comptes), la clé secrète auto-générée, et en option tous les fichiers
stockés (PDF, RIS bruts, protocoles). Gardez la clé secrète avec la
sauvegarde — sans elle (`LITUBIK_SECRET_KEY` ou `data/secret.key`), une base
restaurée ne peut plus déchiffrer les clés API qu'elle contient.

Pour une sauvegarde récurrente, lancez `scripts/backup_litubik.ps1` (dans le
dépôt) depuis n'importe quelle machine qui atteint l'instance : il se
connecte avec un compte superadmin, télécharge le zip, le vérifie et ne garde
que les copies les plus récentes (3 par défaut). Son option `-Install`
l'enregistre comme tâche planifiée Windows quotidienne.

Pour restaurer : arrêtez l'app, remettez `litubik.db` (et `secret.key`) du
zip dans le dossier `data/`, supprimez les fichiers `litubik.db-wal` /
`litubik.db-shm` éventuels, décompressez `storage/` à côté, redémarrez.

Tout se gère depuis la page **Synchronisation** du projet.
