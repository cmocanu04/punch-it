
---

## Fichiers Python

### 1. `serveur_principal.py`

<u> Résumé</u> :  gère la **réception en temps réel des données du gant de boxe connecté via socket TCP, l'accumulation de ces données dans un buffer avec gestion du chevauchement, le déclenchement périodique de l'analyse des coups, leur classification et évaluation, et leur insertion dans la base de données.** Il s'occupe également de **l'identification ou la création d'utilisateurs, la gestion des sessions d'entraînement, et l'intégration du module de coaching basé sur des règles d'expert.** Enfin, il assure la **création des fichiers CSV avec des données brutes** et la gestion de l'arrêt du serveur.

#### Fonctions et logiques clés

* **Gestion du buffer de données avec chevauchement et déduplication**
    * Les données reçues sont stockées dans `DATA_BUFFER_LIST`.
    * Un système de fenêtre glissante (`overlap`) permet d'analyser des segments de données avec recouvrement, afin de ne pas manquer de coups aux frontières des fenêtres.
    * La déduplication est effectuée via `RECENTLY_INSERTED_PUNCHES_SEQN` (deque) pour éviter d'insérer plusieurs fois le même coup détecté dans des fenêtres successives.

* **`process_data_buffer(data_window_list)`**
    * Traite une fenêtre de données, applique le modèle KNN pour détecter et classifier les coups, effectue la déduplication, insère les coups en base de données, calcule le score de réussite, affiche les résultats.

* **`handle_client(conn, addr)`**
    * Gère la connexion d'un client (Arduino), la réception des données, l'écriture dans le fichier CSV brut, l'alimentation du buffer, et le déclenchement de l'analyse.

* **`start_server()`**
    * <u>Point d'entrée principal </u>: initialise la connexion à la base de données, l'identification de l'utilisateur, la session, le chargement des règles d'expert, puis lance la boucle d'acceptation des clients et la gestion de l'arrêt propre du serveur.
<br><br>

* **Coaching basé sur les règles d'expert**
    * La fonction `generer_et_afficher_conseils(details_coup)` compare les caractéristiques d'un coup aux plages idéales définies dans un fichier JSON, et affiche des conseils personnalisés.

#### Dépendances externes

* **`socket`, `threading`**: Communication réseau et gestion multi-clients.
* **`csv`, `pandas`, `numpy`**: Manipulation et stockage des données brutes.
* **`colorama`**: Affichage coloré dans la console pour une meilleure lisibilité.
* **`msvcrt`**: Détection de touches clavier sous Windows (arrêt manuel du serveur).
* **`json`**: Chargement des règles d'expert depuis un fichier.
* **`os`, `sys`, `signal`, `time`, `datetime`**: Utilitaires système, gestion des fichiers, signaux d'arrêt, timestamps.
* **Modules personnalisés**: `db_utils`, `analyse_coups`, `arduino_secrets_server` pour la base de données, l'analyse ML et les informations sensibles.

### 2. `analyse_coups.py`


<u> Résumé:</u> Engendre toute **la logique d'analyse des données de capteurs pour la détection, la segmentation, l'extraction de caractéristiques et la classification des coups de boxe.** Il implémente **l'algorithme de segmentation par énergie**, **l'extraction de features physiques, la gestion et la persistance du modèle KNN (ainsi que du scaler et de l'imputer)**.

#### Fonctions et logiques clés

* **Algorithme de segmentation des coups par énergie**
    * `segment_coups_par_energie` : Détecte les segments actifs (coups) dans le signal d'accélération, en utilisant une enveloppe d'énergie et des seuils, avec gestion de la fusion de segments proches.

* **Extraction des caractéristiques (features)**
    * `extract_features_from_segment` : Calcule les features physiques (min/max, amplitude, ordre des extrêmes, force, flexion) sur chaque segment détecté.

* **Gestion et persistance du modèle KNN**
    * `charger_modele_knn_entraine` : Charge ces objets depuis le disque pour une utilisation en production.

* **Analyse complète d'un buffer**
    * `analyse_buffer_avec_knn` : Pipeline complet qui lisse les données, segmente, extrait les features, applique le KNN, et retourne les prédictions détaillées.

* **Prédiction d'un coup**
    * `predict_coup_knn` : Applique le pipeline de preprocessing et le modèle KNN à un ensemble de features pour prédire le type de coup et la confiance.

#### Dépendances externes

* **`pandas`, `numpy`**: Manipulation de données, calculs numériques.
* **`scikit-learn` (`KNeighborsClassifier`, `StandardScaler`, `SimpleImputer`)**: Machine learning (KNN, normalisation, gestion des valeurs manquantes).
* **`joblib`**: Sauvegarde et chargement efficaces des objets ML (modèle, scaler, imputer).
* **`os`**: Gestion des chemins de fichiers pour la persistance des modèles.

### 3. `db_utils.py`

<u> Résumé:</u>
Ce module centralise toutes les interactions avec la base de données MySQL. Il fournit des **fonctions pour ouvrir et fermer la connexion, créer des utilisateurs et des sessions, insérer les coups détectés avec leurs caractéristiques, et clôturer une session en calculant les statistiques finales (durée, force max, pourcentage de réussite).**

#### Fonctions et logiques clés

* **Connexion et gestion de la base de données**
    * `ouvrir_connexion_bd`, `fermer_connexion_bd` : Gèrent l'ouverture et la fermeture sécurisée de la connexion MySQL.

* **Gestion des utilisateurs**
    * `get_user_by_id` : Recherche un utilisateur par ID.
    * `create_new_user` : Crée un nouvel utilisateur avec auto-incrémentation de l'ID.

* **Gestion des sessions**
    * `creer_nouvelle_session` : Crée une nouvelle session d'entraînement pour un utilisateur.
    * `cloturer_session` : Met à jour la session avec la date de fin, la durée, la force maximale et le score de réussite.

* **Insertion des coups**
    * `inserer_coup_dans_bdd` : Insère un coup détecté avec toutes ses caractéristiques physiques et de classification.

#### Dépendances externes

* **`mysql-connector-python`**: Connexion et requêtes MySQL.
* **`numpy`**: Gestion des NaN et conversions pour l'insertion des features.
* **`datetime`**: Gestion des timestamps pour les sessions et les coups.
* **`arduino_secrets_server`**: Récupération sécurisée des identifiants de connexion à la base de données.

### 4. `arduino_secrets_server.py`

#### Résumé général du fichier
Ce fichier **contient les informations sensibles nécessaires à la connexion à la base de données MySQL (hôte, port, utilisateur, mot de passe, nom de la base).** Il est importé par les autres modules pour centraliser et sécuriser la gestion des secrets.

#### Fonctions et logiques clés

* **Aucune fonction spécifique**
    * Ce fichier ne contient que des variables globales (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DATABASE`) utilisées par `db_utils.py` pour établir la connexion à la base de données.

#### Dépendances externes

* **Aucune**
    * Ce fichier ne dépend d'aucune bibliothèque externe ; il ne fait que stocker des constantes.

---


## Fichiers Jupyter Notebook

### 1. `creation_ref_knn.ipynb` - Création du jeu de données de référence

<u> Résumé:</u>
Il charge une session d'enregistrement de données brutes (depuis un fichier CSV), applique des algorithmes de traitement du signal pour segmenter et isoler des coups potentiels, puis il guide l'utilisateur à travers un processus interactif pour étiqueter manuellement chaque coup détecté (direct, crochet, uppercut). Finalement, il extrait un ensemble de 11 caractéristiques numériques pour chaque coup labellisé et sauvegarde le tout dans un nouveau fichier CSV (`dataset_entrainement_knn.csv`), prêt pour l'entraînement.

#### Fonctions et logiques clés

* **Segmentation des coups par énergie (`segment_coups_par_energie`)** : C'est l'algorithme clé pour détecter automatiquement les coups. Il calcule d'abord la magnitude du vecteur d'accélération (la force globale ressentie par le capteur) puis son enveloppe d'énergie (une moyenne mobile du signal au carré). En appliquant un seuil sur cette énergie, le script identifie les segments de haute activité. Ces segments sont ensuite affinés en les fusionnant s'ils sont très proches et en ignorant ceux qui sont trop courts, ce qui permet d'isoler de manière robuste chaque coup individuel.

* **Extraction des caractéristiques (`extract_features_from_segment`)** : Une fois qu'un segment de coup est identifié, cette fonction le transforme en un vecteur de 11 caractéristiques numériques. Elle analyse les signaux lissés (AccX, AccZ, Roll, Pitch) à l'intérieur du segment pour en extraire des valeurs statistiques clés : les valeurs minimales et maximales, l'amplitude (différence entre max et min), et l'ordre d'apparition de ces extrêmes (par ex. pour AccX, le retrait du poing a-t-il eu lieu avant ou après l'impact ?). Ces caractéristiques sont l'empreinte digitale de chaque coup.

* **Labellisation interactive** : La boucle `for` parcourt `detected_segments_indices`, elle génère un graphique et demande à l'utilisateur de fournir une étiquette via la console (`input()`). 

#### Dépendances externes (librairies)

* **`pandas` & `numpy`**: Utilisés pour la manipulation des données (DataFrames) et les calculs numériques (moyenne, écart-type, etc.).
* **`matplotlib.pyplot`**: Essentielle pour la visualisation. Elle permet d'afficher les graphiques de chaque segment de coup pour aider l'utilisateur à prendre une décision de labellisation.
* **`scipy.signal.find_peaks`**: Bien que la segmentation principale se fasse par énergie, cette fonction est utilisée dans une fonction héritée (`identify_coup_segments`) pour détecter les pics spécifiques dans le signal, ce qui constitue une méthode alternative ou complémentaire.
* **`sklearn`**: Fournit les composants de base du machine learning (`KNeighborsClassifier`, `StandardScaler`, `SimpleImputer`) qui sont entraînés et sauvegardés dans le notebook `entrainement_knn_from_csv`.

### 2. `entrainement_knn_from_csv.ipynb` - Entraînement et sauvegarde du modèle

<u>Résumé:</u>Ce notebook a pour unique but d'entraîner le modèle de reconnaissance de coups. Il prend en entrée le fichier `dataset_entrainement_knn.csv` (créé par le script précédent), sépare les données en caractéristiques (`X`) et en étiquettes (`Y`), puis applique une chaîne de prétraitement standard en machine learning. Il entraîne ensuite un classifieur K-Nearest Neighbors (KNN) sur ces données. L'étape la plus critique est la sauvegarde du modèle entraîné ainsi que des objets de prétraitement (scaler et imputer) à l'aide de `joblib`.

#### Fonctions et logiques clés

* **Séparation des données** : Le code isole les 11 colonnes de caractéristiques dans un DataFrame `X_ref` et la colonne `Type_Coup` dans une série `y_ref`. C'est la préparation standard pour un algorithme d'apprentissage supervisé de `scikit-learn`.

* **Imputation (`SimpleImputer`)** : Avant toute chose, il configure un `SimpleImputer`. Cet objet apprend à remplacer les éventuelles valeurs manquantes (`NaN`) dans les données par la médiane des valeurs de chaque colonne. C'est une étape de robustesse essentielle pour éviter les erreurs si les données futures sont incomplètes.

* **Mise à l'échelle (`StandardScaler`)** : Le `StandardScaler` est entraîné pour centrer et réduire chaque caractéristique (moyenne de 0, écart-type de 1). Cette étape est cruciale pour les modèles basés sur la distance comme KNN, car elle empêche les caractéristiques avec de grandes échelles (comme la rotation) de dominer celles avec de plus petites échelles (comme l'accélération).

* **Persistance avec `joblib`** : La fonction `joblib.dump()` est utilisée pour sérialiser et sauvegarder sur le disque les trois objets entraînés : le modèle KNN, le scaler et l'imputer. Cette persistance est fondamentale, car elle permet au serveur principal de simplement charger ces fichiers `.joblib` pour faire des prédictions sans avoir à recharger et à retraiter l'ensemble du jeu de données d'entraînement à chaque fois.

#### Dépendances externes (librairies)

* **`pandas`**: Utilisé pour charger le fichier `dataset_entrainement_knn.csv` dans un DataFrame.
* **`joblib`**: La bibliothèque clé pour la persistance du modèle. Elle est optimisée pour sauvegarder et charger des objets Python contenant de grands tableaux NumPy (ce qui est le cas des modèles `scikit-learn`).
* **`sklearn`**: Fournit tous les outils de machine learning : `SimpleImputer` (gestion des NaN), `StandardScaler` (mise à l'échelle) et `KNeighborsClassifier` (l'algorithme de classification).

### 3. `fusion_csv.ipynb` - Fusion de jeux de données

<u>Résumé:</u> Son rôle est de combiner plusieurs fichiers CSV, qui représentent différentes sessions d'entraînement ou différents boxeurs, en un seul et unique fichier `dataset_entrainement_toutes_sessions.csv`. L'objectif est de créer un jeu de données plus grand, plus varié et plus généralisable. 

#### Fonctions et logiques clés

* **Définition des fichiers d'entrée** : Une liste Python (`fichiers_entree`) contient les chemins vers tous les fichiers CSV à fusionner. Cette approche rend le script facilement adaptable en modifiant simplement cette liste.

* **Lecture et stockage itératifs** : Le script parcourt la liste des fichiers. Pour chaque fichier, il utilise `pd.read_csv()` pour le charger dans un DataFrame pandas, puis ajoute ce DataFrame à une liste (`liste_dataframes`).

* **Concaténation (`pd.concat`)** : C'est l'opération centrale du script. La fonction `pd.concat` prend la liste de tous les DataFrames et les empile verticalement pour n'en former qu'un seul. L'option `ignore_index=True` est importante pour garantir que le DataFrame final ait un index continu de 0 à N-1.

* **Sauvegarde du résultat (`to_csv`)** : Le DataFrame fusionné est sauvegardé dans un nouveau fichier CSV, créant ainsi le jeu de données consolidé prêt à être utilisé pour l'entraînement.

#### Dépendances externes (librairies)

* **`pandas`**: La seule dépendance majeure. Elle est utilisée pour toutes les opérations de lecture, de manipulation (concaténation) et d'écriture des fichiers CSV.
* **`os`**: Utilisé pour la vérification de l'existence des fichiers (`os.path.exists`), ce qui rend le script plus robuste en évitant les erreurs si un fichier est manquant.

### 4. `generation_conseils.ipynb` - Génération de règles de coaching

<u>Résumé:</u> Il analyse un jeu de données venant du boxeur expert (fichier CSV) pour définir ce qu'est un coup "idéal". Pour chaque type de coup (direct, crochet, etc.) et pour chaque caractéristique, il calcule une fourchette de valeurs considérées comme correctes (basée sur la moyenne et l'écart-type). Ces règles sont ensuite stockées dans un fichier `regles_expert.json`. Ce fichier JSON devient la base de connaissances du coach virtuel, permettant à d'autres parties du système de comparer un coup donné aux standards de l'expert et de générer des conseils.

#### Fonctions et logiques clés

* **Calcul des intervalles (`calculate_correct_punch_intervals`)** : C'est le cœur de la génération de règles. La fonction regroupe les données de l'expert par type de coup. Pour chaque groupe, elle calcule la moyenne et l'écart-type de chaque caractéristique. La "fourchette idéale" est ensuite définie comme moyenne ± (1.5 * écart-type). Le dictionnaire résultant contient ces fourchettes pour chaque coup et chaque feature.

* **Sauvegarde des règles (`save_rules_to_json`)** : Après avoir calculé les intervalles, cette fonction utilise la bibliothèque `json` pour écrire le dictionnaire de règles dans un fichier. Le format JSON est idéal car il est à la fois lisible par l'homme et facilement interprétable par d'autres programmes Python.

#### Dépendances externes (librairies)

* **`pandas` & `numpy`**: Utilisés pour l'analyse statistique des données de l'expert (calcul des moyennes, écarts-types, etc.).
* **`json`**: Indispensable pour écrire le dictionnaire de règles dans un fichier JSON structuré.
* **`os`**: Potentiellement utilisé pour gérer les chemins de fichiers, bien que non visible dans le code principal de cette cellule.

### 5. `Shap.ipynb` - Interprétabilité du modèle avec SHAP

<u>Résumé: </u> Ce notebook est dédié à l'explicabilité du modèle . Son objectif est de comprendre quelles caractéristiques (features) ont le plus d'impact sur les décisions du modèle KNN. Pour ce faire, il utilise la bibliothèque `shap` pour calculer les valeurs de Shapley, qui quantifient la contribution de chaque feature à une prédiction donnée. Les visualisations, en particulier le Bar Plot, classent les caractéristiques par ordre d'importance globale, permettant de répondre directement à la question : "Quelle est la caractéristique la plus prépondérante pour distinguer les coups ?".


#### Fonctions et logiques clés

* **Fonction de prédiction wrapper (`predict_fn`)** : Le `KernelExplainer` de SHAP, nécessaire pour **les modèles non arborescents comme KNN**, ne peut pas utiliser directement un pipeline `scikit-learn`. Cette fonction "enveloppe" donc la chaîne de prétraitement (imputation, mise à l'échelle) et la prédiction du modèle en une seule fonction qui prend un tableau numpy et renvoie des probabilités, format requis par l'explainer.

* **Initialisation de l'explainer (`shap.KernelExplainer`)** : Cette ligne crée l'objet `explainer`. Il est crucial de lui fournir un `background_data` (un petit sous-ensemble représentatif des données d'entraînement) pour qu'il puisse simuler des "valeurs manquantes" et calculer l'impact de chaque feature.

* **Visualisation `shap.summary_plot` (Bar Plot)** : C'est le résultat le plus important. En utilisant `plot_type='bar'`, SHAP affiche un graphique à barres qui classe les caractéristiques par ordre d'importance globale (basée sur la valeur absolue moyenne des contributions de Shapley). La caractéristique en haut du graphique est celle qui, en moyenne, a le plus d'influence sur les prédictions du modèle pour toutes les classes confondues. C'est la réponse la plus directe à votre question.



#### Dépendances externes (librairies)

* **`joblib`**: Utilisé pour charger le modèle, le scaler et l'imputer pré-entraînés.
* **`pandas` & `numpy`**: Pour la gestion des données.
* **`shap`**: La bibliothèque centrale pour le calcul et la visualisation des valeurs de Shapley.
* **`matplotlib.pyplot`**: Utilisée par `shap` en arrière-plan pour générer et afficher les graphiques.

### 6. `visualisations_2D_tSNE.ipynb` - Visualisation des données en 2D

<u> Résumé:</u> C'est un outil d'exploration et de visualisation de données. Son rôle principal est de réduire la dimensionnalité de l'espace des caractéristiques (qui a 11 dimensions) à seulement 2 dimensions pour pouvoir le visualiser sur un graphique.

 Cela permet d'évaluer visuellement si les différents types de coups forment des groupes (clusters) distincts et séparables. Il utilise deux techniques populaires : la PCA (linéaire) et la t-SNE (non linéaire), et génère des nuages de points où chaque point est un coup, coloré par son type (prédit ou réel).

#### Fonctions et logiques clés

* **Chargement et Prétraitement** : Le script charge les données et applique le scaler et l'imputer sauvegardés. C'est une étape essentielle car les algorithmes de réduction de dimension sont, comme KNN, sensibles à l'échelle des caractéristiques.

* **Réduction par PCA (`PCA`)** : L'Analyse en Composantes Principales est une technique linéaire qui trouve les deux axes (les composantes principales) qui capturent le maximum de variance dans les données. Le graphique résultant est une "ombre" des données projetées sur ce plan optimal, préservant au mieux la structure globale. Le script affiche également le pourcentage de variance expliquée, qui indique la quantité d'information conservée.

* **Réduction par t-SNE (`TSNE`)** : t-Distributed Stochastic Neighbor Embedding est une technique non linéaire qui est particulièrement efficace pour visualiser la structure locale des données. Elle tend à créer des clusters plus distincts et visuellement séparés que la PCA, ce qui est très utile pour voir si les classes de coups sont naturellement regroupées.

* **Visualisation avec Ellipses (`plot_confidence_ellipse`)** : En plus du nuage de points, le script dessine des ellipses de confiance autour de chaque groupe de coups. Ces ellipses permettent de visualiser rapidement le "centre" (la moyenne) et la "dispersion" (l'écart-type) de chaque classe dans l'espace 2D, rendant les clusters encore plus faciles à interpréter.

#### Dépendances externes (librairies)

* **`pandas` & `numpy`**: Pour la manipulation et la préparation des données.
* **`matplotlib.pyplot` & `seaborn`**: Pour la création de graphiques esthétiques et informatifs (nuages de points et ellipses).
* **`sklearn`**: Fournit les algorithmes de réduction de dimension (`PCA`, `TSNE`) ainsi que le `StandardScaler` pour le prétraitement.
* **`joblib`**: Nécessaire pour charger les objets de prétraitement (imputer, scaler) et le modèle KNN dont les prédictions sont utilisées pour colorer les points.
* **`scipy`**: Utilisé via `chi2` pour calculer le facteur d'échelle des ellipses de confiance, bien que le code plus récent l'ait remplacé par une approche plus simple basée sur l'écart-type.







### 7. `matrice_confusion.ipynb` - Évaluation du modèle avec la Matrice de Confusion
<u>Résumé:</u>
Ce notebook évalue quantitativement la performance du modèle KNN. Pour ce faire, **il charge le modèle pré-entraîné**, lui soumet **un jeu de données de test** qu'il n'a jamais vu, et confronte les prédictions du modèle aux véritables étiquettes. Le résultat est une matrice de confusion.


#### Fonctions et logiques clés

* **Chargement du modèle et des données :** 
 Le script commence par charger les objets .joblib essentiels (le modèle KNN, le scaler et l'imputer) ainsi qu'un fichier CSV de test contenant des coups déjà étiquetés.

* **Prétraitement et Prédiction :**: Il applique la même chaîne de prétraitement (imputation des valeurs manquantes puis mise à l'échelle) sur les données de test, puis utilise le modèle KNN pour prédire le type de chaque coup (y_pred).

* **Calcul de la matrice de confusion (confusion_matrix):** C'est l'étape centrale où scikit-learn compare la liste des prédictions (y_pred) avec la liste des vraies valeurs (y_test). 


* **Visualisation (ConfusionMatrixDisplay) :**
 Le script utilise matplotlib pour générer un graphique coloré de la matrice. 

#### Dépendances externes (librairies)

* **`joblib`**: Utilisé pour charger le modèle, le scaler et l'imputer pré-entraînés.
* **`pandas` & `numpy`**: Pour la gestion des données.
* **`scikit-learn`**: Fournit les fonctions clés pour l'évaluation, notamment confusion_matrix et ConfusionMatrixDisplay.
* **`matplotlib.pyplot`**: Utilisée pour créer et personnaliser la visualisation graphique de la matrice de confusion.



