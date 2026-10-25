# Collaborer entre plusieurs instances LitUbik

LitUbik fonctionne selon deux modes, combinables :

1. **Une instance partagée** — le serveur d'un labo/une université héberge
   LitUbik (`docker compose up`, voir README) ; tout le monde s'y connecte au
   navigateur. Rien à synchroniser.
2. **Une instance par chercheur** (chacun fait tourner LitUbik sur sa
   machine) — les instances s'échangent leur travail par **instantanés** et
   **paquets de contributions**, manuellement (fichiers) ou automatiquement
   (dossier partagé). C'est ce mode que décrit ce guide.

## Les rôles

- Le **coordinateur** (l'instance du porteur de la revue) possède l'état
  *structurel* : protocole, équations, imports de références, déduplication,
  configuration des rounds, résolution des conflits, PRISMA.
- Les **satellites** (les co-reviewers) reçoivent ce state par instantané et
  produisent leurs contributions *personnelles* : votes, appréciations JBI,
  extractions, annotations PDF. Les pages structurelles y sont verrouillées
  (badge « sat »).

Les personnes sont appariées par **e-mail** : utilisez le même e-mail de
compte sur chaque instance. Un membre encore inconnu d'une instance y devient
un « compte fantôme » — s'inscrire avec cet e-mail le récupère, avec tout son
travail.

## Scénario A — échange par fichiers (aucune infrastructure)

Alice (Lyon) coordonne ; Bob (Montréal) co-screene.

1. **Alice** prépare le projet (protocole, imports, dédup, round de screening
   avec Bob parmi les reviewers), puis *Synchronisation → Exporter
   l'instantané* et envoie le `.zip` à Bob (mail, drive, USB…).
2. **Bob** installe LitUbik (voir README), crée son compte **avec le même
   e-mail**, puis *Projets → Importer un projet* avec le zip : sa copie
   satellite est prête, PDF compris.
3. **Bob vote** (hors-ligne s'il veut), puis *Synchronisation → Exporter mes
   contributions* → un petit `.json` qu'il renvoie à Alice.
4. **Alice** l'importe (*Importer les contributions d'un co-reviewer*) : les
   votes de Bob s'insèrent, les **conflits et le kappa se recalculent
   automatiquement**. Ils résolvent les conflits (en visio, sur l'instance
   d'Alice), Alice avance le projet, ré-exporte un instantané v2…
5. **Bob** l'applique (*Appliquer un instantané reçu*) : ses votes locaux
   survivent à la mise à jour (la version la plus récente gagne).

Renvoyer un vieux fichier est sans danger : les exports sont complets et
l'import idempotent — rien de plus récent n'est jamais écrasé.

## Scénario B — dossier partagé (synchronisation automatique)

Même logique, zéro manipulation : liez chaque instance au **même dossier
synchronisé** (Nextcloud, OneDrive, Google Drive, Dropbox…).

1. Alice crée un dossier dans son Nextcloud, le partage avec Bob (qui le
   synchronise sur son PC). Sur son instance : *Synchronisation → Dossier
   partagé* (chemin local du dossier), puis « Publier l'instantané dans le
   dossier ».
2. Bob n'a **rien à recevoir** : sur sa page Projets, « Rejoindre via un
   dossier partagé » → il colle le chemin *local* de ce même dossier → sa
   copie satellite se crée depuis le dernier instantané trouvé et le projet
   est lié au dossier, en un seul geste.
3. C'est tout : toutes les 5 minutes (ou via « Synchroniser maintenant »),
   chaque instance dépose ses contributions et importe celles des autres.
   Alice publie ses instantanés dans le dossier (bouton « Publier », ou
   publication auto) ; Bob voit « mise à jour disponible » et l'applique en
   un clic. Le journal de la page Synchronisation trace tous les échanges.

## Clés API partagées (optionnel)

Chaque membre peut partager ses clés API **de projet** (IA, Scopus, IEEE)
avec les autres instances : carte *Clés API partagées* de la page
Synchronisation. Les clés voyagent **chiffrées** par une *phrase secrète de
projet* (PBKDF2 → Fernet) que chaque instance saisit une fois — communiquez-la
de vive voix, jamais avec les fichiers. Dé-partager une clé la retire chez
les autres au prochain échange. Les identifiants institutionnels EZProxy/CAS
(personnels) ne voyagent jamais.

## FAQ sécurité

- **Que contient un instantané ?** Tout l'état du projet : références,
  votes de tous les reviewers, protocole, fichiers RIS bruts, PDF (option),
  membres (e-mails et rôles — jamais les mots de passe). C'est aussi le
  paquet de réplication à déposer avec la publication (OSF).
- **Et un paquet de contributions ?** Uniquement le travail de son auteur,
  plus, si une phrase secrète est définie, ses clés partagées chiffrées.
- **Les clés API en clair ?** Jamais — ni au repos (Fernet local), ni en
  transit (phrase secrète). Sans la phrase, le bloc de clés est ignoré.
- **Un tiers qui obtient un fichier ?** Il lit les métadonnées de la revue
  (comme le ferait le paquet de réplication publié), pas les clés. Faites
  transiter les fichiers par vos canaux institutionnels habituels.
- **Deux personnes votent le même article en même temps ?** Chacun ne modifie
  que ses propres votes — il n'y a jamais de conflit *technique* ; les
  désaccords sont des conflits *de screening*, gérés dans l'onglet Conflits.
