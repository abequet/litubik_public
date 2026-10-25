# Rechercher dans les bases et importer des références

## Construire l'équation : concepts et blocs

Sur la page **Équations**, vous listez vos concepts et leurs mots-clés, puis
vous les combinez en variantes. Les mots-clés d'un bloc sont combinés en
**OR**, les blocs entre eux en **AND** :

    (older adults OR elderly) AND (gamification OR "serious games")

Par défaut, chaque concept forme son propre bloc. Pour chercher *l'un ou
l'autre* de deux concepts au lieu des deux, placez-les dans le **même bloc** :
à côté de chaque concept sélectionné, un petit sélecteur indique son bloc. La
ligne d'aperçu sous le formulaire montre ce que vous allez créer, p. ex.
`(Population OR Setting) AND Intervention`. Un bloc fusionné est simplement
l'union des mots-clés de ses concepts — rien d'autre ne change dans
l'équation, et toutes les traductions par base suivent.

Si votre protocole nomme déjà ses propres concepts et mots-clés de recherche,
l'extraction du protocole les conserve (section *Search concepts* du protocole
généré) et **Proposer depuis le protocole** part de ceux-là au lieu d'en
inventer d'autres. Relancer la proposition n'écrase jamais votre travail : les
concepts déjà listés ne reçoivent que des mots-clés supplémentaires.

Le bouton **Synonymes IA** d'un concept fonctionne de la même façon — la
question de recherche, le protocole et les autres concepts lui sont fournis,
pour que ses suggestions restent sur l'axe de ce concept. Rien n'est jamais
appliqué sans vous : chaque mot-clé reste modifiable et supprimable.

## Coller une équation écrite ailleurs

Un protocole arrive souvent avec son équation déjà construite et testée :
cinquante lignes de syntaxe PubMed, avec des balises `[tiab]` et `[MeSH]`
qu'aucun constructeur par concepts ne reproduirait. Basculez le formulaire
*Nouvelle variante* en **saisie par base**, donnez un libellé à la variante
(*Éq. 6*), choisissez la base pour laquelle le texte est écrit et collez-le.
Rien n'est généré : ce que vous avez tapé est ce que les décomptes exécutent,
ce que la page Recherche lance ou affiche pour l'export manuel, et ce que le
rapport de recherche cite.

Les autres bases interrogées par la revue sont **pré-remplies par l'IA**
juste après la création (la case *Pré-remplir les autres bases par IA* est
cochée par défaut ; le formulaire indique combien de bases et le coût
approximatif). Un appel par base tourne en arrière-plan, chaque ébauche
devient la requête de cette base, et la carte de la variante comme les
cartes de la page Recherche l'affichent avec le badge **ébauche IA, non
relue**. L'ébauche est utilisable aussitôt — décomptes, recherches, bouton
Copier pour un export manuel — mais elle reste marquée tant qu'un humain
n'a pas cliqué **Valider l'ébauche** après l'avoir lue, ou modifié le texte
(un texte modifié est le vôtre, le badge disparaît). Le rapport de recherche
et l'audit des Méthodes disent quelles requêtes ont tourné en ébauche non
relue : relisez-les avant la vraie recherche. **Ébaucher les … manquantes par
IA**, sur la carte ou sur la page Recherche, ébauche toute base encore sans
requête, depuis le premier texte écrit par l'équipe.

On peut aussi travailler base par base : ouvrez une ligne, tapez sa
requête, ou cliquez sur **Ébaucher par IA depuis…** pour obtenir une ébauche
dans l'éditeur avec les remarques du modèle (un terme MeSH qu'il a dû
abandonner, par exemple), puis *Enregistrer*. Une variante saisie garde
l'étiquette *saisie* ; elle se gèle, se compte et se duplique comme les
autres.

Les bases que tout cela couvre sont un réglage du projet : *Paramètres →
Clés bases de données → Bases interrogées par cette revue*. Cochez celles
que votre protocole nomme (les bases déclarées comptent toujours) ; les
pages Équations et Recherche, les décomptes, les ébauches, les contrôles de
rappel et le rapport PRISMA-S suivent alors cette liste au lieu de tout le
registre.

**Dupliquer** crée un nouveau brouillon avec les mêmes requêtes : c'est ainsi
qu'on dérive *Éq. 6 bis* d'*Éq. 6* pour tester un seul changement. Les
décomptes et les contrôles de rappel restent sur l'original.

## Gold set et rappel par base

Le panneau **Golden set** liste les références que toute équation acceptable
doit retrouver, par **DOI ou PMID** (une à la fois, ou plusieurs lignes d'un
coup) ; l'identifiant manquant est cherché sur PubMed. **Vérifier le
rappel** sur une variante répond ensuite à la question du protocole *chaque
référence est-elle retrouvée dans chaque base ?* de deux façons, consignées
côte à côte sur la carte et dans le rapport de recherche :

- **API** — PubMed (par PMID), OpenAlex, Europe PMC, et Scopus ou Web of
  Science quand leur clé est configurée, sont interrogés : leur recherche
  pour l'équation retrouve-t-elle chaque référence ?
- **import** — pour chaque base dont vous avez importé des références
  (EBSCO, TRID, ACM, Compendex… ou une recherche API), les références sont
  cherchées parmi les notices importées sous cette source pour la variante.
  Ce contrôle tourne tout seul après chaque import : un export déposé sur une
  carte met la pastille à jour aussitôt.

Chaque pastille se lit *trouvées/total* ; son infobulle nomme les références
manquées. Une référence connue seulement par son DOI ne peut pas être
contrôlée sur PubMed et y compte comme manquée, ce qui est la règle même du
protocole : une référence est attendue partout où elle est indexée.
L'historique de chaque contrôle est conservé par variante.

## Bases connectées

Sur la page **Search**, chaque base a sa propre carte. Les bases à API
ouverte fonctionnent sans configuration : **PubMed**, **OpenAlex**,
**Semantic Scholar**, **Crossref**, **Europe PMC** (PubMed + PMC + les
preprints bioRxiv, medRxiv, ChemRxiv, Research Square et SSRN — cochez le
type de document *Preprint* dans l'équation pour les inclure ; il n'y a pas
de carte bioRxiv séparée), **arXiv** (physique, maths, informatique,
biologie quantitative, statistiques — une requête toutes les 3 s, un gros
téléchargement prend donc quelques minutes), **HAL** (l'archive ouverte
française, toutes disciplines) et **DOAJ** (revues en libre accès). Les
bases à clé API demandent une clé configurée — **Scopus** et **IEEE
Xplore** (clés via l'abonnement de votre institution), **Web of Science
Starter** (abonnés, via la bibliothèque ; l'API Starter renvoie des titres
sans résumés), **CORE** (agrégateur de libre accès, clé gratuite sur
core.ac.uk), **Lens.org** (Crossref + PubMed + OpenAlex + CORE, jeton
gratuit pour usage non commercial, à demander sur lens.org) et **Springer
Nature** (Springer, Nature, BMC, clé gratuite sur dev.springernature.com) :

- **clés du projet** — *Settings → Database keys* du projet (admin projet) ;
  un helper sur chaque carte indique où demander la clé (généralement via
  l'abonnement de votre institution), ou
- **clés globales de l'app** — *Administration → Database keys* (superadmin).

Sans clé, la base n'est pas bloquée : sa carte passe en **mode manuel
assisté** — l'app affiche l'équation traduite dans la syntaxe de cette base,
vous la lancez sur le site de la base et importez le fichier d'export.

Lancez la recherche depuis la carte ; les résultats sont importés avec leurs
métadonnées complètes et tracés avec leur base source et l'équation utilisée.

## Bases en mode manuel assisté

Certaines bases n'ont pas d'API utilisable (Web of Science sans abonnement,
EBSCO, TRID, Compendex, ACM DL, Google Scholar…). Leur carte affiche
l'**équation traduite** à copier dans l'interface de la base, puis permet
d'**importer le fichier d'export**. Formats acceptés : RIS (`.ris`, y compris
ceux d'EBSCO et d'ACM), PubMed MEDLINE (`.nbib`, ou `.txt` de *Save → PubMed
format*), BibTeX (`.bib`) et CSV (l'export CSV de Scopus ; un export Web of
Science *tab-delimited* passe une fois renommé en `.csv`). EndNote XML et le
*plain text* de Web of Science ne sont pas lus : ré-exportez dans l'un des
formats ci-dessus. Un PMID porté par le fichier (`.nbib`, RIS PubMed, EBSCO
MEDLINE) est conservé : c'est une clé exacte de dédoublonnage et ce que le
contrôle du gold set recherche.

Avant de déposer le fichier, déclarez ce que PRISMA-S demande : le jour où
vous avez lancé la recherche sur la base (**Recherche du**) et le nombre de
résultats qu'elle affichait (**Résultats affichés**) — un export est souvent
déposé des jours plus tard et peut être plafonné en dessous du vrai nombre.
Les deux figurent dans le tableau des imports et dans le rapport de
recherche ; une recherche API les remplit elle-même. Les références importées
ainsi portent la même provenance que les résultats API.

D'autres items PRISMA-S accompagnent chaque dépôt, export de base ou import
libre : **Limites de dates**, **Limites disciplinaires** et **Limites de
types de documents** — une restriction de dates, une restriction
disciplinaire (domaines) et une restriction de types de documents ont-elles
réellement été appliquées en interrogeant cette source ? Si des disciplines
ou des types de documents ont été appliqués, nommez-les dans le champ qui
apparaît (*Psychologie, Ingénierie, Transports* ; *Article, Review* : les
listes proposées par la base, séparées par des virgules). **Recherche dans**
indique les champs sur lesquels la requête a porté — titre, résumé,
mots-clés, texte intégral ou tous les champs ; cochez tous ceux qui
s'appliquent. Laissez *non déclaré* et ne cochez rien si vous l'ignorez ; les
réponses apparaissent dans la colonne **Limites** du tableau des imports et
dans le rapport de recherche. Une recherche API les fixe depuis les
paramètres de l'équation.

Les références arrivées **sans résumé** (Web of Science Starter, Scopus sans
jeton institutionnel, beaucoup d'exports manuels) sont complétées en arrière-
plan juste après l'import, depuis des API ouvertes uniquement (OpenAlex,
Semantic Scholar, PubMed) : rien à cliquer, les résumés apparaissent dans le
tableau en une ou deux minutes. Celles qu'aucune source ouverte ne décrit
gardent un résumé vide ; la page **Snowballing** propose toujours la passe
manuelle plus profonde, qui lit aussi les pages des éditeurs.

**Tour** : un export appartient par défaut à la **recherche initiale**,
même déposé après le début du screening — l'export d'une base arrive souvent
quelques jours après les autres, et ses références rejoignent simplement
les files du tour en cours. Choisissez **mise à jour de la recherche**
quand le fichier est une *relance* de la recherche (avant soumission, par
exemple) : il devient alors une passe de mise à jour avec son propre tour
(dédoublonnage immédiat, tour de screening suivant ouvert, équipe
notifiée), exactement comme une recherche API lancée pendant le screening.

## Ajouter soi-même une base de données

La liste intégrée (PubMed, OpenAlex, Semantic Scholar, Crossref, Europe PMC,
arXiv, HAL, DOAJ, Web of Science, Scopus, IEEE Xplore, CORE, Lens.org,
Springer Nature, EBSCO PsycINFO/PsycARTICLES, ACM DL, TRID, Compendex, Google
Scholar) couvre rarement toutes les sources d'une revue : portail national
(Cairn, Érudit), dépôt de thèses et mémoires (theses.fr, DUMAS), base de
domaine (ERIC, Embase), littérature grise…

Un admin du projet en ajoute une dans *Paramètres → Clés bases de données →
Bases ajoutées par ce projet* :

- **nom** — ce que verront vos co-relecteurs, et le nom de source de chaque
  import provenant de cette base ;
- **syntaxe de l'équation** — l'app ne peut pas connaître le langage
  d'interrogation d'une base quelconque : choisissez la plus proche parmi les
  bases intégrées (ou la chaîne booléenne générique) et ajustez l'équation à
  la main sur la page Équations si nécessaire ;
- **lien et instructions** (facultatifs) — affichés sur la carte, pour que
  tout le monde cherche et exporte de la même façon.

La base se comporte ensuite comme n'importe quelle base en mode manuel
assisté : elle apparaît sur la page Équations (équation traduite, comptage
manuel) et sur la page Recherche (instructions + import de fichier), et ses
références comptent dans le PRISMA. La supprimer plus tard ne retire que la
carte — les références déjà importées gardent leur source.

## Importer depuis Zotero

Si vos références sont déjà dans **Zotero**, connectez votre bibliothèque une
fois pour toutes (barre latérale → *Mes intégrations* : collez une clé API
créée sur zotero.org/settings/keys avec *Allow library access*, puis choisissez
votre bibliothèque personnelle ou l'un de vos groupes). La page Recherche
affiche alors une carte **Bibliothèque Zotero** : choisissez une collection
(ou toute la bibliothèque), indiquez si elle compte comme **recherche en
base** ou comme **autre source** pour le PRISMA, cochez *Récupérer aussi les
PDF joints* si vous les voulez dans la bibliothèque full text, et importez.
L'import tourne en arrière-plan, est archivé et tracé comme n'importe quel
import de fichier (source `zotero:<collection>`), et dédoublonné aussitôt.
Chaque référence importée garde la trace de son item Zotero : un envoi
ultérieur vers Zotero mettra ces items à jour au lieu d'en créer des copies.

## Revue vivante : passes de mise à jour

Une revue peut rester vivante après la première recherche. Sur la page
**Search**, le panneau *Revue vivante — mises à jour de la recherche* (admin
du projet) permet de :

- **planifier** des passes de mise à jour tous les 7, 14, 30 ou 90 jours sur
  les bases API cochées (l'équation gelée est relancée ; on ne demande à
  chaque base que ce qu'elle a indexé depuis la passe précédente — PubMed par
  date Entrez, OpenAlex et Crossref par date de création, Europe PMC, arXiv,
  HAL et DOAJ par date de dépôt, Scopus par date de chargement ; Semantic
  Scholar et IEEE ne savent pas filtrer ainsi, ils sur-récupèrent et le
  dédoublonnage absorbe le recouvrement) ;
- **lancer une mise à jour maintenant**, sur les mêmes bases ;
- lire l'**historique des passes** (date, bases, références récupérées,
  nouvelles uniques) et supprimer la dernière si elle a mal tourné.

Chaque passe est un **tour à part entière**, comme une itération de
snowballing : les nouvelles références sont dédoublonnées contre tout le
corpus, un tour de screening titre/résumé s'ouvre avec les reviewers et les
règles du tour précédent, le tour texte intégral est préparé en brouillon,
et PRISMA montre la passe dans sa propre colonne (*Mise à jour 1, 2…*).
Chaque membre reçoit une notification dans l'app (cloche de l'en-tête,
pastille sur la carte du projet) indiquant combien de nouveaux candidats
sont à cribler. Le brouillon de Méthodes liste les dates de mise à jour et
la cadence.

**Lancer une recherche depuis une carte pendant qu'un tour de screening est
actif** fait la même chose : la recherche devient une passe de mise à jour
avec son propre tour, pour qu'aucune référence ne se glisse dans un tour
dont le screening a déjà commencé. Avant tout screening, une recherche
étend simplement le tour 1. Dans les deux cas le dédoublonnage tourne juste
après la recherche.

Les passes planifiées s'exécutent sur l'instance coordinatrice tant qu'elle
tourne (vérification toutes les heures) ; pas d'e-mail — la notification est
dans l'app.
