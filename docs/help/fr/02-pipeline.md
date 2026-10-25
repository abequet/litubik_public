# Le pipeline de revue

## Type de revue et cadre de la question

Deux réglages, dans *Paramètres du projet → Général*, décident du vocabulaire
de toute la revue :

- **Type de revue** — revue systématique classique, ou *synthèse « best fit » à
  cadre a priori* (Carroll & Booth, 2013).
- **Cadre de la question** — PICO, PICOS, **SPIDER** (Cooke, Smith & Booth,
  2012 : Sample, Phenomenon of Interest, Design, Evaluation, Research type),
  SPICE, PEO, ou un cadrage libre/adapté.

Ils changent la façon dont l'application vous parle et parle à l'IA : les
rubriques que l'extraction du protocole cherche, le nom des blocs de concepts,
le modèle de colonnes d'extraction proposé, et ce que le brouillon de la
section Methods affirme que la revue est.

**Ils ne changent rien au pipeline lui-même.** Les douze étapes ci-dessous sont
les mêmes quel que soit votre choix. En particulier, choisir une synthèse
« best fit » ne vous donne pas d'outil pour le cadre *a priori* : LitUbik ne
mène qu'un seul brin de recherche, n'a pas d'objet pour ce cadre et ne code pas
les données contre lui. Construisez le cadre et faites ce codage hors de
LitUbik — le modèle d'extraction `Synthèse « best fit » à cadre a priori` vous
donne des colonnes pour consigner le thème sur lequel un résultat a été codé,
ce qui n'y entrait pas, et d'où vient chaque résultat — et le brouillon Methods
dira que le logiciel n'a pas outillé cette partie, au lieu de s'en attribuer le
mérite.

Changer de cadre s'applique à la **prochaine** extraction du protocole : un
protocole déjà extrait conserve son texte (qui reste modifiable à la main).

## Les douze étapes

Chaque projet suit les mêmes douze étapes. Rien n'est jamais supprimé entre
les étapes : chaque référence garde sa provenance pour le rapport PRISMA.

1. **Protocol** — questions de recherche, éléments de votre cadre de question,
   règles d'inclusion/exclusion. Rédigé en Markdown ; l'assistant IA peut
   proposer une première version à partir de la description de votre sujet.
2. **Equations** — construisez l'équation de recherche à partir de vos
   concepts (les mots-clés d'un bloc sont combinés en OR, les blocs en AND ;
   deux concepts placés dans le même bloc sont combinés en OR), avec conseils
   IA et traduction par base (chaque carte de base affiche la syntaxe
   traduite).
3. **Search** — lancez les équations sur les bases connectées (OpenAlex,
   PubMed, Europe PMC, arXiv, Scopus, IEEE…) ou importez manuellement les
   fichiers d'export pour les bases en mode manuel assisté. Une *revue
   vivante* peut planifier des passes de mise à jour ensuite ; chaque passe
   est criblée comme un tour à part entière.
4. **Dedup** — détection automatique des doublons avec revue manuelle des
   paires incertaines.
5. **Screening** — screening titre/résumé. Chaque référence reçoit des votes
   include/exclude/maybe des reviewers assignés ; les conflits se résolvent
   dans une vue dédiée.
6. **FT retrieval** — récupération des PDF des références incluses (sources
   open access, ou votre accès institutionnel).
7. **FT screening** — screening du texte intégral selon les critères du
   protocole, avec motifs d'exclusion (ils alimentent le diagramme PRISMA).
8. **Snowballing** — exploration des références et citations des articles
   inclus, par rounds ; les nouveaux candidats repassent par le screening.
   Un round lancé par erreur (p. ex. amorcé par un article inclus à tort) ?
   Depuis *Snowballing → Itérations*, un admin peut supprimer le **dernier**
   round — ses articles découverts, leur screening et ses liens de citation
   sont retirés, comme s'il n'avait jamais eu lieu (uniquement le plus récent ;
   à retirer du plus récent au plus ancien).
   Le **réseau de citations**, en bas de la page, a deux vues. *Itérations*
   (par défaut) ne montre que les articles retenus, une colonne par tour,
   chacun relié à la graine dont l'exploration l'a trouvé (trait plein =
   trouvé dans ses références, pointillé = trouvé parmi les articles qui la
   citent). La barre à côté d'une graine résume ce que son exploration a
   ramené (◀ en arrière, ▶ en avant) ; l'en-tête de chaque colonne donne le
   rendement du tour, et son pied compte les articles non retenus — un clic
   affiche leur liste, les plus liés d'abord. Un tour qui ne retient plus rien
   signale la saturation. *Réseau* dessine les articles retenus et ceux que
   plusieurs graines partagent ; les articles trouvés par une seule graine sont
   repliés en un anneau par graine (un clic les déploie en éventail). Son filtre
   *Itérations affichées* ajoute les tours sans rien déplacer. Les deux vues
   s'exportent en PNG ou en SVG, et **Données** liste tous les articles en
   tableau.
9. **Extraction** — extraction structurée dans un tableau configurable
   (colonnes définies par l'admin du projet), avec préremplissage IA
   optionnel que vous validez cellule par cellule.
10. **Results** — graphiques (par année, pays, design…) et synthèse
    narrative IA optionnelle.
11. **PRISMA** — le diagramme de flux est généré automatiquement à partir de
    tout ce qui précède, exportable pour votre article.
12. **Reporting** — la section Méthodologie de votre article, rédigée depuis la
    piste d'audit de tout ce qui précède, et une déclaration d'usage de l'IA
    rédigée depuis le journal d'usage du projet. Deux brouillons modifiables
    (voir *Reporting*).

## Exporter les références

À n'importe quel stade, l'entrée **Export references** de la barre latérale
télécharge les références du projet — toutes, ou seulement celles incluses,
exclues ou encore en attente (les décisions full text priment sur celles
titre/résumé) — au format **RIS**, **BibTeX** ou **CSV**. RIS et BibTeX se
réimportent proprement dans Zotero, EndNote ou un autre projet LitUbik ; le
CSV ajoute une colonne `screening_status`.

Le même dialogue peut **envoyer les références directement dans Zotero**
(destination *Zotero*) une fois votre bibliothèque connectée dans *Mes
intégrations* avec une clé ayant l'accès en écriture. Choisissez une
collection existante ou laissez LitUbik créer `LitUbik – <projet>` : chaque
référence devient un item étiqueté `litubik:included` / `excluded` /
`undecided` plus ses tags LitUbik, la décision étant notée dans le champ
*Extra*. Une référence déjà envoyée est mise à jour sur place (ses tags et
collections Zotero sont conservés), jamais dupliquée. Les PDF ne sont pas
envoyés.
