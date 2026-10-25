# Déployer LitUbik sur un serveur (guide pas-à-pas)

L'usage local en un clic n'a besoin de **rien** de tout ceci : lancez
`LitUbik.exe` (version packagée) ou `start.bat` (depuis les sources). Ce
document couvre les déploiements hébergés : la **démo publique sur Railway**
(section principale, expliquée pour débutant) et le serveur de labo
(docker-compose).

---

## Notions de base (si les mots « volume », « variable d'environnement »… ne vous parlent pas)

- **Image Docker** : une « boîte » qui contient LitUbik et tout ce qu'il faut
  pour le faire tourner (Python, le frontend compilé…). Le fichier
  `Dockerfile` à la racine du repo est la recette de cette boîte. Railway
  sait lire cette recette tout seul.
- **Conteneur** : la boîte en train de tourner. Si on la redémarre, tout ce
  qui était écrit *dedans* est perdu…
- **Volume** : …sauf ce qui est écrit sur un volume : un « disque dur »
  branché au conteneur, qui survit aux redémarrages. LitUbik écrit tout
  (base de données, PDF) dans le dossier `/data` → ce dossier DOIT être un
  volume.
- **Variable d'environnement** : un réglage donné au conteneur au démarrage,
  sous forme `NOM=valeur`. C'est comme ça qu'on active le mode démo, qu'on
  donne la clé secrète, etc. Sur Railway, ça se règle dans un onglet
  « Variables ».
- **Railway** : un hébergeur cloud. On lui montre le repo GitHub, il
  construit l'image Docker et la fait tourner sur une URL publique.
  Plan « Hobby » ≈ 5 $/mois.

## Règles d'or (à lire une fois, valables partout)

1. **`LITUBIK_SECRET_KEY` se génère UNE fois et ne change JAMAIS.**
   Cette clé signe les sessions ET chiffre toutes les clés API stockées
   (Scopus, IA…). Si elle change, toutes les clés stockées deviennent
   illisibles et chacun devra les re-saisir. Pour en générer une, dans un
   terminal (n'importe quel Python) :

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Copiez le résultat quelque part de sûr (gestionnaire de mots de passe).
2. **`/data` doit être un volume persistant** (voir notions ci-dessus).
   Le perdre = perdre la base et les PDF.
3. **HTTPS devant** : Railway le fournit automatiquement sur son domaine.
   Sur un serveur à vous, mettez un reverse proxy (Caddy, nginx…).
4. **Sauvegardez `/data`** de temps en temps (une copie du dossier suffit).
5. Les migrations de base se font toutes seules au démarrage du conteneur.
6. Sonde de vie : `GET /api/health` répond `{"status": "ok"}`.

---

## La démo publique sur Railway, pas à pas

Objectif : **une seule instance, deux adresses**.

- `demo.votre-domaine.example` : n'importe qui essaie LitUbik **en un clic,
  sans compte** — une session invitée anonyme, avec un projet exemple
  pré-rempli, supprimée chaque nuit.
- `app.votre-domaine.example` : la connexion ordinaire de **vos** comptes
  (votre email et ceux de la liste d'autorisation) — comptes complets,
  permanents, sans restriction.

C'est le nom d'hôte qui fait la différence : les adresses qui commencent par
`demo.` affichent le bouton invité, les autres non (réglable avec
`LITUBIK_DEMO_GUEST_HOSTS`, voir plus bas).

### Étape 0 — Prérequis

- Un compte GitHub, avec le dépôt `abequet/litubik_public` ou votre fork.
- Un compte Railway : https://railway.app → « Login » → « Login with
  GitHub » (le plus simple : ça reliera directement vos repos).
- Une `LITUBIK_SECRET_KEY` générée (règle d'or n°1).

### Étape 1 — Créer le projet Railway

1. Sur https://railway.app, cliquez **« New Project »**.
2. Choisissez **« Deploy from GitHub repo »**.
3. La première fois, Railway demande l'autorisation d'accéder à vos repos
   GitHub : acceptez (vous pouvez ne l'autoriser que sur ce dépôt).
4. Sélectionnez le dépôt **`litubik_public`** (ou votre fork).
5. Railway détecte le `Dockerfile` et lance un premier build. **C'est
   normal qu'il tourne** — laissez-le faire, on règle la suite pendant ce
   temps. (Ce premier déploiement sera de toute façon refait après l'étape
   variables.)
6. Par défaut Railway déploie la branche `main`. Pour changer :
   service → **Settings** → section **Source** → « Branch ».

### Étape 2 — Brancher le volume `/data`

1. Cliquez sur le service LitUbik (la carte au centre de l'écran).
2. Clic droit sur la carte (ou bouton « + » du projet) → **« Attach
   Volume »** (parfois : Settings → Volumes → Add Volume).
3. **Mount path** : tapez exactement `/data`.
4. Taille : 1 GB suffit largement pour commencer (agrandissable plus tard).

> Sans cette étape, chaque redéploiement effacerait la base : à ne pas
> oublier.

### Étape 3 — Les variables d'environnement

Service → onglet **« Variables »** → ajoutez ces lignes (bouton « New
Variable », une par une, ou « Raw Editor » pour tout coller) :

```
LITUBIK_SECRET_KEY=<la-clé-générée-à-l-étape-0>
LITUBIK_DEMO=true
LITUBIK_TRUSTED_EMAILS=vous@votre-etablissement.example
```

Ce que ça veut dire :

| Variable | Rôle |
|---|---|
| `LITUBIK_SECRET_KEY` | La clé secrète (règle d'or n°1 — ne changera plus jamais) |
| `LITUBIK_DEMO` | Active le profil démo : sessions invitées, bacs à sable, purge quotidienne, budget IA, pages légales |
| `LITUBIK_TRUSTED_EMAILS` | Les emails « de confiance », séparés par des virgules : ils s'inscrivent en compte complet. Le **premier compte** de l'instance (le superadmin) doit en faire partie |

Tout le reste a une valeur par défaut adaptée ; ne l'ajoutez que pour la
changer :

| Variable (optionnelle) | Défaut | Rôle |
|---|---|---|
| `LITUBIK_DEMO_RESET_HOUR` | `4` | Heure (UTC) de la purge quotidienne des sessions invitées. `-1` = jamais |
| `LITUBIK_DEMO_GUEST_HOSTS` | `demo.*` | Noms d'hôte qui affichent le bouton invité (motifs séparés par des virgules ; `*` = tous) |
| `LITUBIK_DEMO_AI_USER_CAP_USD` | `2` | Dépense IA maximale par session invitée, en dollars |
| `LITUBIK_DEMO_AI_DAILY_CAP_USD` | `1` | Dépense IA maximale par jour (UTC), tous visiteurs confondus : un bot ne vide pas le budget du mois en un après-midi |
| `LITUBIK_DEMO_AI_MONTHLY_CAP_USD` | `10` | Dépense IA maximale par mois, tous visiteurs confondus. `0` coupe l'IA aux visiteurs |
| `LITUBIK_CONTACT_EMAIL` | (vide) | Adresse envoyée aux API ouvertes (Crossref, OpenAlex, NCBI) et à Unpaywall pour les visiteurs |
| `LITUBIK_SOURCE_URL` | dépôt public | Lien « Code source » (AGPL §13). Sur Railway, il pointe seul vers la branche principale de `litubik_public` ; à changer si vous déployez un fork modifié |

Inutile de poser `LITUBIK_SESSION_COOKIE_SECURE` (le cookie passe en
`Secure` dès que Railway sert la page en HTTPS) ni `FORWARDED_ALLOW_IPS`
(l'image fait déjà confiance au proxy de Railway pour connaître l'IP réelle
des visiteurs). Et `LITUBIK_ALLOW_REGISTRATION` est ignoré sur une démo : les
visiteurs passent par la session invitée, l'inscription par email est
réservée à la liste d'autorisation.

À chaque modification de variable, Railway redéploie automatiquement.

### Étape 4 — Les deux adresses

1. Service → **Settings** → section **Networking**.
2. Cliquez **« Generate Domain »** : Railway donne une URL du type
   `litubik-production-xxxx.up.railway.app`, en HTTPS. Elle sert à tester
   (connexion ordinaire, pas de bouton invité : elle ne commence pas par
   `demo.`).
3. S'il demande le port : **8000** (c'est le port qu'écoute LitUbik dans le
   conteneur ; en général il le détecte seul).
4. Optionnel : Settings → **Healthcheck** → path `/api/health` (Railway
   vérifiera que l'app répond avant de basculer un nouveau déploiement).
5. Ajoutez vos deux noms de domaine (étape 5 bis) : `app.…` et `demo.…`.

### Étape 5 — Premier lancement (checklist)

1. Ouvrez `https://app.votre-domaine.example` (ou l'URL Railway) :
   connexion ordinaire, sans bandeau.
2. Cliquez « Register » et inscrivez-vous avec **votre email autorisé**
   (l'adresse de `LITUBIK_TRUSTED_EMAILS`). Le **premier compte créé
   devient le superadmin** de l'instance.
3. Dans la barre latérale, section Administration : les pages **« Demo
   access »** (liste d'autorisation, budget IA des visiteurs, purge
   manuelle) et **« Legal pages »** (mentions légales, CGU, confidentialité)
   doivent être visibles. Relisez les trois pages légales une fois : elles
   sont pré-remplies (éditeur = votre nom d'affichage, contact =
   `contact@litubik.org`, hébergeur = Railway, détecté seul), et chaque
   champ est modifiable.
4. Ajoutez une **clé IA globale** (Administration → AI keys) si les
   visiteurs doivent pouvoir essayer l'IA : ils l'utilisent dans son modèle
   « bulk », dans la limite du budget (2 $ par session, 10 $ par mois par
   défaut). Rien d'autre n'est partagé avec eux.
5. Test visiteur : dans une fenêtre de navigation privée, ouvrez
   `https://demo.votre-domaine.example` → bandeau jaune, bouton **« Ouvrir
   une session invitée »** → la session reçoit le projet exemple « *Example
   review — distracted pedestrians (sandbox)* », le bandeau affiche le
   budget IA restant, et le menu utilisateur propose « Terminer la session
   et supprimer mes données ».
6. Test robustesse : dans Railway, service → « ⋮ » → **Restart**. Après
   redémarrage, reconnectez-vous : vos données doivent être intactes (c'est
   le volume qui fait ça).

### Étape 5 bis — Les noms de domaine

Pour vos adresses à vous (p. ex. `app.litubik.org` et `demo.litubik.org`), il
faut un domaine que vous possédez et deux redirections DNS vers Railway.

1. **Avoir un domaine.** Deux cas :
   - *Vous n'en avez pas* : achetez-en un chez un registrar (OVH, Gandi,
     Namecheap, Cloudflare… ~10 €/an pour un `.fr`/`.com`/`.org`). Vous
     pourrez créer autant de sous-domaines que voulu (`app.`, `demo.`…).
   - *Domaine institutionnel* : vous ne pouvez pas le gérer vous-même —
     demandez à la DSI de créer les sous-domaines (leur donner les CNAME de
     l'étape 3 ci-dessous).
2. **Côté Railway** : service → **Settings** → **Networking** → **« Custom
   Domain »** → tapez `app.votre-domaine.example` → **Add Domain** ; puis
   pareil pour `demo.votre-domaine.example`. Railway affiche pour chacun la
   cible DNS à configurer, du type :

   ```
   CNAME  app   →  xxxx.up.railway.app
   CNAME  demo  →  yyyy.up.railway.app
   ```

3. **Côté registrar** (l'interface de gestion DNS de votre domaine, p. ex.
   OVH → Zone DNS) : créez les deux enregistrements **CNAME** :
   - **Nom / sous-domaine** : `app` (puis `demo`) ;
   - **Cible** : la valeur affichée par Railway (recopiez-la exactement,
     point final compris si l'interface en met un).
4. **Attendre la propagation DNS** : de quelques minutes à quelques heures.
   Sur la page Railway, chaque domaine passe de « Waiting for DNS » à un ✓
   vert. Les **certificats HTTPS sont générés automatiquement** par
   Railway — rien à faire.
5. **Adresse de contact** : les pages légales affichent `contact@` + votre
   domaine. Créez la redirection mail correspondante chez le registrar
   (gratuite chez la plupart d'entre eux), sinon les messages sont rejetés.
6. **Adresse stable** : si l'instance est citée (article, documentation),
   choisissez son adresse dès maintenant pour ne pas avoir à la changer.

### Étape 6 — Vie courante

- **Mises à jour** : chaque `git push` sur la branche déployée redéclenche
  un build + déploiement. Rien d'autre à faire. Le build échoue exprès si
  l'image contenait l'extension locale optionnelle de récupération : elle
  n'a rien à faire sur un serveur public.
- **Coût** : plan Hobby (~5 $/mois), plus le budget IA des visiteurs
  (plafonné). Surveillez l'onglet « Usage » les premières semaines, et la
  carte « AI budget of the visitors » de la page Demo access.
- **Ajouter un collègue en compte complet** : page « Demo access » → saisir
  son email → il s'inscrit sur l'adresse `app.` (ou son compte existant est
  promu aussitôt).
- **Ça ne marche pas ?** Service → onglet **« Deployments »** → cliquez le
  déploiement → **« View Logs »**. Les erreurs de démarrage s'y lisent en
  clair (clé manquante, migration…).

### Ce que le profil démo change (résumé)

- **Visiteurs** : sur l'adresse `demo.`, un bouton ouvre une session invitée
  en un clic — identifiant aléatoire, aucun email, aucun mot de passe, aucune
  donnée personnelle. Au plus 5 sessions par adresse IP (un bloc /64 en IPv6)
  et par heure, 20 par jour, 60 par heure pour toute l'instance, et 300
  sessions ouvertes en même temps. L'adresse IP prise en compte est celle que
  le proxy de Railway ajoute lui-même, jamais celle qu'un client prétend avoir
  (l'image ne fait confiance qu'aux proxys des réseaux privés).
- **Comptes** : les emails de la liste d'autorisation (et les membres qu'un
  compte autorisé ajoute à ses projets) s'inscrivent en comptes complets ;
  personne d'autre ne s'inscrit par email. Rien ne change pour ces comptes :
  accès institutionnels, clés globales, synchronisation, prompts, comme sur
  n'importe quelle instance.
- **Bac à sable d'une session invitée** : 3 projets, 2 000 références par
  import, recherche ou snowballing et 5 000 par projet, 100 PDF par
  récupération, 20 Mo par PDF, 100 Mo par projet, 25 Mo par requête, 5
  messages de retour par jour, **une tâche de fond à la fois** (et 4 pour
  l'ensemble des visiteurs). Récupération du texte intégral **uniquement
  depuis les sources en libre accès, par téléchargement direct** (aucun accès
  institutionnel, aucune extension, pas de navigateur automatisé). Pas de membres, pas de clés API
  stockées, pas de Zotero, pas de synchronisation, pas de revue vivante
  planifiée, pas de modification des prompts, pas de module « Download
  papers ».
- **IA des visiteurs** : la clé IA globale, dans son modèle « bulk », sous
  trois plafonds (par session, par jour et par mois pour l'ensemble des
  visiteurs). Un appel qui pourrait dépasser un
  plafond est refusé avant d'être envoyé. Les clés BDD globales (Scopus,
  IEEE…) restent réservées aux comptes autorisés.
- **Purge quotidienne** : à l'heure `LITUBIK_DEMO_RESET_HOUR`, les sessions
  invitées et leurs projets sont supprimés (sauf celles ouvertes depuis moins
  d'une heure, qui attendent la purge suivante). Le visiteur peut aussi tout
  supprimer lui-même à tout moment ; le superadmin peut purger à la main.
- **Pages légales** : mentions légales, CGU et politique de
  confidentialité, en anglais et en français, lisibles sans connexion depuis
  le pied de chaque page, avec le lien vers le code source.
- **Requêtes anonymes** (sans session) : 64 Ko au plus, sur toute instance —
  rien d'anonyme n'en a besoin, et un envoi massif est refusé avant d'être lu.
- Une instance normale (sans `LITUBIK_DEMO`) n'a **aucun** des autres
  comportements.
- **Côté Railway**, fixez une limite de dépense (Workspace → Usage → usage
  limit) : quoi qu'il arrive, un trafic anormal ne fera pas grimper la
  facture au-delà.

---

## Serveur de labo (docker-compose)

Pour une instance privée d'équipe sur une machine du labo (avec l'aide de
l'ingénieur système si besoin) :

```bash
# dans le dossier du repo, une fois pour toutes :
echo "LITUBIK_SECRET_KEY=<clé-générée>" > .env
docker compose up -d --build
```

L'app écoute sur le port 8000 ; les données vivent dans `./data` à côté du
compose (c'est le volume). `docker-compose.yml` contient en commentaires le
passage à Postgres (`LITUBIK_DATABASE_URL`) si l'instance devait grossir.

Conseils :

- Les inscriptions sont restreintes par défaut : seuls le premier compte,
  les emails de `LITUBIK_TRUSTED_EMAILS` et les personnes ajoutées à un
  projet par un admin peuvent s'inscrire. `LITUBIK_ALLOW_REGISTRATION=true`
  dans `.env` les ouvre à tous (déconseillé hors réseau de confiance).
- Donnez une adresse de contact joignable aux API ouvertes (Crossref,
  OpenAlex, NCBI) : `LITUBIK_CONTACT_EMAIL=equipe@votre-labo.example` dans
  `.env`. Sans elle, LitUbik se rabat sur l'e-mail Unpaywall global, sinon
  n'envoie aucune adresse (pool public, plus lent) — jamais une adresse
  fictive.
- Hors réseau local de confiance, mettez un reverse proxy HTTPS devant
  (Caddy : 5 lignes de config) — les mots de passe transitent à chaque
  requête.
- Sauvegarde : copie nocturne du dossier `data/` (cron + rsync suffisent).
