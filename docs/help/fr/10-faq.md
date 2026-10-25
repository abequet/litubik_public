# FAQ / Dépannage

**L'interface est dans la mauvaise langue.**
Utilisez le sélecteur de langue (EN/FR) dans l'en-tête. Le choix est
mémorisé par navigateur.

**Je ne vois pas l'entrée Settings d'un projet.**
Seuls les admins du projet la voient. Demandez à un admin du projet de
changer votre rôle.

**Une carte de base de données demande une clé API.**
Configurez une clé projet (*Project settings*, admin) ou une clé globale
(*Administration*, superadmin) — ou utilisez le mode manuel assisté :
copiez l'équation traduite dans le site de la base et importez le fichier
d'export. Les clés CORE et Springer Nature sont gratuites (inscription
immédiate), le jeton Lens.org est gratuit pour un usage non commercial
(formulaire), les clés Scopus, IEEE et Web of Science Starter viennent avec
un abonnement institutionnel. La carte de clé renvoie vers la page de chaque
fournisseur.

**La base de données dont j'ai besoin n'est pas dans la liste.**
Web of Science, EBSCO (PsycINFO/PsycARTICLES), ACM, TRID (recherche
transport) et Google Scholar sont déjà là, en mode manuel assisté — seules Scopus et IEEE apparaissent comme
cartes de clé, ce sont les deux qui disposent d'un connecteur API. Pour toute
autre base, un admin du projet l'ajoute dans *Paramètres du projet → Clés
bases de données → Bases ajoutées par ce projet* ; elle apparaît ensuite sur
les pages Équations et Recherche comme les autres.

**Comment connecter Zotero ?**
Barre latérale → *Mes intégrations*. Créez une clé sur zotero.org/settings/keys
avec *Allow library access* (et *Allow write access* si vous voulez envoyer des
références depuis LitUbik ; cochez aussi le groupe si vous travaillez dans une
bibliothèque de groupe), collez-la, vérifiez-la, choisissez la bibliothèque.
La clé est personnelle : stockée chiffrée sur ce serveur, utilisée seulement
pour vos propres imports et exports, jamais partagée avec les autres membres
ni synchronisée vers d'autres instances. Mendeley n'est pas pris en charge
(API OAuth uniquement, en voie d'abandon) : exportez en RIS/BibTeX à la place.

**Taper le nom de mon université dans les accès institutionnels ne trouve rien.**
L'annuaire de proxys embarqué est public et non exhaustif. Essayez la forme
courte ou le domaine (`univ-eiffel`, `ucly`) ; si rien ne correspond, gardez
l'intitulé que vous avez tapé et collez vous-même l'URL de connexion du proxy
(`https://…/login?url=$@`) — votre bibliothèque peut vous la fournir.

**Les boutons IA disent qu'aucun fournisseur n'est configuré.**
Ajoutez une clé IA (niveau projet ou app, voir *Assistance IA*). Si une clé
existe mais échoue, vérifiez son quota/sa validité chez le fournisseur.

**Un projet est marqué « sat » et certaines actions sont verrouillées.**
C'est une copie satellite : la structure est gérée par l'instance
coordinatrice. Contribuez votes/notes/extraction et synchronisez ; les
changements structurels se font sur le coordinateur.

**J'ai perdu mon mot de passe.**
Demandez au superadmin de l'app (pas de réinitialisation en libre-service
en v1). Le superadmin peut aussi promouvoir des comptes.

**J'ai lancé le snowballing par erreur (ou sur les mauvais articles inclus).**
Ouvrez *Snowballing* → *Itérations* et cliquez sur le ✕ du dernier tour. Cela
l'annule complètement — les articles trouvés par ce tour, leur tri et ses
liens de citation sont supprimés, comme s'il n'avait jamais eu lieu — et
libère ses graines pour être réexplorées. Seul le tour le plus récent est
supprimable (supprimez les tours du plus récent au plus ancien) ; l'action est
réservée aux admins et irréversible.

**Le journal indique qu'aucune IA n'a été utilisée, alors que si.**
Le journal d'usage de l'IA commence avec la version de LitUbik qui a introduit
la page *Reporting*. Un projet ayant utilisé l'IA avant possède des sorties IA
dans ses tables mais aucune entrée de journal — la page de déclaration le
détecte et vous avertit. Corrigez les niveaux du formulaire à la main avant de
générer ; à partir de maintenant chaque appel est enregistré.

**La déclaration d'usage de l'IA couvre-t-elle la rédaction de l'article ?**
Non. Elle couvre l'usage de l'IA pour *conduire* la revue, parce que c'est ce
que LitUbik peut observer. L'énoncé généré le précise. Si vous avez utilisé un
outil d'IA pour rédiger ou corriger le manuscrit, déclarez-le à part.

**Ma revue n'est pas une revue systématique PICO. Puis-je utiliser LitUbik ?**
Oui. Dans *Paramètres du projet → Général*, réglez le **cadre de la question**
sur celui qu'emploie votre protocole — SPIDER, SPICE, PEO, PICO(S), ou un
cadrage libre — et le **type de revue** sur ce que votre revue est réellement.
L'extraction du protocole, le nom des blocs de concepts, les modèles
d'extraction, les prompts IA et le brouillon de la section Methods suivent. Le
pipeline lui-même ne change pas.

**J'ai choisi la synthèse « best fit » — où est le cadre *a priori* ?**
Il n'y en a pas dans l'application, et c'est délibéré plutôt que manquant :
LitUbik ne mène qu'un seul brin de recherche et n'outille ni la construction
d'un cadre *a priori*, ni le codage des données contre lui. Le réglage change
le vocabulaire, les modèles et le brouillon Methods, pas le pipeline. Faites le
travail de cadre hors de LitUbik et consignez-le dans la table d'extraction —
le modèle `Synthèse « best fit » à cadre a priori` vous donne des colonnes pour
le thème sur lequel un résultat a été codé, le fait que le cadre l'accueillait
ou non, le thème émergent le cas échéant, et la provenance de chaque résultat.
Le brouillon Methods indique que le logiciel n'a pas outillé cette partie de la
méthode, pour qu'un lecteur ne lui attribue pas un travail qu'il n'a pas fait.

**J'ai changé le cadre de la question et mon protocole affiche encore l'ancien.**
C'est attendu : le réglage s'applique à la **prochaine** extraction. Le texte
de protocole déjà généré est le vôtre — éventuellement édité à la main — donc
l'application ne le réécrit jamais. Relancez l'extraction IA sur une nouvelle
version du protocole, ou modifiez le Markdown à la main.

## Accessibilité

LitUbik vise le niveau AA des WCAG 2.1. La déclaration de conformité —
chaque critère avec son statut et le plan pour les deux critères partiels —
est dans `docs/ACCESSIBILITY.md` de l'arbre source ; un audit automatique
axe-core des pages principales tourne avec la suite de tests.

**Puis-je utiliser LitUbik uniquement au clavier ?**
Oui. Tous les contrôles sont atteignables avec Tab, et la première
tabulation de chaque page propose un lien *Aller au contenu principal* qui
saute la barre latérale. Les cellules d'extraction sont des boutons : Tab
jusqu'à la cellule, Entrée pour la modifier, Échap pour annuler. Les pages
de screening ajoutent des raccourcis à une lettre (Y/N/M/S/P) ; s'ils
entrent en conflit avec votre technologie d'assistance, désactivez-les dans
le menu **?** (*Raccourcis à une touche*).

**Puis-je lire les graphiques sans les voir ?**
Chaque graphique de la page Résultats a un bouton **Données** qui affiche
les mêmes chiffres en tableau, et le réseau de citations de la page
Snowballing a le même bouton listant les articles (statut, tour, graines
liées, citations).
Les graphiques portent aussi une description textuelle pour les lecteurs
d'écran.

**Les animations me gênent.**
LitUbik suit le réglage *réduire les animations* de votre système : quand il
est actif, les dialogues s'ouvrent sans transition et la visite guidée ne
s'anime pas. Le réseau de citations ne bouge jamais de lui-même : sa
disposition est calculée une fois et dessinée immobile.

**Le texte est trop petit.**
L'en-tête a un réglage de taille de texte (icône *A*) de 80 % à 140 %,
mémorisé par navigateur ; le zoom du navigateur fonctionne aussi. En thème
clair, le texte secondaire respecte désormais le contraste WCAG AA (4,5:1) et
aucun libellé informatif ne descend sous 12 px.

**Quelle langue utilise mon lecteur d'écran ?**
Celle de l'interface : la langue de la page suit le sélecteur EN/FR, le
lecteur d'écran change donc de voix avec lui.

**Quelque chose cloche / j'ai trouvé un bug.**
Utilisez le bouton de feedback (icône message dans l'en-tête) — il crée un
ticket avec le contexte de la page, visible sur la page *Tickets* de **votre
instance** : il arrive à qui l'administre, pas aux développeurs de LitUbik.
L'admin de l'app peut exporter tous les tickets (avec leurs commentaires)
en CSV depuis cette page. Un bug de LitUbik lui-même se signale dans le
suivi des tickets du dépôt public (github.com/abequet/litubik_public).

**Où sont stockées mes données ?**
Dans le dossier `data/` à côté de l'app (base SQLite + PDF). Sauvegardez ce
dossier ; sur un serveur, gardez `LITUBIK_SECRET_KEY` stable, sinon les
clés API stockées deviennent illisibles.

**Quelle adresse e-mail LitUbik donne-t-il à Crossref, OpenAlex et PubMed ?**
La vôtre si vous en donnez une, sinon aucune. Ces services répondent plus vite
et plus sûrement aux requêtes qui portent une adresse de contact. LitUbik
envoie celle de `LITUBIK_CONTACT_EMAIL` (dans `backend/.env`, ou
l'environnement du serveur) ou, à défaut, l'e-mail Unpaywall global saisi dans
les réglages Full text. Sans l'une ni l'autre, les requêtes partent sans
adresse : cela fonctionne quand même, sur le pool public de ces services.
Aucune adresse fictive n'est jamais envoyée, et rien d'autre ne sort de votre
installation : ni télémétrie, ni vérification de mise à jour.

**Qu'est-ce que l'instance de démonstration ?**
La démo publique permet à chacun d'essayer LitUbik en un clic, sans compte :
sur l'adresse de la démo, *Ouvrir une session invitée* ouvre un bac à sable
personnel avec une revue d'exemple déjà préparée (tri en cours, conflits à
arbitrer, diagramme PRISMA). Ni e-mail ni mot de passe ne sont demandés. Tout
ce que contient la session est supprimé à la remise à zéro quotidienne — ou
immédiatement avec *Terminer la session et supprimer mes données* dans le
menu utilisateur ; quitter une session invitée est définitif, puisqu'elle n'a
pas de mot de passe.

Une session invitée a des limites : quelques projets, imports et recherches
plafonnés à 2 000 références (5 000 par projet), une tâche de fond à la fois,
textes intégraux récupérés uniquement auprès des sources en libre accès, et ni
clés d'API stockées, ni membres, ni synchronisation, ni modification des
prompts. Les fonctions d'IA utilisent la clé de l'instance dans la limite d'un
petit budget — par session, et par jour et par mois pour l'ensemble des
visiteurs — affiché dans le bandeau jaune ; une fois épuisé, l'IA s'arrête
jusqu'à la session, au jour ou au mois suivant.

Les comptes complets et persistants du serveur de démo sont réservés aux
personnes que son administrateur a autorisées (et aux membres qu'un compte
autorisé ajoute à un projet) ; ils se connectent sur l'adresse ordinaire de
l'instance. Les mentions légales, les conditions d'utilisation et la
politique de confidentialité sont accessibles en bas de chaque page. Rien de
tout cela ne s'applique à une installation normale (auto-hébergée ou de
bureau).
