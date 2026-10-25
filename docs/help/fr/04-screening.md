# Screening (titre/résumé et texte intégral)

## Comment marchent les votes

Chaque référence est screenée par les reviewers qui lui sont assignés
(l'allocation est réglée par l'admin du projet dans les paramètres de
screening : nombre de reviewers par référence, qui screene quoi). Un vote
est **include**, **exclude** ou **maybe**. Quand les votes requis
concordent, la décision est actée ; en cas de désaccord la référence
apparaît dans la vue **Conflicts**, où elle se discute et se résout.

## Lots pondérés et binômes tournants

Pour une équipe où chacun ne prend pas la même part du travail, l'admin du
projet peut répartir le tour en **lots pondérés** (*Qui trie quoi* → *Lots
pondérés*) :

- le corpus est découpé, dans l'ordre du corpus, en **lots** d'une taille
  choisie (100 références par défaut) ;
- chaque lot est trié par **un binôme** de relecteurs : chaque référence
  reçoit donc toujours deux votes ;
- chaque relecteur déclare une **part du travail en pourcentage** (la somme
  fait 100 ; *Répartir à parts égales* les remplit) ; les binômes sont
  choisis lot après lot pour que chacun termine à un lot près de sa part, et
  les binômes **tournent** — à parts égales, chaque binôme reçoit un lot
  avant qu'un binôme n'en reçoive un second ;
- en résolution des conflits *Arbitre*, les **deux arbitres** au plus
  désignés pour le tour ne sont jamais en binôme sur un même lot, pour qu'un
  conflit ait toujours un arbitre qui n'a pas voté dessus.

**Aperçu des lots** montre le plan avant tout démarrage : une ligne par lot
avec son binôme, modifiable, et une échéance à fixer. La part effective de
chaque relecteur se met à jour au fil des modifications. **Exporter le
plan (CSV)** télécharge le plan en l'état, au même format que le CSV de
répartition, pour le déposer avec le protocole avant le démarrage du tour.
**Démarrer le tri avec ces lots** applique ce plan — c'est lui qui est
publié.

Les références qui entrent dans le tour plus tard (snowballing, passes de
mise à jour de la recherche, import tardif) forment de **nouveaux lots**,
numérotés à la suite, sur les quotas restants.

Le **Tableau de bord** montre ensuite la *part par relecteur* (effective
contre déclarée) et le tableau des *lots* : binôme, avancement de chaque
relecteur, échéance, statut (*ouvert*, *en retard* une fois l'échéance
passée, *fermé* quand tous les votes du lot sont faits). **CSV de
répartition** télécharge une ligne par lot — lot, taille, relecteur A,
relecteur B, échéance, statut — la répartition à déposer avec le protocole.

## Relecteur pivot : un relecteur trie tout, les autres se partagent

Quand une personne — typiquement le ou la responsable de la revue — veut
passer sur chaque référence pendant que le reste de l'équipe se partage la
charge, choisissez *Qui trie quoi* → **Relecteur pivot**. Désignez le pivot
parmi les relecteurs cochés (vous-même par défaut). Chaque référence reçoit
alors exactement **deux votes** : celui du pivot et celui d'un co-relecteur.
Avec 100 références et deux co-relecteurs, le pivot en trie 100, chaque
co-relecteur 50 ; avec trois, 34 / 33 / 33.

Les co-relecteurs se partagent le corpus **à parts égales**, sauf si vous
déclarez leurs **parts en pourcentage** (la somme fait 100 sur les
co-relecteurs seulement ; *Répartir à parts égales* les remplit). Les
références sont distribuées dans l'ordre du corpus au co-relecteur le plus
en retard sur sa part, la répartition est donc reproductible. Les
références tardives (snowballing, passes de mise à jour) vont au pivot plus
au co-relecteur suivant dans cet équilibre.

Les conflits entre le pivot et un co-relecteur se résolvent comme dans
toute autre répartition (consensus ou arbitre). Le kappa est celui de Cohen
avec un seul co-relecteur ; avec plusieurs, la *matrice croisée des votes*
montre une matrice par binôme pivot/co-relecteur. Le Tableau de bord
affiche la *part par relecteur* (effective contre déclarée) des
co-relecteurs.

Avec un seul co-relecteur, cette répartition revient à *Tout le monde trie
chaque référence*. L'option existe aux deux étapes, titre/résumé et texte
intégral.

## Relecteurs anonymes

Le double aveugle masque les *votes* tant qu'une référence n'est pas
complète ; il ne masque pas *qui* trie avec qui. Quand l'équipe préfère ne
pas le savoir — pour qu'un désaccord se discute sur l'article et non sur la
personne — l'admin du projet coche **Relecteurs anonymes** dans les
réglages du screening, à l'une ou l'autre étape (titre/résumé, texte
intégral). L'option est figée au lancement du tour, comme le reste de la
configuration.

Tant que le tour est en cours, **personne — admins et arbitres compris — ne
voit le nom d'un relecteur** : partout où un nom apparaîtrait (les votes
d'un conflit, l'avancement par relecteur, les matrices de kappa, les lots
et leurs binômes, le CSV de répartition, les notes de screening, les
surlignages PDF) il est remplacé par un pseudonyme stable, *Reviewer 1*,
*Reviewer 2*… — le même pour tout le monde, le vôtre compris, signalé
*(vous)* sur vos votes. Le tableau *Activité des relecteurs* de la page
PRISMA est masqué en entier, car ses autres colonnes (doublons,
extraction) trahiraient les pseudonymes. Les noms reviennent **une fois le
tour terminé** : toutes les références votées et tous les conflits
résolus. Un conflit résolu reste donc pseudonyme tant que d'autres
références sont ouvertes.

Deux choses que l'option ne peut pas faire : cacher le relecteur pivot à
l'admin qui l'a choisi, et avoir un sens à deux relecteurs — chacun sait
qui est l'autre.

## Résoudre les conflits — et annuler une résolution

Chaque carte de l'onglet **Conflicts** montre les votes, les notes des
reviewers et l'abstract (cliquez dessus pour le déplier en entier, recliquez
pour le replier). *Inclure* ou *Exclure* enregistre la décision finale.

Mauvais bouton ? Un bandeau apparaît au-dessus de la liste juste après chaque
résolution, avec **Annuler la résolution** ; le même bouton figure sur chaque
carte de la vue *Résolus*. Annuler remet le conflit dans *À résoudre*, sans
toucher aux votes. Qui peut résoudre peut annuler (les reviewers en mode
consensus, les arbitres en mode arbitre). Une limite : une inclusion
sur titre/résumé ne peut plus être annulée une fois que la référence a reçu
des votes sur texte intégral.

## Le tableau de bord

- **Par relecteur** — l'avancement de chacun, compté sur ce qu'il a
  réellement à lire. Si le triage IA des titres a été utilisé, les titres
  qu'il a exclus sont dessinés en hachuré et retirés du total :
  `120/400 · 600 via triage IA` signifie 400 références à trier à la main,
  120 faites, 600 écartées par le triage.
- **Matrice croisée des votes** — à deux relecteurs, un tableau avec un nom
  sur chaque axe : une case compte les articles pour lesquels le relecteur en
  ligne et le relecteur en colonne ont voté ainsi, la diagonale étant les
  accords. À trois relecteurs ou plus, il y a un tableau de ce type par paire
  de relecteurs, chacun avec son κ de Cohen : on voit *qui* est en désaccord
  avec *qui* (le κ affiché en tête reste le κ de Fleiss sur toute l'équipe).
- **κ sur titre/résumé : « maybe » compte comme « include »** — les deux
  votes envoient la référence vers le texte intégral, donc le κ et l'accord
  brut mesurent la décision binaire *passe à la suite / exclue* : un
  relecteur qui vote *maybe* et l'autre *include*, c'est un accord. La
  matrice montre toujours les trois votes séparément, et un *maybe* ouvre
  toujours un conflit à résoudre — seule la statistique change. Sur texte
  intégral, les trois votes restent distincts. La checklist de reporting et
  le paragraphe Méthodes généré mentionnent ce regroupement.

## Screening au clavier

L'écran de screening est pensé pour la vitesse : les raccourcis clavier
(include/exclude/maybe, suivant/précédent) sont affichés sur la page. Ce
sont des lettres seules (Y, N, M, S, P), qui peuvent gêner la saisie vocale
ou certaines technologies d'assistance : le menu **?** de l'en-tête a un
interrupteur *Raccourcis à une touche* pour les désactiver (Échap, Entrée et
Retour arrière continuent de fonctionner). Les **highlights** configurables
(paramètres du projet) colorent en vert les termes liés à l'inclusion et en
rouge ceux liés à l'exclusion dans les titres et résumés.

## Vue un par un ou liste, et recherche par mots-clés

L'onglet de screening a deux présentations, commutables en haut : **un par
un** (le défaut — un article, gros boutons, raccourcis clavier) et
**liste** (on fait défiler sa file et on vote directement sur chaque
carte). Taper dans le **champ de recherche** ouvre toujours la liste,
filtrée sur les papiers correspondant à vos mots-clés (titre, abstract,
auteurs, revue — accents ignorés, termes combinés en ET, occurrences
surlignées). En recherche, la liste couvre tout ce qui vous est assigné, y
compris les papiers déjà votés — revoter remplace simplement votre vote
tant que la référence n'est pas close.

Dans la liste, une carte reste en place après votre vote, avec un bouton
**↶ Annuler** : il retire le vote (l'article revient dans votre file) ou
rétablit le vote qu'il remplaçait. L'annulation fonctionne même si votre
vote a clos la référence ou ouvert un conflit — le conflit est alors
retiré — tant que ce conflit n'a pas été résolu. Chaque carte porte aussi
ses **tags** (*+ Tag*), comme dans la vue un par un.

## Lire un abstract dans votre langue

Si un fournisseur d'IA est configuré, **Traduire en français / anglais**, sous
un article, traduit son titre et son abstract dans la langue de votre
interface. Cochez **Traduire automatiquement** pour que ce soit fait tout seul
pour chaque article que vous ouvrez et qui n'est pas déjà dans votre langue.
La vue liste ne traduit jamais d'elle-même : utilisez le lien sous une carte
quand vous voulez une traduction. En vue un par un, les trois
articles suivants de votre file sont aussi traduits pendant que vous lisez
l'article courant : le texte est en général prêt quand vous y arrivez. Le même
lien est disponible
de chaque côté d'une paire dans le **dédoublonnage**.

Une traduction est une aide à la lecture, jamais la source : elle est marquée
*Traduction IA* avec le modèle qui l'a produite, **Afficher l'original** est à
un clic, et le bouton *Modifier le résumé* sous le texte modifie toujours
l'abstract d'origine. Le
surlignage des mots-clés s'applique au texte affiché : les termes de votre
équation en anglais ne s'allumeront donc pas dans une traduction française. En
cas de doute sur un critère — un nombre, une population, un design — vérifiez
l'original avant de voter.

Chaque texte est traduit une seule fois et partagé avec toute l'équipe (il
voyage avec les snapshots) : personne ne paie deux fois ; modifier l'abstract
supprime sa traduction. Un abstract déjà dans votre langue ne coûte aucun appel
à l'IA. La consigne donnée au modèle est modifiable dans *Réglages du projet →
Prompts IA*, et la traduction apparaît dans le journal d'usage de l'IA et dans
la déclaration, comme toute autre fonctionnalité IA.

## Notes et tags

Chaque référence peut porter des notes libres (visibles par toute l'équipe
sur la page *Screening notes* — une justification de vote seulement une
fois la référence complète, pour que l'aveugle tienne là aussi) et des tags
colorés pour organiser les articles d'intérêt.

## Screening du texte intégral

Le screening FT fonctionne pareil, mais chaque exclusion exige un **motif
d'exclusion** (choisi parmi les critères du protocole). Ces motifs
apparaissent tels quels dans le diagramme PRISMA : restez cohérents.

Pas prêt à trancher — PDF manquant, tronqué, ou mauvais article ? Appuyez
sur **S** (*Passer — décider plus tard*) : l'article reste dans votre file,
repart à la fin et revient une fois tout le reste voté. Vous pouvez aussi
déposer ou remplacer le PDF directement depuis cet écran (voir *Full
text*), et ne recourir au motif « texte intégral introuvable » que s'il est
vraiment impossible à obtenir.

## Suggestions IA

Si un fournisseur IA est configuré, l'assistant peut pré-trier les
références ou suggérer des votes. Les suggestions IA sont toujours
affichées comme telles (marquées *AI*) et ne comptent **jamais** comme un
vote humain — un reviewer confirme ou corrige toujours.

Un PDF stocké de **plus de 45 pages** n'est jamais envoyé à l'IA (suggestion
sur texte intégral, préremplissage de l'extraction, évaluation critique) : à
cette longueur, le fichier est un livre, une thèse ou un volume d'actes
entier, dont le modèle ne verrait que les premières pages. Le bouton
l'indique ; évaluez l'article à la main, ou remplacez le fichier par
l'article lui-même.

### Voir la suggestion seulement après son vote

Une suggestion lue avant de décider tend à ancrer la décision. Les
paramètres du screening proposent **Afficher la suggestion IA seulement
après le vote**, par itération et par étape. Quand l'option est active :

- la suggestion est retenue **par le serveur** tant que votre propre vote sur
  cette référence n'existe pas — la même règle que l'aveugle entre reviewers,
  donc aucun écran ne peut la montrer trop tôt ;
- une fois votre vote enregistré, une courte carte compare votre décision à
  ce que l'IA suggérait, puis la file avance (*Entrée* ou *Suivant*) ;
- le bouton *Suggestion IA* à la demande et *Régénérer* n'apparaissent que sur
  les références que vous avez déjà votées (votre historique) ;
- une suggestion **déjà calculée** — par votre propre lot ou celui d'un
  co-reviewer — peut tout de même être consultée avant de voter, par le
  bouton explicite **Voir la suggestion IA avant de voter**. Ce choix est
  enregistré : le journal d'usage de l'IA et la déclaration indiquent combien
  de votes ont suivi une révélation anticipée, pour distinguer les votes à
  l'aveugle des votes informés.

Au texte intégral, le même réglage existe ; là, les raisons d'exclusion de
l'IA ne sont jamais recopiées d'elles-mêmes dans votre formulaire —
**Reprendre les raisons d'exclusion de l'IA** le fait à la demande, et vous
choisissez toujours la raison principale.

Un admin peut changer le réglage pendant l'itération. Les itérations de
snowballing l'héritent de l'itération précédente.

### Échantillon de contrôle du triage IA des titres

Le triage par titres exclut en masse ce que l'IA juge hors sujet avec
confiance, après validation de la liste par un humain. Pour confronter cette
confiance au jugement des relecteurs, le paramétrage du tri propose un
**Échantillon de contrôle** à côté du mode de triage (10 % par défaut,
1–50 %, modifiable pendant l'itération). Activé, cette part de chaque liste
validée est tirée au hasard et **n'est pas** exclue : ces titres restent dans
la file normale sans aucune marque, et les relecteurs les trient comme
n'importe quelle référence. Un second passage du triage ne les propose plus.

Le tableau de bord affiche alors une carte **Échantillon de contrôle du
triage IA** : combien de contrôles sont encore dans la file, combien les
relecteurs ont exclus à la main (le triage est confirmé) et combien ils ont
conservés — une inclusion, un *peut-être* ou un conflit non résolu comptent
comme une contradiction. Les contrôles en attente sont seulement comptés,
jamais listés, pour que personne ne puisse les reconnaître pendant le tri ;
ceux qui sont tranchés apparaissent avec la confiance et la raison de l'IA à
côté de la décision des relecteurs. Si plus d'un dixième des contrôles
tranchés contredisent le triage, la carte le signale : abaissez le seuil de
confiance ou relisez les listes validées avant de vous fier aux exclusions
automatiques. La carte est réservée aux admins en mode admin ; en mode
relecteurs, chacun voit les contrôles tirés de ses propres listes.
