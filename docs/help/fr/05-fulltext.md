# Récupérer et lire les textes intégraux

## Récupération automatique

L'étape **FT retrieval** tente de télécharger le PDF de chaque référence
incluse au screening titre/résumé. Elle parcourt les sources dans l'ordre et
s'arrête à la première qui répond :

1. **Crossref** — résout le DOI et fournit les liens déclarés par l'éditeur ;
2. **Unpaywall** — la copie open access lorsqu'elle est référencée ;
3. **PubMed Central / Europe PMC** ;
4. **la page open access de l'éditeur** ;
5. **votre accès institutionnel**, si vous en avez configuré un (voir ci-dessous).

Rien d'autre n'est tenté : aucune bibliothèque parallèle, aucun contournement
de paywall. Quand toutes les sources échouent, la référence est marquée *non
récupérée* — ce compteur alimente directement le diagramme PRISMA — et vous
pouvez déposer le PDF à la main.

Le statut de chaque référence indique si un PDF a été trouvé, est en attente,
ou a échoué. Tout membre du projet peut lancer la récupération, pas seulement
les admins.

## Mes accès institutionnels (PDF sous paywall)

Les articles derrière un paywall passent souvent par le proxy de votre
bibliothèque (EZproxy, OpenAthens, CAS). Ajoutez votre institution depuis
**Mes accès institutionnels** dans la barre latérale (également disponible
sur la page Full text d'un projet et dans *Paramètres du projet → Accès
institutionnels*) : commencez à taper son nom et choisissez-la dans
l'annuaire intégré — l'URL du proxy se remplit automatiquement — puis
saisissez vos identifiants bibliothèque habituels.

**Si votre université passe par un CAS fédéré** (c'est le cas à Toulouse, où
plusieurs établissements partagent le même proxy), la page de connexion vous
demande de choisir votre établissement dans un menu. L'annuaire intégré ne
connaît que l'URL du proxy, pas cette information : vous devez la saisir
vous-même dans le champ **scope**. Si vous le laissez vide, la connexion part
sur l'établissement par défaut du menu et échoue. Lancez une récupération : le
message d'erreur affiché sur la référence liste les valeurs acceptées (pour
Toulouse II Jean Jaurès, c'est `ut2`).

La recherche dans l'annuaire tolère les accents, les traits d'union et le
domaine du proxy : `université gustave eiffel`, `univ-eiffel` ou `ucly`
trouvent tous leur institution. Cet annuaire est public, pas exhaustif : si
la vôtre n'y figure pas, gardez l'intitulé que vous avez tapé et collez
vous-même l'URL de connexion du proxy — de la forme
`https://<quelque-chose>/login?url=$@`, votre bibliothèque peut vous la
fournir (`$@` est l'endroit où l'app insère l'URL de l'article).

**L'endroit où vivent vos identifiants dépend de la façon dont vous les avez
saisis**, et la différence compte :

- **Mes accès institutionnels** (barre latérale) les garde **uniquement dans
  votre navigateur**. Ils sont envoyés une fois à chaque récupération que vous
  lancez, utilisés pour télécharger les PDF, puis oubliés côté serveur. Par
  défaut le mot de passe n'est gardé que jusqu'à la fermeture de l'onglet ;
  cochez *Mémoriser sur cet appareil* pour le conserver dans ce navigateur.
- **Paramètres du projet → Accès institutionnels** et la page *Accès
  institutionnels (app)* les **stockent sur le serveur**, chiffrés, et tous les
  projets de l'instance peuvent s'en servir. C'est l'objectif — cela permet à
  une équipe de partager un compte de bibliothèque — mais votre mot de passe
  quitte alors votre machine, et l'administrateur de l'instance détient la clé
  qui le déchiffre.

Du point de vue de l'éditeur, une récupération automatisée via un proxy de
bibliothèque est un téléchargement de masse. La plupart des contrats
d'abonnement interdisent le téléchargement « systématique ou substantiel », et
la sanction habituelle frappe l'établissement entier, pas la personne. Vérifiez
ce que permettent les conditions de votre bibliothèque avant de lancer de gros
lots, et gardez les PDF récupérés au sein de l'équipe de revue.

Si vous rejoignez un projet comme reviewer et que des PDF manquent encore,
ajoutez votre propre institution et lancez *Retrieve missing PDFs* : tout ce
que couvre votre abonnement est téléchargé et partagé avec le projet.

## Accès partagés (stockés sur le serveur)

À côté de vos identifiants personnels, LitUbik peut conserver des proxys
**partagés** sur le serveur, chiffrés, essayés à chaque récupération :

- **au niveau de l'application** — *Administration → Accès institutionnels
  (application)* (admin de l'application) ; hérités par tous les projets de
  l'instance ;
- **propres à un projet** — *page Full text → Paramètres* (admin du projet).

Les deux sont listés dans *Paramètres du projet → Accès institutionnels*, à
côté de vos accès personnels stockés dans le navigateur : on voit d'un coup
d'œil ce qui est déjà configuré et où le modifier. Utilisez les accès
partagés pour un abonnement dont toute l'équipe peut se servir, et les accès
personnels pour des identifiants qui doivent rester les vôtres.

## Dépôt manuel et remplacement

Pour les articles hors de portée du tiers automatique (paywall, scans…),
déposez le PDF manuellement sur la référence, ou utilisez le bouton
*Remplacer le PDF* si le fichier récupéré est mauvais (p. ex. le supplément
au lieu de l'article).

Tout membre du projet peut déposer ou remplacer un PDF — pas seulement les
admins — pour qu'un relecteur qui tombe sur un fichier manquant ou erroné le
corrige sur place, depuis trois endroits :

- la page **Full-text** (*Déposer un PDF* / *Remplacer* sur la ligne de la
  référence) ;
- le panneau **bibliothèque PDF** (*Remplacer le PDF* à côté de chaque
  entrée) ;
- l'écran de **screening du texte intégral** lui-même (*Déposer un PDF*
  dans le lecteur vide, *Remplacer le PDF* sous le titre), où le lecteur
  recharge aussitôt le nouveau fichier.

Supprimer un PDF reste une action d'admin.

## Import de PDF en masse

Vous avez déjà les PDF — p. ex. depuis la plateforme où la revue a
commencé, ou un dossier Zotero ? Sur la page **Full-text**, l'admin du
projet peut utiliser **Import de PDF en masse** et sélectionner de nombreux
fichiers d'un coup. Chaque fichier est rattaché à son article
automatiquement : par le DOI imprimé dans le PDF, par le DOI présent dans
le nom de fichier, ou par correspondance du titre (dans le texte, puis dans
le nom de fichier). Les fichiers reconnus avec confiance sont enregistrés
immédiatement ; les autres sont listés avec leurs meilleurs candidats et un
menu pour les attribuer à la main — ou remplacer un PDF existant. Les
articles importés via une table d'extraction externe font aussi partie de
la bibliothèque : leurs PDF s'importent (ou se récupèrent automatiquement)
de la même façon.

## La bibliothèque de PDF

L'entrée **PDFs téléchargés** de la barre latérale liste tous les PDF du
projet. Les PDF s'ouvrent dans le lecteur intégré, qui gère surlignages et
annotations partagés avec l'équipe ; un PDF peut aussi s'ouvrir dans une
fenêtre séparée pour lire en screenant. Sélectionnez du texte puis faites un
clic droit : **Copier** le place dans le presse-papiers, **Ajouter un
commentaire / surlignage** le partage avec l'équipe — une fois le screening
texte intégral de l'article terminé ; d'ici là chaque relecteur ne voit que
ses propres surlignages, pour que l'aveugle tienne.

Chaque entrée est colorée selon sa décision de texte intégral (inclus,
exclu, à évaluer). Les pastilles au-dessus de la liste la filtrent : cliquez
**inclus** pour ne voir que les PDF retenus, **Tous** pour tout revoir ; la
liste se trie aussi par auteur, année ou décision.

Chaque entrée porte une case à cocher, et **Télécharger la sélection**, en
bas du panneau, réunit ce que vous avez coché dans un zip — **Tout
sélectionner** prend toute la bibliothèque, ou seulement les entrées
affichées quand un filtre est actif (« tous les PDF inclus » = une pastille
plus une case). Dans le zip, chaque fichier est
renommé `Auteur_Annee_cinq_premiers_mots_du_titre.pdf` (nom du premier
auteur, année de publication, cinq premiers mots du titre) : l'archive se
range directement dans vos dossiers ou dans Zotero.

## Télécharger des articles hors projet

Besoin de quelques PDF sans monter une revue ? **Télécharger des articles**,
dans la section *Espace* de la barre latérale (sous *Projets*), fonctionne de
façon autonome : collez des DOI — un par ligne, ou séparés par des virgules ou
des espaces ; les préfixes `doi:` et les liens `doi.org` sont acceptés — puis
cliquez sur **Télécharger**.

Le module est **fermé par défaut** : un admin de l'application l'ouvre
utilisateur par utilisateur, en cochant *Télécharger des articles* dans
**Administration → Utilisateurs**. D'ici là, l'entrée n'apparaît pas dans votre
barre latérale. Une fois le module ouvert, vous pouvez demander **5 articles
par heure** (un article introuvable n'est pas décompté) ; la page indique
combien il vous en reste et quand le prochain créneau se libère. Les admins de
l'application ont toujours le module, sans limite horaire (200 DOI au plus par
lancement).

Les admins de l'application voient aussi **à quoi le module a servi** : la même
page **Administration → Utilisateurs** liste, sous *Articles téléchargés*,
chaque utilisateur qui l'a lancé, avec le nombre de lancements et de PDF
récupérés ; en dépliant un utilisateur, on voit chaque lancement et chaque
article demandé — titre, DOI, si un PDF a été trouvé et depuis quelle source.
Les PDF eux-mêmes ne sont pas conservés au-delà de 24 heures ; seule cette
trace des demandes l'est.

Les mêmes sources que la récupération d'un projet sont essayées, y compris vos
accès institutionnels personnels et ceux de l'application. À la fin, votre
navigateur télécharge le résultat : **le PDF lui-même si un seul article a été
trouvé, un zip s'il y en a plusieurs**. Les fichiers sont nommés
`Auteur_Annee_premiers_mots_du_titre.pdf`, comme pour la récupération par lot.
Les articles introuvables sont listés avec la raison et, quand elle est connue,
un lien vers la page de l'éditeur.

Rien n'est ajouté à un projet. Le traitement tourne sur le serveur : vous
pouvez quitter la page et y revenir ; les fichiers restent disponibles 24
heures, et vous seul pouvez les récupérer.

## Partage des PDF dans l'équipe

Les PDF voyagent avec les snapshots du projet (voir *Collaboration et
synchronisation*) : un texte intégral récupéré par un membre devient
disponible pour tous.
