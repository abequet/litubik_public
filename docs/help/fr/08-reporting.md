# Reporting : section Méthodologie et déclaration d'usage de l'IA

La dernière étape du pipeline produit deux textes pour votre manuscrit,
rédigés à partir de ce que l'application a enregistré pendant le travail — pas
de ce dont on se souvient. Ce sont des brouillons : vous les modifiez, et
c'est vous qui les signez.

## Section Méthodologie

*Reporting → Section Méthodologie* rédige les paragraphes de méthodologie de
votre article : protocole et critères d'éligibilité, sources d'information et
équation de recherche gelée, règle de dédoublonnage, nombre de reviewers,
allocation et règle de résolution des conflits, accord inter-juges réellement
obtenu, motifs d'exclusion, récupération des full texts, instrument
d'évaluation, procédure d'extraction, itérations de snowballing et — pour
une revue vivante — les dates et la cadence des passes de mise à jour.

Chaque chiffre vient de la piste d'audit du projet (l'encadré au-dessus du
bouton montre les faits principaux, pour vérification avant génération).
L'IA rédige autour de ces faits ; elle ne peut pas inventer un seuil ou un
nombre de reviewers, puisqu'on ne lui donne que ce que le pipeline a
enregistré. Le texte généré mentionne LitUbik et sa version comme logiciel
dans lequel la revue a été conduite.

### Ce que contient le brouillon

Il suit la structure PRISMA 2020 d'une section Méthodologie de revue : design
de l'étude et enregistrement · critères d'éligibilité (table Critère /
Description) · sources d'information et stratégie de recherche (concepts ×
termes, et **chaque équation reproduite verbatim telle qu'elle a été lancée**,
y compris les équations éditées à la main, avec son nombre de résultats) ·
sélection des études, une sous-section par phase sur le même patron —
screenés, inclus, exclus, conflits et leur résolution, et chaque κ avec son
interprétation Landis & Koch · récupération des full texts et motifs
d'exclusion avec leurs effectifs · collecte des données · évaluation critique,
en nommant l'instrument réellement employé et en précisant si deux évaluateurs
ont travaillé indépendamment · méthode de synthèse. Chaque itération de snowballing reçoit le même
traitement, et le corpus final est ventilé entre la recherche initiale et
chaque itération.

### L'enregistrement est un réglage, pas une devinette

L'item 24a de PRISMA demande le registre et le numéro d'enregistrement, **ou**
une déclaration explicite que la revue n'a pas été enregistrée. Ce sont deux
réponses différentes, et le silence en est une troisième. *Paramètres du
projet → General* porte les trois : choisissez votre registre (PROSPERO, OSF
Registries, INPLASY…) et donnez le numéro, ou répondez « Non enregistrée ».

Laissé sans réponse, le brouillon Methods laisse un trou visible. Répondu
« Non enregistrée », il l'écrit franchement, comme la limite que c'est. Ce que
le brouillon ne fera jamais, c'est transformer votre silence en affirmation
que la revue n'a pas été enregistrée — c'est à vous de le dire.

Importer un protocole depuis un lien OSF pré-remplit le registre et l'URL,
mais seulement si vous n'aviez pas encore répondu. Quand le lien est un
*enregistrement* OSF, son identifiant (le GUID à cinq caractères) et sa date
d'enregistrement sont remplis aussi ; un *projet* OSF n'est pas une
préregistration, le numéro reste alors à saisir.

### Les manques sont signalés, pas comblés

Certaines choses qu'exige une section Méthodologie ne sont pas dans
l'application : la raison d'une fenêtre temporelle ou d'un choix de langues,
la justification de la méthode de synthèse, les numéros de tables et de
suppléments. Plutôt que de les inventer, le brouillon écrit
**[À COMPLÉTER : …]** en gras, à l'endroit voulu — cherchez-le avant de
soumettre.

Si les chiffres enregistrés ne s'additionnent pas à une phase, le brouillon les
rapporte tels quels et signale l'écart, au lieu d'ajuster discrètement un
nombre.

Choisissez **l'anglais ou le français** avant de générer — utile quand le
protocole est dans une langue et la revue visée dans l'autre. La version
française emploie la terminologie méthodologique française établie plutôt que
des traductions littérales.

## Déclaration d'usage de l'IA

*Reporting → Déclaration d'usage de l'IA* produit l'énoncé que les revues
demandent de plus en plus, portant sur **l'usage de l'IA pour conduire la
revue** : recherche, sélection, évaluation, extraction, synthèse. Elle ne dit
délibérément rien de la rédaction de votre manuscrit, qui ne se fait pas dans
LitUbik — l'énoncé le précise, pour que le lecteur sache ce qu'il couvre et ce
qu'il ne couvre pas. Si vous avez aussi utilisé l'IA pour écrire l'article,
déclarez-le à part.

### Elle est rédigée depuis un journal, pas de mémoire

Chaque appel à l'IA effectué par LitUbik est enregistré : quelle aide, quel
modèle, combien d'appels, par qui, quels jours, à quel coût. La page affiche ce
journal, ainsi que ce que les reviewers en ont fait — combien de suggestions
de screening concordaient avec la décision humaine finale et combien ont été
infirmées, combien de cellules préremplies ont été validées, combien de
propositions de triage un reviewer a confirmées.

C'est important parce que reconstituer après coup l'usage de l'IA n'est pas
fiable : on attribue mal et on sous-déclare ce qu'un outil a apporté. Ici,
vous corrigez un relevé au lieu d'en reconstruire un.

> Si le projet a utilisé l'IA *avant* cette version de LitUbik, la page vous
> avertit : le journal commence plus tard que l'usage réel, et il faut
> corriger les niveaux à la main avant de générer.

### Le formulaire avant le bouton

Vous relisez un court formulaire : niveau d'assistance de l'IA (aucun /
faible / moyen / élevé) pour chaque activité de la revue, outils et versions,
éléments transmis aux fournisseurs, garde-fous configurés côté fournisseur,
validation humaine, périmètre d'autorat. Les niveaux sont préremplis depuis le
journal ; corrigez ce qui ne correspond pas à votre façon de travailler, puis
générez.

L'énoncé généré est modifiable, et votre version modifiée est conservée en cas
de régénération.

La structure de ce formulaire suit **DAISY**, l'outil de déclaration évalué
dans :

> Ahmetoglu, Y., Constantinides, M., & Cox, A. (2026). AI Disclosure with
> DAISY. *Proceedings of the 5th Annual Symposium on Human-Computer
> Interaction for Work (CHIWORK ’26)*, Linz, Autriche. ACM.
> <https://doi.org/10.1145/3808045.3808056>

Leur étude montre qu'une déclaration structurée produit des énoncés plus
complets sans mettre les auteurs moins à l'aise, et que les auteurs préfèrent
un énoncé généré qu'ils peuvent modifier à un énoncé qu'ils doivent écrire ou
accepter tel quel — d'où le formulaire d'abord, et un texte qui reste le
vôtre.

## Amendements aux méthodes prévues

Une revue a le droit de changer d'avis. Ce qu'il faut au lecteur — et ce que
vérifie le triage éditorial, pour toute revue qui référence un protocole —
c'est le changement *et sa raison*. L'item 24c de PRISMA le demande ; l'item 1b
de SWiM le demande pour les groupes de synthèse en particulier.

*Reporting → Amendements* y répond par deux bouts.

**Ce que le pipeline a remarqué.** LitUbik a horodaté chaque étape au fil de
l'eau : certains changements sont donc visibles dans ses propres tables —
critères d'éligibilité reformulés une fois le screening commencé, version de
protocole validée après l'arrivée des notices, équation de recherche gelée
après les imports, tour de screening relancé sur des votes existants. Chacun
apparaît sous forme de carte.

Une carte est une **question, pas un verdict**. Rien n'est promu en écart
automatiquement, parce que la raison est la seule chose que vous êtes seul à
détenir. Répondez — « c'était un changement, voici pourquoi » — ou écartez :
« nous avons regardé, c'était une correction de coquille ». Un rejet est
consigné plutôt qu'oublié, pour que personne ne rejoue le même signal dans
trois mois.

**Ce qu'aucune table ne pouvait voir.** Un regroupement décidé en réunion, une
méthode de synthèse abandonnée, une base ajoutée en cours de recherche :
déclarez-les vous-même, avec l'étape à laquelle ils appartiennent.

Seul ce que vous déclarez atteint le brouillon Methods, qui se termine par une
sous-section **Amendements aux méthodes prévues** listant chacun avec sa date
et sa raison. Un signal sans réponse reste une question pour vous et ne devient
jamais une affirmation sur la revue.

Notez ce qui n'est délibérément *pas* détecté : les colonnes d'extraction
ajoutées en cours de route. LitUbik n'horodate pas les colonnes ; le seul
signal disponible se déclencherait donc pour tout projet ayant commencé une
extraction, qu'il y ait eu changement ou non — et un registre qui crie au loup
est un registre que personne ne lit. Celui-là se déclare à la main.

## Checklists de rapport

*Reporting → Checklists* remplit la checklist **PRISMA 2020** — le fichier de
42 lignes que les revues demandent en supplémentaire — avec ce que ce projet a
réellement consigné.

Chaque item tombe dans l'un de quatre états :

- **Consigné par l'application** — le pipeline l'a vu se produire, et le fait
  est affiché. L'item 8, par exemple, restitue le nombre de relecteurs, la
  règle d'allocation, le κ obtenu et le mode de résolution des conflits.
- **À vous d'écrire** — hors du logiciel par nature : financement, conflits
  d'intérêts, discussion. Ajoutez votre note et la page.
- **Pas fait** — l'application sait que l'étape n'a jamais tourné. C'est cet
  état qui rend le fichier utile : une case vide se lit comme un oubli, « pas
  fait » se lit comme un constat, et mieux vaut le découvrir ici que dans un
  rapport de relecture.
- **Sans objet** — vous seul pouvez le dire, c'est donc le seul statut que vous
  posez à la main.

La checklist **SWiM** apparaît à côté dès qu'un de vos résultats déclare une
méthode de synthèse autre que la méta-analyse — c'est le périmètre que SWiM se
donne, et la montrer à une revue qu'elle ne couvre pas vous apprendrait à
ignorer les checklists.

Exportez l'une ou l'autre en CSV, avec vos renvois de page en dernière colonne.

### Avant de soumettre

Le même onglet liste les problèmes que cherche le triage éditorial, quand ils
sont présents : aucun instrument d'évaluation appliqué, aucun cadre de
certitude, un évaluateur unique, une équation jamais gelée, une recherche
jamais confrontée à des références connues, des changements repérés par le
pipeline que personne n'a expliqués.

Ce qu'il ne fait délibérément **pas**, c'est vous noter. Les outils de triage
demandent à un éditeur de noter six domaines de 1 à 5 ; reproduire cela ici
transformerait un instrument d'éditeur en instrument d'auteur, et s'attribuer
un 4 est exactement la conformité auto-déclarée que ces outils traquent. Une
note est un jugement. Une évaluation manquante est un fait.

## Qui peut les générer

N'importe quel membre du projet, comme pour les autres boutons IA à la
demande : l'auteur et le coût sont enregistrés. Sur une copie satellite la
page est en lecture seule — le reporting se publie depuis l'instance
coordinatrice.
