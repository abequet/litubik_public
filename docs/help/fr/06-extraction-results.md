# Extraction, résultats et PRISMA

## Extraction des données

L'étape **Extraction** est un tableau structuré sur les articles inclus.
L'admin du projet définit les colonnes (texte libre, nombres, choix
simple/multiple…) ; l'IA peut suggérer le jeu de colonnes depuis votre
protocole, et préremplir les cellules depuis les PDF — toute valeur
préremplie par l'IA reste marquée jusqu'à validation humaine. L'évaluation
critique a son propre onglet (voir plus bas).

**Modèles de départ.** Les *aides aux colonnes* proposent trois jeux de
colonnes prêts à l'emploi : la **table de synthèse (PICO)** classique, une
**table de synthèse (qualitatif / SPIDER)** pour les revues de points de vue,
d'expériences et de déterminants, et un jeu **synthèse « best fit » à cadre
a priori** qui ajoute les colonnes rendant ce type de synthèse traçable (sur
quel thème *a priori* un résultat a été codé, si le cadre l'accueillait, le
thème émergent sinon, et d'où vient le résultat). Celui que suggère votre type
de revue est mis en évidence, mais tous restent utilisables et combinables — un
modèle n'ajoute jamais que les colonnes dont le nom n'est pas déjà utilisé.

**Plusieurs études dans un article.** Un article rapporte parfois plus d'une
étude (deux expériences, deux cohortes, un pilote puis un essai). Cliquez
**+ étude** sous le titre de l'article pour ajouter une ligne par étude :
chacune a son libellé, son design, ses cellules et son évaluation critique,
et les exports écrivent une ligne par étude (une colonne *Study* les
distingue). La première étude ne peut pas être retirée ; les autres oui,
avec leurs valeurs. La page Résultats compte alors articles et études
séparément, les résultats de synthèse choisissent des *études*
contributrices, et la figure PRISMA affiche à la fois « études incluses » et
« rapports des études incluses ». Une table d'extraction importée peut
porter une colonne *Study* ; sans elle, plusieurs lignes correspondant au
même article deviennent ses études successives. Le préremplissage IA
répond une entrée par étude trouvée dans le PDF et ne fait qu'ajouter des
études, jamais en retirer.

## Évaluation critique

L'onglet **Évaluation critique** évalue chaque étude incluse contre une
checklist choisie d'après son devis d'étude — qualifiez donc le devis
d'abord (à la main, ou via la suggestion IA, depuis l'onglet Table).

**Quel instrument.** LitUbik embarque deux instruments dont les conditions
le permettent : les checklists d'évaluation critique **JBI** et le **MMAT
2018** (Mixed Methods Appraisal Tool, Hong et al., gratuit pour l'éducation
et la recherche). Choisissez-en un dans *Paramètres du projet → Évaluation*.
Redistribuer l'outil d'une autre organisation est une décision de licence,
pas un choix d'empaquetage : une équipe qui en utilise un autre y déclare
**son propre instrument** — un nom, une citation, et une checklist par devis
d'étude dont les questions sont groupées en domaines. Le formulaire
d'évaluation, le graphique par domaine, les exports et le brouillon Methods
lisent chaque instrument de la même façon, et le brouillon cite celui qui est
réellement utilisé.

**Particularités du MMAT.** Le MMAT cote chaque étude sur les cinq critères
de sa catégorie — qualitative, à répartition aléatoire, sans répartition
aléatoire (quasi-expérimentale, cohorte, cas-témoins), descriptive
(transversale, rapport de cas) ou méthodes mixtes — précédés de deux
questions de triage facultatives. Les réponses sont *oui*, *non* ou *ne sait
pas*. Il n'y a **ni score global ni jugement inclure/exclure** : le manuel
déconseille de réduire les cotations à un nombre, donc LitUbik n'affiche
aucun score, la page Résultats ne garde que la vue par critère, et une
évaluation est complète dès que les cinq critères sont cotés. Une étude
mixte est cotée sur les critères 5.1–5.5 *et* sur les critères de ses
composantes qualitative et quantitative (le critère 5.5 se juge à partir
d'eux) : le formulaire présente les blocs de composantes comme facultatifs ;
remplissez la composante quantitative qui s'applique. Les critères sont
reproduits sans les explications du manuel — lisez le manuel pour les usagers
avant d'évaluer. Les revues systématiques et les devis « autre » n'ont pas de
catégorie MMAT.

**Un évaluateur ou deux.** Par défaut, n'importe quel membre évalue n'importe
quelle étude et rien n'est comparé. Dans *Paramètres du projet → Évaluation*,
vous pouvez exiger **deux évaluateurs indépendants**, choisir ce qui compte
comme désaccord (le jugement global seulement, ou n'importe quelle question)
et qui tranche (les évaluateurs par consensus, ou un admin du projet comme
arbitre). Un onglet **Désaccords** liste alors les études où les deux
divergent, côte à côte.

Trancher un désaccord n'écrase jamais ce que chacun a dit : l'évaluation
retenue est enregistrée à part, et les deux évaluations individuelles restent
visibles. Ce n'est pas de la comptabilité — un lecteur est en droit de savoir
que deux évaluateurs ont lu une étude différemment. C'est l'évaluation
retenue que comptent la page Résultats et les exports.

L'évaluation en double indépendante, ou son absence, part dans le brouillon
Methods dans les deux cas. Les outils de triage éditorial la cherchent
explicitement : une évaluation par un seul évaluateur est donc énoncée comme
une limite plutôt que passée sous silence.

## Synthèse et certitude

L'onglet **Synthèse & certitude** est l'endroit où la revue dit comment elle a
synthétisé ses preuves, et avec quelle confiance. Il est éteint par défaut ;
un projet qui ne l'ouvre jamais se comporte exactement comme avant.

### Déclarer la synthèse (SWiM)

Les revues sans méta-analyse se voient reprocher toujours la même chose :
l'étiquette « synthèse narrative » sans description de ce qui a réellement été
fait. La recommandation SWiM (Campbell et al., *BMJ* 2020;368:l6890) en fait
neuf items de rapport, et cet onglet les porte — comment les études ont été
groupées et pourquoi, ce qui a changé depuis le protocole et pour quelle
raison, les critères qui ont priorisé certaines études, comment
l'hétérogénéité a été examinée, comment les données sont présentées, et ce que
la synthèse ne permet pas de conclure.

Tant que vous ne déclarez rien, LitUbik ne met **aucune** méthode dans votre
bouche. Chaque type de revue porte une méthode plausible par défaut, mais le
brouillon Methods la traite comme un défaut, pas comme un compte rendu de ce
que vous avez fait : il écrit un `[À COMPLÉTER]` visible plutôt que de vous
l'attribuer.

### Les résultats, et la méthode qui leur convient

Une revue rapporte des *résultats*, chacun synthétisé à sa façon. Déclarez-les
un par un : les études qui y contribuent, la métrique standardisée, la méthode
de synthèse, et ce que la synthèse a trouvé.

La méthode compte plus qu'il n'y paraît. Le tableau 2 de SWiM apparie chaque
méthode à la question qu'elle peut réellement traiter, et l'application montre
l'appariement au moment du choix : le comptage de votes répond à « y a-t-il
une preuve quelconque d'un effet ? », jamais à « quel est l'effet moyen ? ».
Rapporter le second à partir du premier est précisément le décalage que
l'item 9 de SWiM demande de déclarer comme limite — plus facile à éviter qu'à
avouer.

### Certitude de la preuve (GRADE)

Noter la certitude de la preuve est un attendu méthodologique des revues
Cochrane et l'un des six domaines sur lesquels les éditeurs trient. LitUbik
suit les cinq étapes de Brignardello-Petersen & Guyatt (*Am J Epidemiol*
2025;194:1681-6), **par résultat** — sur les études qui contribuent à ce
résultat, pas sur le corpus.

1. **Intention.** Causalité ou association ? La même preuve se note
   différemment : des études observationnelles qui répondent à une question de
   causalité démarrent bas ; pour une question d'association, elles démarrent
   haut, parce qu'elles y sont le devis approprié.
2. **Cible et seuils.** Notez-vous la certitude d'un effet de taille
   quelconque, ou d'un effet assez grand pour importer ? Prédéfinissez les
   seuils — GRADE les demande avant la notation, pas après.
3. **Point de départ.** Proposé d'après les devis qualifiés des études
   contributives, avec les décomptes qui motivent la proposition. Vous
   tranchez.
4. **Les huit domaines.** Cinq qui abaissent la certitude (risque de biais,
   incohérence, imprécision, caractère indirect, biais de publication), trois
   qui peuvent la rehausser. Pour le risque de biais, les évaluations de ces
   études précisément vous sont mises sous les yeux — y compris « aucune n'a
   été évaluée », ce qui rend vérifiable un jugement d'« aucune préoccupation
   sérieuse ». Pour le biais de publication, la recherche réellement menée.
5. **Le niveau.** L'application calcule ce que donne son arithmétique et
   l'affiche à côté de votre décision. Quand les deux diffèrent, elle le dit
   au lieu d'en taire une : GRADE autorise explicitement deux préoccupations
   moins que sérieuses dans des domaines différents à coûter un niveau à elles
   deux, ce qu'aucune formule ne reproduit.

Choisir un niveau rédige un brouillon de l'énoncé en langage clair que demande
la GRADE guideline 26. Notez où loge la certitude : dans le verbe. « Réduit
probablement » **est** la phrase de certitude modérée — pas une réserve
ajoutée à une phrase assurée.

**GRADE n'est pas universel.** Il note la certitude d'estimations
quantitatives. Une revue qui synthétise des résultats qualitatifs relève de
GRADE-CERQual, et SWiM exclut lui aussi la synthèse qualitative (ENTREQ et
eMERGe la couvrent). Si votre cadre de question suggère une synthèse
qualitative, l'application le signale — comme un avertissement, pas comme un
verrou.

### Summary of Findings

La table que réclament les éditeurs, assemblée depuis ce que vous avez
déclaré : une ligne par résultat, ses études contributives, les effectifs
totalisés depuis votre table d'extraction, la méthode, la certitude et
l'énoncé en langage clair. Exportable en CSV. Un résultat jamais noté affiche
« non notée » plutôt qu'une cellule vide — une colonne de certitude vide se
lit comme une colonne confiante.

## Vers la méta-analyse

LitUbik ne combine pas les études — le modèle, ses hypothèses et leur
justification vous appartiennent — mais il calcule ce dont une méta-analyse
a besoin et le transmet. Sur un résultat déclaré, **Tailles d'effet** permet
à un admin du projet de choisir une mesure (différence de moyennes
standardisée en *g* de Hedges, différence de moyennes, odds ratio, risque
relatif, corrélation en *z* de Fisher) et d'associer ses entrées (N,
moyenne, ET, événements, *r*) aux colonnes d'extraction numériques. Chaque
étude contributrice reçoit alors son estimation, sa variance et son
intervalle de confiance à 95 %, calculés exactement comme `escalc()` de
metafor (correction petit échantillon pour *g*, correction de continuité
usuelle pour les cellules nulles) ; une étude dont une cellule manque ou
est en conflit est listée avec la raison, jamais écartée en silence. Le
tableau s'accompagne d'un forest plot sans losange combiné, exportable en
PNG, et de trois exports : un lot **R / metafor** (`data.csv`, une ligne
par étude, plus `analysis.R` qui recalcule les effets depuis les données
brutes en guise de contrôle, ajuste un modèle à effets aléatoires et trace
forest et funnel plots), un CSV **RevMan Web** disposé comme son modèle de
résultats d'étude (une ligne par bras, Study ID égal à celui de l'étude
incluse — RevMan Web génère le modèle par revue, faites correspondre les
en-têtes au vôtre avant l'import), et un CSV long de tous les résultats
quantitatifs du projet depuis l'onglet *Synthèse & certitude*.

## Importer une table d'extraction d'une autre plateforme

Votre revue a commencé ailleurs (Excel, export Covidence, Rayyan…) ? Dans
**Extraction → Réglages**, l'admin du projet peut téléverser la table
d'extraction existante au format **.xlsx**. LitUbik propose une
correspondance des colonnes du tableur — lesquelles sont des métadonnées
d'article (titre, DOI, auteurs, année…) et lesquelles sont des colonnes
d'extraction (rapprochées par nom de votre grille, ou créées à la volée).
Les lignes sont rapprochées des articles du projet par DOI, puis par
titre ; les articles introuvables peuvent être créés automatiquement et
entrent directement dans le corpus d'extraction, marqués comme inclus
(ils ont été screenés sur l'autre plateforme). Les cellules non vides sont
enregistrées comme valeurs validées ; les cellules vides restent vierges
pour que l'équipe complète la table dans l'application. Réimporter un
fichier mis à jour écrase simplement vos valeurs importées précédentes.

## Résultats

La page **Results** met le corpus inclus en graphiques : publications par
année, par pays, designs d'étude, et toute colonne d'extraction
catégorielle. Les graphiques sont interactifs : cliquez sur une barre
d'année, une barre de design ou un pays sur la carte pour filtrer tous les
graphiques d'un coup (des barres grises « fantômes » gardent visibles les
totaux non filtrés derrière les valeurs filtrées, et le badge de chaque
carte affiche `n=filtré / total`) ; la barre de filtres au-dessus des
graphiques résume et réinitialise les filtres actifs. Chaque graphique a
un menu **Exporter** (téléchargement PNG ou SVG, copie de l'image, copie
des données agrégées) et un bouton **Données** qui montre les mêmes
chiffres en tableau ; un bouton au niveau de la page exporte d'un coup
tous les graphiques de l'onglet courant. Les tuiles d'en-tête suivent la
progression vers la complétude (extraction, validation, évaluation)
et pointent vers l'écran qui fait avancer le chiffre. Une **synthèse
narrative** optionnelle peut être générée par l'IA depuis le tableau
d'extraction — relisez-la et modifiez-la avant tout usage.

L'onglet **Thèmes** cartographie le corpus en un nuage de points, un par
référence, regroupés par sujet. Choisissez le corpus (toutes les références
uniques, celles incluses au titre/résumé, ou celles incluses au texte
intégral) et laissez le nombre de groupes se choisir automatiquement
(silhouette) ou fixez-le ; titres, résumés et mots-clés sont vectorisés
(TF-IDF), réduits (SVD) et disposés en deux dimensions (t-SNE), puis les
groupes sont découpés sur cette carte (k-means sur la disposition) : chacun
est une région d'un seul tenant, numérotée à partir de la plus grande —
entièrement sur ce serveur, sans IA. Chaque groupe apparaît comme un halo
translucide autour de ses points avec un libellé en son centre ; la couleur
est le groupe, le marqueur la décision de screening (plein = inclus, anneau
= exclu, pâle = en attente) : un amas de points exclus ou en attente montre
d'un coup d'œil où le corpus s'amincit. Chaque groupe liste ses termes
saillants ; nommez-le à la main, ou demandez à l'IA des libellés suggérés
(marqués *IA* tant que vous ne les avez pas modifiés). Survolez un groupe
dans la légende pour le mettre en évidence sur la carte, survolez un point
pour l'article, cliquez pour sa fiche, masquez des groupes depuis la légende
(la carte se recadre sur ce qui reste), exportez la carte en PNG et
l'affectation en CSV ; le bouton **Tableau** montre la même affectation en
tableau simple. Chaque calcul est conservé, une carte antérieure peut être
rouverte. Il faut au moins six références, et cela fonctionne avant tout
screening — c'est une aide au cadrage, pas un résultat : deux groupes
voisins sont deux faces d'une même région, pas deux sujets sans rapport, et
un nouveau calcul redispose la carte.

## PRISMA

La page **PRISMA** assemble le diagramme de flux automatiquement depuis les
chiffres réels du projet : références identifiées par base, doublons
retirés, références screenées et exclues, textes intégraux évalués avec
motifs d'exclusion, rounds de snowballing, et le corpus final inclus. Il
suit le gabarit PRISMA 2020 : les trois bandes d'étape (*Identification*,
*Screening*, *Inclus*) à gauche, la colonne principale qui descend avec une
flèche vers chaque boîte d'exclusion à droite, une seconde colonne
d'identification (*via d'autres méthodes* : recherche de citations, ajouts
manuels) dès qu'elle existe, les deux convergeant vers l'unique boîte
*Études incluses*. Les boîtes en pointillés marquent les étapes pas encore
atteintes. Le menu **Exporter** au-dessus de la figure la télécharge en
**PNG** (résolution d'impression) ou en **SVG** (vectoriel, pour les revues
qui le demandent), ou copie l'image dans le presse-papiers ; les réserves en
direct (dédoublonnage inachevé, totaux provisoires) s'affichent sous la
figure et ne sont jamais exportées.

Sous le diagramme, **Activité des relecteurs sur l'ensemble de la revue**
résume ce que chaque membre a fait, toutes itérations confondues (recherche
initiale et chaque itération de snowballing) : titres/résumés et textes
intégraux criblés à la main sur ceux attribués, conflits tranchés, doublons
arbitrés, références extraites et évaluations critiques. Une barre empilée
par étape montre la répartition inclure / exclure / peut-être de chaque
relecteur à côté de celle de l'équipe, et le kappa de Cohen par paire est
recalculé sur toutes les références doublement criblées de la revue — un
petit round de snowballing ne donne plus un kappa sur une poignée de
références. Travail humain uniquement : les suggestions IA ne sont pas
comptées, et les titres exclus via le triage IA validé sont distingués de ce
que le relecteur a réellement lu.
