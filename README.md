# Planning AI

Ce projet se penche sur la création et la résolution de perturbations pour un emploi du temps. Nous avons créé un générateur, ainsi qu'un gestionnaire de perturbations et enfin une pipeline de génération de données (emploi du temps,perturbations,emploi du temps réparé).

## Installation
- Cloner le repo
- installer OR-Tools (pip install ortools)

## Utilisation
Ce repo contient 3 modules : un de génération (Generator), un gestionnaire de perturbations (Perturbations) et une pipeline de génération de données.
### Génération
Ce générateur permet d'effectuer différents types d'action : une génération semestrielle (via un fichier dans Data/ de format instance_petite_semestre.json), appliquer un scénario à un emploi du temps déjà dans edt/ (extrêmement rudimentaire), afficher les résultats d'une génération ou comparer deux générations, lancer une génération hebdomadaire (via un fichier dans Data/ de format instance_petite.json), lancer des générations à partir d'un même fichier mais avec toutes les configurations de contraintes souples possibles et enfin, faire une étude de convergence. Il est important de noter que ce générateur fonctionne en slots abstraits. De plus, la configuration (activation et poids des contraintes souples) se fait dans le main.
Pour la génération semestrielle:
- Dans Generator/, lancer python ./main.py
- Choisir la résolution semestrielle
- Donner le chemin vers le fichier d'instance (Data/nom_fichier.json)
- Choisir le nombre de semaines du semestre (N)
- Choisir un temps de recherche CP-SAT pour la répartition des sessions par semaine
- Choisir un temps de recherche CP-SAT pour le placement des sessions dans chacune des semaines (N * timeout donné)
- Choisir le nombre de threads CPU mis à disposition pour CP-SAT
- Choisir le nombre de sessions maximales par groupe par semaine ; auto garantit que le groupe le plus chargé fonctionne, donner une valeur plus faible que ce seuil risque de finir avec plusieurs sessions non placées
- Choisir les poids pour les contraintes souples du solveur de répartition : préférences temporelles, équilibre des semaines, respect de l'ordre des sessions donné par les professeurs

Le générateur donne un temps de fin de génération estimé si tous les timeout sont atteints. Les informations de génération sont affichées dans le terminal (ou console). Pour l'étape 1 : le statut de la répartition des sessions, ainsi que ladite répartition pour chacune des semaines. Pour l'étape 2 : pour chacune des semaines du semestre, le début de la résolution est affiché entre crochets et nous avons aussi le statut de la résolution, ainsi que le score de celle-ci. Un résumé donnant tous les statuts hebdomadaires, ainsi qu'une liste des éventuelles sessions non placées et la durée de la résolution complète en secondes.
Il faut ensuite donner le nom du fichier json qui contiendra l'emploi du temps généré (SANS EXTENSION), et il est possible de générer un fichier HTML pour l'emploi du temps.

### Perturbation
Le gestionnaire de perturbations fonctionne à partir d'un emploi du temps au format csv (format de edt_semestre.csv), on peut choisir le csv dans le main, lors de l'extraction. Il a aussi besoin d'un fichier appelé specs.json, qui comprend toutes les informations importantes de l'université (on peut le changer dans le main, lors de l'extraction). Il fonctionne en heures et minutes et non en slots abstraits comme le générateur. Nous travaillons avec des jours et semaines 0-indexés ainsi que des jours absolus (0 est S1 Lun, 5 est S2 Lun, 10 est S3 Lun, etc.).
Pour perturber et résoudre :
- Dans Perturbations/, lancer python ./main.py
- Choisir un jour (absolu) que l'on considèrera comme "aujourd'hui" (ce jour marque la fin de la zone d'emploi du temps où la résolution ne s'attarde pas car ces sessions ont déjà eu lieu)
- Saisir les perturbations (type de perturbation, suivi des informations requises)
- Saisir 0 pour lancer la résolution des perturbations saisies
- Choisir le type de résolution (1 pour cascade, 2 pour une passe) ; pour un meilleur résultat, nous conseillons 2 (une passe)

Un résumé de la résolution s'affiche dans le terminal (ou la console). En cascade, c'est résumé de chaque résolution de perturbation, tandis qu'en une passe, c'est le résumé de chaque phase de résolution (statut ou N/A, informations de résolution). En une passe, un résumé des statuts est proposé après les informations des phases. Un tableau de comparaison de score avant/après perturbations et le delta est disponible dans le résumé, permettant de voir en un coup d'oeil l'impact des perturbations saisies sur l'emploi du temps. De plus, un bilan des perturbations est disponible et permet de savoir quelles sessions ont été déplacées, ajoutées, supprimées ou n'ont pas pu être replacées dans l'emploi du temps. L'emploi du temps réparé (après résolution) est enregistré en json dans un dossier créé spécifiquement pour la résolution dans edt/ et l'utilisateur peut choisir de créer un fichier HTML pour cet emploi du temps. S'il choisit de le générer, un fichier HTML qui représente les heures de cours données par les professeurs est aussi créé.

### Pipeline
Nous avons créé une pipeline de création de données qui permet de générer et de perturber un emploi du temps. Elle a besoin d'un fichier d'instance (format Generator/Data/data_instance.json) et d'un fichier d'informations de l'université (format Perturbations/Data/specs.json).
- Dans PROJET/ lancer python ./pipeline.py
- Donner le chemin vers le fichier qui vient d'être créé (il est Generator-compatible et son chemin est écrit juste au-dessus de la ligne actuelle du prompt, donner le chemin à partir de PROJET/)
- Saisir les informations nécessaires à la génération (cf. ## Génération)
- Donner les noms des fichiers d'instance, de specs et de l'emploi du temps généré, ainsi que le nom de l'emploi du temps transformé depuis slots abstraits en heures minutes
- Saisir les informations nécessaires à la perturbation (cf. ## Perturbation)

Le fichier d'emploi du temps en heures et minutes (dans Perturbations/Data), la liste des perturbations (dans Perturbations/Logs/log_perturbations.jsonl) et l'emploi du temps réparé (dans Perturbations/edt) peuvent servir de triplets d'entraînement pour un MLP ou un JEPA visant à proposer des mouvements pour la résolution de perturbations.

Il est possible d'automatiser toutes les saisies via le fichier demo.py, mais il est conseillé de tester d'abord avec pipeline.py, puis de remplir demo.py comme souhaité.


## Notes et limites
- Génération
    - Le générateur ne fonctionne pas avec des demi groupes ou des cours qui dure plusieurs slots (plusieurs créneaux) de l'emploi du temps
- Perturbations
    - ATTENTION : dans la saisie des perturbations, il faut absolument mettre les heures avec un "h" et non un "H"!
    - le score de same_day est toujours à 0.0 car c'est un scorer interne...
- Pipeline
    - Lors de la génération ou de la perturbation, il est possible qu'une ou plusieurs sessions n'aient pas pu être placées ou replacées dans l'emploi du temps. Il faut faire en sorte d'écarter ces données là si l'on souhaite générer un dataset de données correct.
