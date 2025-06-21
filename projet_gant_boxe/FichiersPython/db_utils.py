import mysql.connector as mysql
from datetime import datetime
import arduino_secrets_server as db_secrets
import numpy as np

def ouvrir_connexion_bd():
    """Établit et retourne une connexion à la base de données MySQL."""
    print("\n*** Connexion à la BD ***")
    connexion_bd = None
    try:
        connexion_bd = mysql.connect(
            host=db_secrets.DB_HOST,
            port=db_secrets.DB_PORT,
            user=db_secrets.DB_USER,
            password=db_secrets.DB_PASSWORD,
            database=db_secrets.DB_DATABASE
        )
        if connexion_bd.is_connected():
            print("=> Connexion établie...")
        else:
            print("=> Connexion échouée (pas d'erreur mais non connectée)...")
    except mysql.connector.Error as e:
        print(f"[ERREUR] MySQL: {e}")
    except Exception as e:
        if "NameError" in str(e) and "mysql" in str(e):
            print("[ERREUR] MySQL: Driver 'mysql' non installé ? (pip install mysql-connector-python)")
        else:
            print(f"[ERREUR] Inattendue lors de la connexion BD: {e}")
    return connexion_bd

def fermer_connexion_bd(connexion_bd):
    """Ferme une connexion active à la base de données."""
    print("\nFermeture de la Connexion à la BD")
    if connexion_bd and connexion_bd.is_connected():
        try:
            connexion_bd.close()
            print("=> Connexion fermée...")
        except mysql.connector.Error as e:
            print(f"[ERREUR] MySQL: {e}")
    else:
        print("=> Pas de connexion ouverte ou déjà fermée.")

def inserer_coup_dans_bdd(connexion_bd, id_session, id_user, idTypeCoup, date_coup, details_coup):
    """Insère les détails d'un coup analysé dans la table 'Coups' de la base de données."""
    if not connexion_bd or not connexion_bd.is_connected():
        print("[ERREUR] BDD: Connexion non disponible pour insérer le coup.")
        return False

    def get_order_bool(key_name):
        val = details_coup.get(key_name)
        if val is None or np.isnan(val):
            return None
        return bool(val)

    sql = """
        INSERT INTO Coups (
            id_session, id_user, idTypeCoup, Date_coup, Force_coup, 
            Flexion_poignet_ok, Duree_coup_ms, 
            min_accel_x, max_accel_x, accel_x_amplitude, accel_x_order_min_max, 
            min_accel_z, 
            min_roll, max_roll, roll_order_min_max, 
            max_pitch, min_pitch, pitch_order_min_max
        ) VALUES (
            %(id_session)s, %(id_user)s, %(idTypeCoup)s, %(Date_coup)s, %(Force_coup)s,
            %(Flexion_poignet_ok)s, %(Duree_coup_ms)s,
            %(min_accel_x)s, %(max_accel_x)s, %(accel_x_amplitude)s, %(accel_x_order_min_max)s,
            %(min_accel_z)s,
            %(min_roll)s, %(max_roll)s, %(roll_order_min_max)s,
            %(max_pitch)s, %(min_pitch)s, %(pitch_order_min_max)s
        )
    """
    
    data_to_insert = {
        "id_session": id_session,
        "id_user": id_user,
        "idTypeCoup": idTypeCoup,
        "Date_coup": date_coup,
        "Force_coup": details_coup.get('Force_coup_calculee', 0.0), 
        "Flexion_poignet_ok": details_coup.get('Flexion_poignet_ok', True),
        "Duree_coup_ms": details_coup.get('Duree_coup_ms', 0),
        "min_accel_x": details_coup.get('Min_AccX_Val', np.nan),
        "max_accel_x": details_coup.get('Max_AccX_Val', np.nan),
        "accel_x_amplitude": details_coup.get('AccX_Amplitude', np.nan),
        "accel_x_order_min_max": get_order_bool('AccX_Ord(1=Max>Min)'),
        "min_accel_z": details_coup.get('Min_AccZ_Val', np.nan),
        "min_roll": details_coup.get('Min_Roll_Val', np.nan),
        "max_roll": details_coup.get('Max_Roll_Val', np.nan),
        "roll_order_min_max": get_order_bool('Roll_Ord(1=Max>Min)'),
        "max_pitch": details_coup.get('Max_Pitch_Val', np.nan),
        "min_pitch": details_coup.get('Min_Pitch_Val', np.nan),
        "pitch_order_min_max": get_order_bool('Pitch_Ord(1=Max>Min)')
    }
    
    for key, value in data_to_insert.items():
        if isinstance(value, float) and np.isnan(value):
            data_to_insert[key] = None

    try:
        cursor = connexion_bd.cursor()
        cursor.execute(sql, data_to_insert)
        connexion_bd.commit()
        print(f"-> Coup (Début SeqNum: {details_coup.get('SeqNum_debut_coup', 'N/A')}) inséré avec ID: {cursor.lastrowid}")
        return True
    except mysql.Error as e:
        print(f"[ERREUR] MySQL INSERTION: {e}")
        try:
            connexion_bd.rollback()
        except Exception as rb_err:
            print(f"Erreur pendant le rollback: {rb_err}")
        return False
    except Exception as e:
        print(f"[ERREUR] Inattendue lors de l'insertion du coup: {e}")
        try:
            connexion_bd.rollback()
        except Exception as rb_err:
            print(f"Erreur pendant le rollback: {rb_err}")
        return False
    
def creer_nouvelle_session(connexion_bd, id_user, date_debut=None):
    """Crée une nouvelle session d'entraînement dans la base de données et retourne son ID."""
    if not connexion_bd or not connexion_bd.is_connected():
        print("[ERREUR] BDD: Connexion non disponible pour créer une session.")
        return None

    if date_debut is None:
        date_debut = datetime.now()

    sql = """
        INSERT INTO SessionEntrainement (id_user, Date_debut) 
        VALUES (%(id_user)s, %(Date_debut)s)
    """
    data_session = {
        "id_user": id_user,
        "Date_debut": date_debut
    }

    try:
        cursor = connexion_bd.cursor()
        cursor.execute(sql, data_session)
        connexion_bd.commit()
        id_session_creee = cursor.lastrowid
        print(f"-> Nouvelle session (ID: {id_session_creee}) créée pour l'utilisateur ID: {id_user} à {date_debut.strftime('%Y-%m-%d %H:%M:%S')}")
        return id_session_creee
    
    except mysql.Error as e:
        print(f"[ERREUR] MySQL INSERTION Session: {e}")
        connexion_bd.rollback()
        return None
    except Exception as e:
        print(f"[ERREUR] Inattendue lors de la création de session: {e}")
        connexion_bd.rollback()
        return None
    
def get_user_by_id(connexion_bd, id_user_to_check):
    """Récupère les informations d'un utilisateur par son ID et les retourne sous forme de dictionnaire."""
    if not connexion_bd or not connexion_bd.is_connected():
        print("[ERREUR BDD] Connexion non disponible pour vérifier l'utilisateur.")
        return None
    try:
        cursor = connexion_bd.cursor(dictionary=True) 
        sql = "SELECT * FROM Utilisateur WHERE id_user = %s"
        cursor.execute(sql, (id_user_to_check,))
        user_data = cursor.fetchone()
        cursor.close()
        return user_data
    except mysql.Error as e:
        print(f"[ERREUR MySQL] lors de la recherche de l'utilisateur ID {id_user_to_check}: {e}")
        return None
    except Exception as e:
        print(f"[ERREUR INATTENDUE] get_user_by_id: {e}")
        return None

def create_new_user(connexion_bd, nom, prenom, age, taille, poids):
    """Crée un nouvel utilisateur dans la base de données et retourne son nouvel ID."""
    if not connexion_bd or not connexion_bd.is_connected():
        print("[ERREUR BDD] Connexion non disponible pour créer l'utilisateur.")
        return None
    try:
        cursor = connexion_bd.cursor()
        sql = """
            INSERT INTO Utilisateur (nom, prenom, age, taille, poids)
            VALUES (%s, %s, %s, %s, %s)
        """
        data_user = (
            str(nom).strip(), 
            str(prenom).strip(), 
            int(age), 
            int(taille), 
            float(str(poids).replace(',', '.'))
        )
        cursor.execute(sql, data_user)
        connexion_bd.commit()
        new_user_id = cursor.lastrowid
        cursor.close()
        print(f"-> Nouvel utilisateur '{prenom} {nom}' créé avec succès. ID: {new_user_id}")
        return new_user_id
    except mysql.Error as e:
        print(f"[ERREUR MySQL] lors de la création de l'utilisateur '{prenom} {nom}': {e}")
        connexion_bd.rollback()
        return None
    except ValueError as ve:
        print(f"[ERREUR DONNÉES] pour le nouvel utilisateur: {ve}. L'âge, la taille et le poids doivent être numériques.")
        return None
    except Exception as e:
        print(f"[ERREUR INATTENDUE] create_new_user: {e}")
        connexion_bd.rollback()
        return None

def cloturer_session(connexion_bd, id_session, date_debut, date_fin, pourcentage_reussite):
    """Met à jour une session d'entraînement avec ses informations de fin."""
    if not connexion_bd or not connexion_bd.is_connected():
        print("[ERREUR] BDD: Connexion non disponible pour clôturer la session.")
        return False

    try:
        cursor = connexion_bd.cursor()
        sql_max_force = "SELECT MAX(Force_coup) FROM Coups WHERE id_session = %s"
        cursor.execute(sql_max_force, (id_session,))
        result = cursor.fetchone()
        force_max = result[0] if result and result[0] is not None else 0.0

        if not date_debut or not date_fin:
            print("[ERREUR] date_debut ou date_fin manquant pour calcul de durée.")
            return False
        duree_session = (date_fin - date_debut).total_seconds()

        sql_update = """
            UPDATE SessionEntrainement
            SET Date_fin = %s, Duree_session = %s, pourcentage_reussite = %s, Force_max = %s
            WHERE id_session = %s
        """
        cursor.execute(sql_update, (date_fin, duree_session, pourcentage_reussite, force_max, id_session))
        connexion_bd.commit()
        print(f"-> Session {id_session} clôturée : Date_fin={date_fin}, Duree={duree_session}s, Pourcentage réussite={pourcentage_reussite:.1f}%, Force_max={force_max}")
        return True
    except Exception as e:
        print(f"[ERREUR] lors de la clôture de session: {e}")
        try:
            connexion_bd.rollback()
        except Exception as rb_err:
            print(f"Erreur pendant le rollback: {rb_err}")
        return False