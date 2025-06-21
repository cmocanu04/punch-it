import socket
import threading
import csv
from datetime import datetime
import time
import signal
import sys
import os
import pandas as pd
import numpy as np
import collections
import msvcrt
from colorama import init, Fore, Style
import json

import arduino_secrets_server as db_secrets
import db_utils
import analyse_coups

init(autoreset=True)

HOST = '0.0.0.0'
PORT = 12345

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PARENT_DIRECTORY = os.path.dirname(SCRIPT_DIRECTORY)
FICHIERS_CSV_DIRECTORY = os.path.join(PARENT_DIRECTORY, "fichiers_csv")
FILENAME_CSV_BRUT = os.path.join(FICHIERS_CSV_DIRECTORY, f"session_brute_{timestamp}.csv")
os.makedirs(FICHIERS_CSV_DIRECTORY, exist_ok=True)


RULES_EXPERT_FILE = os.path.join(PARENT_DIRECTORY, "regles_expert.json")


HEADERS_CSV_BRUT = [
    "SeqNum", "AccX", "AccY", "AccZ",
    "GyroX", "GyroY", "GyroZ",
    "Flex", "Force1", "Force2", "Force3", "Force4",
    "TimestampReception"
]

last_sequence_number = None
received_count = 0
lost_count = 0
lock = threading.Lock()
shutdown_flag = False

CSV_BRUT_READY = False
try:
    with open(FILENAME_CSV_BRUT, 'w', newline='', encoding='utf-8') as f:
        writer_brut = csv.writer(f)
        writer_brut.writerow(HEADERS_CSV_BRUT)
    print(f"Fichier CSV pour données brutes créé : {FILENAME_CSV_BRUT}")
    CSV_BRUT_READY = True
except IOError as e:
    print(f"ERREUR CRITIQUE: CSV brut {FILENAME_CSV_BRUT}. ({e})")

ID_UTILISATEUR_ACTUEL = None
ID_SESSION_ACTUELLE = None
CONNEXION_BDD = None

DATA_BUFFER_LIST = []

BUFFER_ANALYSIS_WINDOW_SIZE = 200

NEW_DATA_THRESHOLD_FOR_ANALYSIS = 150

OVERLAP_SIZE = BUFFER_ANALYSIS_WINDOW_SIZE - NEW_DATA_THRESHOLD_FOR_ANALYSIS

RECENTLY_INSERTED_PUNCHES_SEQN = collections.deque(maxlen=10)
DEDUPLICATION_SEQNUM_WINDOW = 40

COLUMNS_FROM_ARDUINO = ["SeqNum", "AccX", "AccY", "AccZ", "GyroX", "GyroY", "GyroZ", "Flex", "Force1", "Force2", "Force3", "Force4"]

REUSSITE_SCORES_LIST = []

FEATURES_WEIGHTS = {
    "Pitch_Ord(1=Max>Min)": 20,
    "Max_Pitch_Val": 20,
    "Min_AccX_Val": 12,
    "Min_AccZ_Val": 9,
    "Max_AccX_Val": 8,
    "Roll_Ord(1=Max>Min)": 7,
    "AccX_Amplitude": 6,
    "Min_Pitch_Val": 5,
    "Max_Roll_Val": 5,
    "AccX_Ord(1=Max>Min)": 3,
    "Min_Roll_Val": 3
}
FEATURES_WEIGHTS_TOTAL = sum(FEATURES_WEIGHTS.values())

def generer_et_afficher_conseils(details_coup):
    """Compare les caractéristiques d'un coup aux règles de l'expert et affiche des conseils."""
    if not REGLES_EXPERT:
        return

    type_coup = details_coup.get('type_determine_knn')
    
    if not type_coup or type_coup not in REGLES_EXPERT:
        return

    print(f"      {Fore.CYAN}--- Analyse du Geste (vs Expert) ---{Style.RESET_ALL}")
    
    regles_pour_coup = REGLES_EXPERT[type_coup]

    for feature in analyse_coups.FEATURES_COLUMNS:
        if feature in details_coup and feature in regles_pour_coup:
            
            valeur_actuelle = details_coup[feature]
            if pd.isna(valeur_actuelle):
                continue

            regle = regles_pour_coup[feature]
            min_ideal = regle['min_ideal']
            max_ideal = regle['max_ideal']
            
            feedback_text = ""
            if valeur_actuelle < min_ideal:
                feedback_text = f"{Fore.YELLOW}Trop bas (votre valeur: {valeur_actuelle:.2f}, idéal > {min_ideal:.2f})"
            elif valeur_actuelle > max_ideal:
                feedback_text = f"{Fore.YELLOW}Trop élevé (votre valeur: {valeur_actuelle:.2f}, idéal < {max_ideal:.2f})"
            else:
                feedback_text = f"{Fore.GREEN}OK (dans la plage idéale)"
            
            print(f"      - {feature:<20}: {feedback_text}")

def shutdown_handler(sig, frame):
    """Définit le drapeau global d'arrêt pour une fermeture propre du serveur."""
    global shutdown_flag
    print("\n[*] Ctrl+C détecté. Arrêt du serveur en cours...")
    shutdown_flag = True

def afficher_coup(type_coup, force_kg, heure, score):
    """Affiche les informations d'un coup détecté dans la console avec une mise en forme colorée."""
    if type_coup.lower() == 'direct':
        couleur = Fore.BLUE
    elif type_coup.lower() == 'crochet':
        couleur = Fore.YELLOW
    elif type_coup.lower() == 'uppercut':
        couleur = Fore.RED
    else:
        couleur = Fore.WHITE
    print(f"{couleur}[{heure}] COUP DÉTECTÉ : {type_coup.upper()} | Force : {force_kg:.1f} N | Confiance : {score:.2f}{Style.RESET_ALL}")

def process_data_buffer(data_window_list):
    """Traite une fenêtre de données pour détecter, classer et insérer les coups dans la base de données."""
    global ID_SESSION_ACTUELLE, ID_UTILISATEUR_ACTUEL, CONNEXION_BDD, RECENTLY_INSERTED_PUNCHES_SEQN

    if not data_window_list:
        return
    
    if ID_SESSION_ACTUELLE is None:
        print("[AVERTISSEMENT] process_data_buffer: ID_SESSION_ACTUELLE est None.")
        return
    if not CONNEXION_BDD or not CONNEXION_BDD.is_connected():
        print("[AVERTISSEMENT] process_data_buffer: Connexion BDD non disponible.")
        return
    if not analyse_coups.KNN_MODEL:
        print("[AVERTISSEMENT] process_data_buffer: Modèle KNN non chargé/entraîné.")
        return

    print(f"Traitement d'une fenêtre de {len(data_window_list)} lignes avec KNN...")
    
    try:
        df_buffer = pd.DataFrame(data_window_list, columns=COLUMNS_FROM_ARDUINO + ['TimestampReception'])
        
        for col in COLUMNS_FROM_ARDUINO[:7]:
            df_buffer[col] = pd.to_numeric(df_buffer[col], errors='coerce')
        for col in COLUMNS_FROM_ARDUINO[7:]:
            df_buffer[col] = pd.to_numeric(df_buffer[col], errors='coerce')
        df_buffer['TimestampReception'] = pd.to_datetime(df_buffer['TimestampReception'])
        
        if 'SeqNum' in df_buffer.columns and not df_buffer['SeqNum'].empty:
            df_buffer.dropna(subset=['SeqNum'], inplace=True)
            if not df_buffer.empty:
                df_buffer = df_buffer.sort_values(by='SeqNum').reset_index(drop=True)
                first_seq_num = df_buffer['SeqNum'].iloc[0]
                t0_reception = df_buffer['TimestampReception'].iloc[0]
                df_buffer['Time'] = t0_reception + pd.to_timedelta( (df_buffer['SeqNum'] - first_seq_num) * analyse_coups.SAMPLING_INTERVAL_SECONDS, unit='s')
            else:
                print("Buffer vide après suppression des SeqNum NaN dans process_data_buffer.")
                return
        else:
            print("Colonne 'SeqNum' manquante ou vide dans la fenêtre, impossible de recalculer 'Time'. Utilisation de TimestampReception.")
            df_buffer['Time'] = df_buffer['TimestampReception']

        df_buffer.dropna(subset=COLUMNS_FROM_ARDUINO[:7], inplace=True) 
        if df_buffer.empty:
            print("Fenêtre de buffer vide après nettoyage des NaN sur IMU, rien à analyser.")
            return

        rename_map = {'GyroX': 'Roll', 'GyroY': 'Pitch', 'GyroZ': 'Yaw'}
        df_buffer.rename(columns=rename_map, inplace=True)

    except Exception as e:
        print(f"Erreur lors de la préparation du DataFrame dans process_data_buffer: {e}")
        return

    predictions = analyse_coups.analyse_buffer_avec_knn(df_buffer.copy())

    if not predictions:
        return

    for prediction_result in predictions:
        type_determine_knn = prediction_result.get("type_determine")
        details_coup_knn = prediction_result.get("details_coup")

        if not type_determine_knn or not details_coup_knn:
            print("Résultat de prédiction malformé, ignoré.")
            continue
            
        print(f"  Coup classifié par KNN: Type={type_determine_knn}, Score (Confiance Max)={details_coup_knn.get('score_final', 0):.2f}")

        seq_num_debut_coup = details_coup_knn.get('SeqNum_debut_coup')
        is_duplicate = False
        if seq_num_debut_coup is not None:
            for recent_seq_num in RECENTLY_INSERTED_PUNCHES_SEQN:
                if abs(seq_num_debut_coup - recent_seq_num) < DEDUPLICATION_SEQNUM_WINDOW:
                    is_duplicate = True
                    print(f"  Coup (SeqNum début: {seq_num_debut_coup}) détecté comme DOUBLON (proche de {recent_seq_num}), non inséré.")
                    break

        if not is_duplicate and \
           type_determine_knn != "Indéterminé" and \
           type_determine_knn != "Indéterminé (Modèle non prêt)" and \
           type_determine_knn != "Indéterminé (Pas de features)" and \
           type_determine_knn != "Indéterminé (Erreur Prédiction)":
            
            map_type_to_id = {
                "direct": 1, "Direct": 1, "Coup Direct": 1, 
                "crochet": 2, "Crochet": 2, "Coup Crochet": 2, 
                "uppercut": 3, "Uppercut": 3, "Coup Uppercut": 3
            }
            idTypeCoup = map_type_to_id.get(type_determine_knn, None)
            
            if idTypeCoup is not None:
                date_coup = details_coup_knn.get('Time_debut_coup', datetime.now())
                if db_utils.inserer_coup_dans_bdd(
                    CONNEXION_BDD,
                    ID_SESSION_ACTUELLE,
                    ID_UTILISATEUR_ACTUEL,
                    idTypeCoup,
                    date_coup,
                    details_coup_knn 
                ):
                    if seq_num_debut_coup is not None:
                        RECENTLY_INSERTED_PUNCHES_SEQN.append(seq_num_debut_coup)
                    score_coup = 0
                    for feature, weight in FEATURES_WEIGHTS.items():
                        regle = None
                        if 'type_determine_knn' in details_coup_knn and details_coup_knn['type_determine_knn'] in REGLES_EXPERT:
                            regles_pour_coup = REGLES_EXPERT[details_coup_knn['type_determine_knn']]
                            regle = regles_pour_coup.get(feature)
                        if regle and feature in details_coup_knn and not pd.isna(details_coup_knn[feature]):
                            val = details_coup_knn[feature]
                            if regle['min_ideal'] <= val <= regle['max_ideal']:
                                score_coup += weight
                    pourcentage_coup = (score_coup / FEATURES_WEIGHTS_TOTAL) * 100
                    REUSSITE_SCORES_LIST.append(pourcentage_coup)
                    print(f"      {Fore.MAGENTA}Pourcentage de réussite du coup : {pourcentage_coup:.1f}%{Style.RESET_ALL}")


                    force_kg = details_coup_knn.get('Force_coup_calculee', 0.0)
                    heure_str = date_coup.strftime('%H:%M:%S') if hasattr(date_coup, 'strftime') else str(date_coup)
                    score = details_coup_knn.get('score_final', 0.0)
                    afficher_coup(type_determine_knn, force_kg, heure_str, score)
                    generer_et_afficher_conseils(details_coup_knn)
                    print("-" * 40)


            else:
                print(f"Type de coup KNN '{type_determine_knn}' non mappé à un ID de BDD valide.")
        elif not is_duplicate:
            print(f"Coup (SeqNum début: {seq_num_debut_coup}) non inséré (type indéterminé par KNN ou erreur modèle).")

def handle_client(conn, addr):
    """Gère la connexion d'un client, reçoit les données et déclenche leur traitement par buffer."""
    global DATA_BUFFER_LIST, shutdown_flag, lock, CSV_BRUT_READY, FILENAME_CSV_BRUT, received_count

    print(f"[+] Nouveau client connecté: {addr}")
    buffer_socket = ""

    csv_writer_instance = None
    csv_file_brut_opened = None

    try:
        conn.settimeout(2.0)
        
        if CSV_BRUT_READY:
            try:
                csv_file_brut_opened = open(FILENAME_CSV_BRUT, 'a', newline='', encoding='utf-8')
                csv_writer_instance = csv.writer(csv_file_brut_opened)
            except IOError as e:
                print(f"[ERREUR] Impossible d'ouvrir {FILENAME_CSV_BRUT} en append: {e}")
                CSV_BRUT_READY = False

        processed_lines_since_last_analysis = 0

        while not shutdown_flag:
            try:
                data = conn.recv(1024)
                if not data:
                    print(f"[-] Client {addr} a envoyé des données vides (déconnexion ?).")
                    break 
            except socket.timeout:
                if shutdown_flag:
                    print(f"[*] Arrêt demandé, sortie de la boucle de réception pour {addr}.")
                    break
                continue
            except ConnectionResetError:
                print(f"[-] Connexion réinitialisée par le client {addr}.")
                break
            except Exception as e:
                print(f"[!] Erreur de réception de {addr}: {e}")
                break

            buffer_socket += data.decode('utf-8', errors='ignore')

            while '\n' in buffer_socket and not shutdown_flag:
                line, buffer_socket = buffer_socket.split('\n', 1)
                line = line.strip()
                if not line: 
                    continue

                reception_time_str = datetime.now().isoformat()

                try:
                    parts = line.split(',')
                    if len(parts) != 12:
                        print(f"[!] Ligne malformée ({len(parts)} colonnes): {line}")
                        continue

                    if csv_writer_instance:
                        try:
                            csv_writer_instance.writerow(parts + [reception_time_str])
                        except Exception as e_csv:
                            print(f"Erreur écriture CSV brut: {e_csv}")
                    
                    with lock:
                        DATA_BUFFER_LIST.append(parts + [reception_time_str])
                        received_count += 1
                        processed_lines_since_last_analysis +=1
                        
                        current_buffer_len = len(DATA_BUFFER_LIST)
                        
                        if current_buffer_len >= BUFFER_ANALYSIS_WINDOW_SIZE and \
                           processed_lines_since_last_analysis >= NEW_DATA_THRESHOLD_FOR_ANALYSIS:
                            
                            window_to_process = list(DATA_BUFFER_LIST[-BUFFER_ANALYSIS_WINDOW_SIZE:])
                            
                            print(f"Déclenchement analyse sur fenêtre de {len(window_to_process)} lignes (buffer total: {current_buffer_len}).")
                            if not shutdown_flag and CONNEXION_BDD and CONNEXION_BDD.is_connected() and analyse_coups.KNN_MODEL:
                                process_data_buffer(window_to_process)

                            processed_lines_since_last_analysis = 0
                            
                            elements_to_remove = BUFFER_ANALYSIS_WINDOW_SIZE - OVERLAP_SIZE
                            if elements_to_remove > 0 and current_buffer_len > elements_to_remove :
                                DATA_BUFFER_LIST = DATA_BUFFER_LIST[elements_to_remove:]
                            elif elements_to_remove > 0 :
                                DATA_BUFFER_LIST = []

                except ValueError as ve:
                    print(f"[!] Erreur de parsing de ligne (ValueError): '{line}' - {ve}")
                except Exception as e_proc:
                    print(f"[!] Erreur traitement ligne: '{line}' - {e_proc}")
            
    finally:
        print(f"[-] Bloc finally pour la connexion {addr}.")
        conn.close()
        if csv_file_brut_opened:
            try:
                csv_file_brut_opened.close()
                print(f"Fichier CSV brut fermé pour {addr}.")
            except Exception as e_close:
                print(f"Erreur fermeture CSV brut pour {addr}: {e_close}")
        
        with lock:
            if not shutdown_flag and DATA_BUFFER_LIST:
                if len(DATA_BUFFER_LIST) >= analyse_coups.MIN_DURATION_SAMPLES_ENERGY_KNN:
                    print(f"Traitement du buffer restant ({len(DATA_BUFFER_LIST)} lignes) pour {addr} avant fin thread...")
                    if CONNEXION_BDD and CONNEXION_BDD.is_connected() and analyse_coups.KNN_MODEL:
                        process_data_buffer(list(DATA_BUFFER_LIST))
                else:
                    print(f"Buffer restant ({len(DATA_BUFFER_LIST)}) pour {addr} trop petit, non traité par ce thread.")
            elif DATA_BUFFER_LIST and shutdown_flag:
                print(f"Buffer restant ({len(DATA_BUFFER_LIST)}) pour {addr} non traité par ce thread (arrêt serveur).")

def start_server():
    """Initialise et démarre le serveur, gère le cycle de vie de la session et les connexions clientes."""
    global shutdown_flag, CONNEXION_BDD, ID_SESSION_ACTUELLE, ID_UTILISATEUR_ACTUEL, REGLES_EXPERT
    global REGLES_EXPERT

    print("\n--- Chargement des règles de l'expert ---")
    try:
        with open(RULES_EXPERT_FILE, 'r', encoding='utf-8') as f:
            REGLES_EXPERT = json.load(f)
        print(f"✅ Fichier de règles '{RULES_EXPERT_FILE}' chargé avec succès.")
    except FileNotFoundError:
        print(f"⚠️  AVERTISSEMENT: Fichier '{RULES_EXPERT_FILE}' non trouvé. Le coaching sera désactivé.")
        REGLES_EXPERT = {}
    except json.JSONDecodeError:
        print(f"❌ ERREUR: Fichier de règles '{RULES_EXPERT_FILE}' mal formaté. Le coaching sera désactivé.")
        REGLES_EXPERT = {}

    CONNEXION_BDD = db_utils.ouvrir_connexion_bd()
    if not CONNEXION_BDD or not CONNEXION_BDD.is_connected():
        print("ERREUR CRITIQUE: Impossible de démarrer, connexion BDD échouée.")
        return

    print("\n--- Identification du Boxeur ---")
    utilisateur_identifie = False
    while not utilisateur_identifie:
        try:
            id_user_input_str = input("Veuillez entrer votre ID utilisateur (numérique) ou 'nouveau' pour créer un compte : ").strip()
            
            if not id_user_input_str:
                print("L'entrée ne peut pas être vide.")
                continue

            if id_user_input_str.lower() == 'nouveau':
                pass
            
            elif id_user_input_str.isdigit():
                id_user_input = int(id_user_input_str)
                user_data = db_utils.get_user_by_id(CONNEXION_BDD, id_user_input)

                if user_data:
                    ID_UTILISATEUR_ACTUEL = user_data['id_user']
                    print(f"Bienvenue {user_data.get('prenom', '')} {user_data.get('nom', '')} (ID: {ID_UTILISATEUR_ACTUEL}) !")
                    utilisateur_identifie = True
                    break
                else:
                    print(f"L'ID utilisateur {id_user_input} n'existe pas.")
            
            else:
                print("Entrée invalide. Veuillez entrer un ID numérique ou 'nouveau'.")
                continue

            if not utilisateur_identifie and (id_user_input_str.lower() == 'nouveau' or \
                (id_user_input_str.isdigit() and not user_data) ) :
                
                creer_choix = input("Aucun utilisateur trouvé avec cet ID ou vous avez demandé 'nouveau'. Créer un nouvel utilisateur ? (o/n) : ").lower()
                if creer_choix == 'o':
                    print("\n--- Création d'un Nouvel Utilisateur ---")
                    nom = input("Nom de famille : ").strip()
                    prenom = input("Prénom : ").strip()
                    while True:
                        age_str = input("Âge : ").strip()
                        if age_str.isdigit() and int(age_str) > 0: break
                        print("Âge invalide. Veuillez entrer un nombre positif.")
                    while True:
                        taille_str = input("Taille (cm) : ").strip()
                        if taille_str.isdigit() and int(taille_str) > 0: break
                        print("Taille invalide. Veuillez entrer un nombre positif.")
                    while True:
                        poids_str = input("Poids (kg, ex: 68.5 ou 68,5) : ").strip().replace(',', '.')
                        try: poids_float = float(poids_str)
                        except ValueError: print("Format du poids invalide."); continue
                        if poids_float > 0: break
                        print("Poids invalide. Veuillez entrer un nombre positif.")
                        
                    new_id = db_utils.create_new_user(CONNEXION_BDD, nom, prenom, int(age_str), int(taille_str), float(poids_str))
                    if new_id:
                        ID_UTILISATEUR_ACTUEL = new_id
                        print(f"Nouvel utilisateur '{prenom} {nom}' créé avec succès. Votre nouvel ID est : {ID_UTILISATEUR_ACTUEL}")
                        utilisateur_identifie = True
                    else:
                        print("La création du nouvel utilisateur a échoué. Réessayez de vous identifier ou de créer.")
                else:
                    print("Création annulée. Veuillez réessayer de vous identifier.")

        except ValueError:
            print("ID utilisateur invalide. Veuillez entrer un nombre ou 'nouveau'.")
        except Exception as e:
            print(f"Une erreur est survenue lors de l'identification: {e}")
            db_utils.fermer_connexion_bd(CONNEXION_BDD)
            return
    
    if not utilisateur_identifie:
        print("Impossible d'identifier ou de créer un utilisateur. Arrêt du serveur.")
        db_utils.fermer_connexion_bd(CONNEXION_BDD)
        return

    print(f"\nCréation d'une nouvelle session pour l'utilisateur ID: {ID_UTILISATEUR_ACTUEL}...")
    ID_SESSION_ACTUELLE = db_utils.creer_nouvelle_session(CONNEXION_BDD, ID_UTILISATEUR_ACTUEL)
    
    if ID_SESSION_ACTUELLE is None:
        print("ERREUR CRITIQUE: Impossible de créer une session. Arrêt du serveur.")
        db_utils.fermer_connexion_bd(CONNEXION_BDD)
        return
    
    print("\n--- Initialisation du modèle KNN ---")
    try:
        analyse_coups_module_path = os.path.dirname(os.path.abspath(analyse_coups.__file__))
        
        training_data_filename = "dataset_entrainement_knn.csv"
        path_to_training_data = os.path.join(analyse_coups_module_path, training_data_filename)

        model_file_name = analyse_coups.MODEL_FILENAME
        path_to_model_file = os.path.join(analyse_coups_module_path, model_file_name)

        if os.path.exists(path_to_model_file):
            print(f"Tentative de chargement du modèle KNN depuis {analyse_coups_module_path}...")
            if not analyse_coups.charger_modele_knn_entraine():
                print("Échec du chargement du modèle. Vérifiez les fichiers ou entraînez à nouveau.")
                if os.path.exists(path_to_training_data):
                    print(f"Tentative d'entraînement du modèle depuis {path_to_training_data}...")
                    if not analyse_coups.train_and_store_knn_model(path_to_training_data):
                        print("ERREUR CRITIQUE: Échec de l'entraînement du modèle KNN. Le serveur ne peut pas continuer avec la prédiction.")
                else:
                    print(f"Fichier d'entraînement '{path_to_training_data}' non trouvé. Impossible d'entraîner.")
        elif os.path.exists(path_to_training_data):
            print(f"Aucun modèle sauvegardé trouvé. Tentative d'entraînement depuis {path_to_training_data}...")
            if not analyse_coups.train_and_store_knn_model(path_to_training_data):
                print("ERREUR CRITIQUE: Échec de l'entraînement initial du modèle KNN.")
        else:
            print(f"ATTENTION: Fichier d'entraînement '{path_to_training_data}' ET modèle sauvegardé non trouvés.")
            print("Le modèle KNN ne sera pas initialisé. Les prédictions des coups seront 'Indéterminé'.")

    except AttributeError as e:
        print(f"Erreur d'attribut lors de l'initialisation du modèle (vérifiez analyse_coups.py): {e}")
    except Exception as e:
        print(f"Erreur inattendue lors de l'initialisation du modèle KNN: {e}")

    signal.signal(signal.SIGINT, shutdown_handler)
    
    date_debut_session = datetime.now()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1.0)
        try:
            s.bind((HOST, PORT))
            s.listen()
            print(f"[*] Serveur principal démarré. Écoute sur {HOST}:{PORT}...")
            print(f"[*] Utilisateur Actuel ID: {ID_UTILISATEUR_ACTUEL}, Session Actuelle ID: {ID_SESSION_ACTUELLE}")
            print(f"[*] Fichier CSV Brut des données sauvegardé dans : {FILENAME_CSV_BRUT}")
            print("[*] Appuyez sur Ctrl+C, 'q' ou 'Esc' pour arrêter.")
        except OSError as e:
            print(f"[!] ERREUR lors du bind sur le port {PORT}: {e}")
            db_utils.fermer_connexion_bd(CONNEXION_BDD)
            return

        active_client_threads = []
        global shutdown_flag
        while not shutdown_flag:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in [b'q', b'Q', b'\x1b']:
                    print("\n[*] Touche 'q' ou 'Esc' détectée. Arrêt du serveur en cours...")
                    shutdown_flag = True
                    break
            try:
                conn, addr = s.accept()
                client_thread = threading.Thread(target=handle_client, args=(conn, addr))
                client_thread.daemon = True
                client_thread.start()
                active_client_threads.append(client_thread)
            except socket.timeout:
                continue
            except Exception as e:
                if not shutdown_flag: 
                    print(f"[!] Erreur lors de l'acceptation de connexion: {e}")
            active_client_threads = [t for t in active_client_threads if t.is_alive()]

    print("\nLe serveur s'arrête...")

    print("Attente de la fin des threads clients actifs...")
    for t in active_client_threads:
        t.join(timeout=5.0)
        if t.is_alive():
            print(f"Avertissement: Le thread client {t.name} n'a pas terminé à temps.")

    with lock:
        if DATA_BUFFER_LIST:
            print("\nTraitement final du buffer global avant fermeture BDD...")
            if CONNEXION_BDD and CONNEXION_BDD.is_connected() and analyse_coups.KNN_MODEL:
                if len(DATA_BUFFER_LIST) >= analyse_coups.MIN_DURATION_SAMPLES_ENERGY_KNN:
                    process_data_buffer(list(DATA_BUFFER_LIST))
                else:
                    print(f"Buffer global final ({len(DATA_BUFFER_LIST)}) lignes trop petit, non traité.")
                DATA_BUFFER_LIST.clear()
            else:
                print("Buffer global non traité (final) car la connexion BDD est fermée/non initialisée ou modèle KNN non prêt.")
                DATA_BUFFER_LIST.clear()
        else:
            print("Aucune donnée restante dans le buffer global à traiter.")

    date_fin_session = datetime.now()
    pourcentage_reussite_session = 0.0
    if REUSSITE_SCORES_LIST:
        pourcentage_reussite_session = sum(REUSSITE_SCORES_LIST) / len(REUSSITE_SCORES_LIST)
    if ID_SESSION_ACTUELLE is not None:
        db_utils.cloturer_session(CONNEXION_BDD, ID_SESSION_ACTUELLE, date_debut_session, date_fin_session, pourcentage_reussite_session)

    db_utils.fermer_connexion_bd(CONNEXION_BDD)
    
    print("\n--- Résumé de la Session ---") 
    print(f"  Messages Reçus: {received_count}")
    if ID_SESSION_ACTUELLE is not None:
        print(f"  Données pour utilisateur ID: {ID_UTILISATEUR_ACTUEL}, session ID: {ID_SESSION_ACTUELLE}")
    print("[*] Serveur principal arrêté.")

if __name__ == "__main__":
    start_server()