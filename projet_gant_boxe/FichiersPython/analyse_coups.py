"""
Module d'analyse des coups de boxe à partir de données capteurs.
Ce module contient les fonctions de traitement du signal, d'extraction de features,
de classification KNN, et d'analyse de segments de coups.
"""
import pandas as pd
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
import os
import joblib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SMOOTHING_WINDOW_SIZE_KNN = 15
SAMPLING_INTERVAL_SECONDS = 0.01

ENERGY_WINDOW_SIZE_KNN = 15
ENERGY_ACTIVITY_THRESHOLD_KNN = 3.0
MIN_DURATION_SAMPLES_ENERGY_KNN = 15
MERGE_GAP_SAMPLES_ENERGY_KNN = 10
ROTATION_EXTREMA_MARGIN_SECONDS_KNN = 0.25
FLEX_WRIST_THRESHOLD_MAX = 1.1
FLEX_WRIST_THRESHOLD_MIN = 0.8

FEATURES_COLUMNS = [
    'Min_AccX_Val', 'Max_AccX_Val', 'AccX_Amplitude', 'AccX_Ord(1=Max>Min)',
    'Min_AccZ_Val',
    'Max_Roll_Val', 'Min_Roll_Val', 'Roll_Ord(1=Max>Min)',
    'Max_Pitch_Val', 'Min_Pitch_Val', 'Pitch_Ord(1=Max>Min)'
]

KNN_MODEL = None
SCALER = None
IMPUTER = None

MODEL_FILENAME = "../joblib/Commun/knn_model_gant.joblib"
SCALER_FILENAME = "../joblib/Commun/scaler_gant.joblib"
IMPUTER_FILENAME = "../joblib/Commun/imputer_gant.joblib"

def smooth_data_knn(df_column, window_size=SMOOTHING_WINDOW_SIZE_KNN):
    """Lisse les données d'une colonne DataFrame en utilisant une moyenne mobile."""
    if window_size <= 0 or len(df_column) < window_size: return df_column
    return df_column.rolling(window=window_size, center=True, min_periods=1).mean()

def calculate_accel_magnitude_smoothed(df, ax_col='AccX_Smoothed', ay_col='AccY_Smoothed', az_col='AccZ_Smoothed'):
    """Calcule la magnitude du vecteur d'accélération à partir des composantes lissées."""
    required_cols = [ax_col, ay_col, az_col]
    if not all(col in df.columns for col in required_cols):
        missing_cols = [col for col in required_cols if col not in df.columns]
        return None
    return np.sqrt(df[ax_col]**2 + df[ay_col]**2 + df[az_col]**2)

def calculate_energy_envelope(signal_series, window_size=ENERGY_WINDOW_SIZE_KNN):
    """Calcule l'enveloppe énergétique d'un signal en utilisant une moyenne mobile sur le signal au carré."""
    if signal_series is None or signal_series.empty:
        return pd.Series(dtype=float)
    squared_signal = signal_series**2
    return squared_signal.rolling(window=window_size, center=True, min_periods=1).mean()

def segment_coups_par_energie(df, energy_envelope_signal, activity_threshold, min_duration_samples=MIN_DURATION_SAMPLES_ENERGY_KNN, merge_gap_samples=MERGE_GAP_SAMPLES_ENERGY_KNN):
    """Segmente les coups dans un DataFrame en se basant sur un signal d'enveloppe énergétique."""
    if energy_envelope_signal is None or energy_envelope_signal.empty: return []
    active_regions = (energy_envelope_signal > activity_threshold)
    if not active_regions.any(): return []
    change_points = active_regions.astype(int).diff()
    start_indices_pos = np.where(change_points == 1)[0]
    end_indices_pos = np.where(change_points == -1)[0]
    start_indices = energy_envelope_signal.index[start_indices_pos].tolist()
    end_indices = energy_envelope_signal.index[end_indices_pos].tolist()
    if active_regions.iloc[0]:
        if not start_indices or start_indices[0] != energy_envelope_signal.index[0]: start_indices.insert(0, energy_envelope_signal.index[0])
    if active_regions.iloc[-1]:
        if not end_indices or end_indices[-1] < energy_envelope_signal.index[-1]: end_indices.append(energy_envelope_signal.index[-1])
    segments = []
    current_e_idx_pos_in_list = 0
    for s_val in start_indices:
        possible_ends = [e_val for e_val in end_indices[current_e_idx_pos_in_list:] if e_val > s_val]
        if possible_ends:
            e_val_chosen = possible_ends[0]
            segments.append((s_val, e_val_chosen))
            try: current_e_idx_pos_in_list = end_indices.index(e_val_chosen, current_e_idx_pos_in_list) + 1
            except ValueError: current_e_idx_pos_in_list = len(end_indices)
        elif active_regions.loc[s_val:].any():
            segments.append((s_val, energy_envelope_signal.index[-1])); break
    segments_duree_ok = []
    min_required_duration_seconds = min_duration_samples * SAMPLING_INTERVAL_SECONDS
    for s, e in segments:
        if s in df.index and e in df.index and s <= e:
            if (df.loc[e, 'Time'] - df.loc[s, 'Time']).total_seconds() >= min_required_duration_seconds: segments_duree_ok.append((s, e))
    if not segments_duree_ok: return []
    merged_segments = []
    current_start, current_end = segments_duree_ok[0]
    for i in range(1, len(segments_duree_ok)):
        next_start, next_end = segments_duree_ok[i]
        try: gap_indices_count = df.index.get_loc(next_start) - df.index.get_loc(current_end) - 1
        except KeyError:
            merged_segments.append((current_start, current_end)); current_start, current_end = next_start, next_end; continue
        if gap_indices_count <= merge_gap_samples : current_end = next_end
        else: merged_segments.append((current_start, current_end)); current_start, current_end = next_start, next_end
    merged_segments.append((current_start, current_end))
    return merged_segments

def classify_order_extrema_knn(idx_min, idx_max):
    """Détermine l'ordre temporel d'occurrence d'un minimum et d'un maximum."""
    if idx_min is None or idx_max is None or pd.isna(idx_min) or pd.isna(idx_max): return np.nan
    if idx_min < idx_max: return 0 
    elif idx_max < idx_min: return 1
    else: return np.nan

def find_rotation_extrema_knn(df, column_name, peak1_idx, peak2_idx, margin_seconds=ROTATION_EXTREMA_MARGIN_SECONDS_KNN):
    """Trouve les extrema de rotation (minimum et maximum) dans une fenêtre temporelle définie."""
    if peak1_idx is None or peak2_idx is None or not (peak1_idx in df.index and peak2_idx in df.index): 
        return None, None, np.nan, np.nan
    time_peak1 = df['Time'].loc[peak1_idx]
    time_peak2 = df['Time'].loc[peak2_idx]
    start_time = time_peak1 - pd.Timedelta(seconds=margin_seconds)
    end_time = time_peak2 + pd.Timedelta(seconds=margin_seconds)
    segment = df[(df['Time'] >= start_time) & (df['Time'] <= end_time)]
    if segment.empty or column_name not in segment.columns or segment[column_name].isnull().all(): 
        return None, None, np.nan, np.nan
    vals = segment[column_name]
    max_val, min_val = vals.max(), vals.min()
    max_idx = vals.idxmax() if pd.notna(max_val) else None
    min_idx = vals.idxmin() if pd.notna(min_val) else None
    return max_idx, min_idx, max_val, min_val

def extract_features_from_segment(df_full, p1_idx, p2_idx):
    """Extrait un ensemble de caractéristiques (features) à partir d'un segment de données représentant un coup."""
    features = {col_name: np.nan for col_name in FEATURES_COLUMNS}
    if p1_idx is None or p2_idx is None or p1_idx not in df_full.index or p2_idx not in df_full.index or p1_idx >= p2_idx: return features
    seg = df_full.loc[p1_idx:p2_idx].copy()
    if seg.empty: return features
    if 'AccX_Smoothed' in seg.columns:
        ax_seg = seg['AccX_Smoothed']
        if not ax_seg.empty and not ax_seg.isnull().all():
            min_val,max_val = ax_seg.min(),ax_seg.max()
            features['Min_AccX_Val'],features['Max_AccX_Val'] = min_val,max_val
            if pd.notna(min_val) and pd.notna(max_val): features['AccX_Amplitude'] = max_val - min_val
            features['AccX_Ord(1=Max>Min)'] = classify_order_extrema_knn(ax_seg.idxmin(), ax_seg.idxmax())
    if 'AccZ_Smoothed' in seg.columns:
        az_seg = seg['AccZ_Smoothed']
        if not az_seg.empty and not az_seg.isnull().all(): features['Min_AccZ_Val'] = az_seg.min()
    if 'Roll_Smoothed' in df_full.columns:
        max_r_idx, min_r_idx, max_r_val, min_r_val = find_rotation_extrema_knn(df_full, 'Roll_Smoothed', p1_idx, p2_idx)
        features['Max_Roll_Val'], features['Min_Roll_Val'] = max_r_val, min_r_val
        features['Roll_Ord(1=Max>Min)'] = classify_order_extrema_knn(min_r_idx, max_r_idx)
    if 'Pitch_Smoothed' in df_full.columns:
        max_p_idx, min_p_idx, max_p_val, min_p_val = find_rotation_extrema_knn(df_full, 'Pitch_Smoothed', p1_idx, p2_idx)
        features['Max_Pitch_Val'], features['Min_Pitch_Val'] = max_p_val, min_p_val
        features['Pitch_Ord(1=Max>Min)'] = classify_order_extrema_knn(min_p_idx, max_p_idx)

    force_cols = ['Force1', 'Force2', 'Force3', 'Force4']
    
    if all(col in seg.columns for col in force_cols) and not seg[force_cols].isnull().all().all():
        for col in force_cols:
            seg[col] = pd.to_numeric(seg[col], errors='coerce')
        
        features['Force_coup_calculee'] = 0.0
        for i, force_col in enumerate(force_cols, 1):
            max_val = seg[force_col].max()
            print(f"Max Force{i} ({force_col}): {max_val}")
            
            features['Force_coup_calculee'] += max_val
        
    else:
        features['Force_coup_calculee'] = 0.0

    if 'Flex' in seg.columns and not seg['Flex'].isnull().all():
        seg['Flex'] = pd.to_numeric(seg['Flex'], errors='coerce')
        
        features['Flexion_poignet_ok'] = seg['Flex'].max() < FLEX_WRIST_THRESHOLD_MAX and seg['Flex'].min() > FLEX_WRIST_THRESHOLD_MIN
    else:
        features['Flexion_poignet_ok'] = True
        
    return features


def charger_modele_knn_entraine(model_name=MODEL_FILENAME, 
                                  scaler_name=SCALER_FILENAME, 
                                  imputer_name=IMPUTER_FILENAME):
    """Charge un modèle KNN, un scaler et un imputer pré-entraînés depuis des fichiers."""
    global KNN_MODEL, SCALER, IMPUTER, SCRIPT_DIR
    model_path = os.path.join(SCRIPT_DIR, model_name)
    scaler_path = os.path.join(SCRIPT_DIR, scaler_name)
    imputer_path = os.path.join(SCRIPT_DIR, imputer_name)
    try:
        if not all(os.path.exists(p) for p in [model_path, scaler_path, imputer_path]):
            print(f"ATTENTION: Fichiers non trouvés pour charger le modèle. Vérifiez les chemins: \n{model_path}\n{scaler_path}\n{imputer_path}")
            return False
        KNN_MODEL = joblib.load(model_path)
        SCALER = joblib.load(scaler_path)
        IMPUTER = joblib.load(imputer_path)
        print(f"Modèle KNN, Scaler et Imputer chargés depuis {SCRIPT_DIR}.")
        return True
    except Exception as e:
        print(f"ERREUR chargement modèle: {e}")
        return False

def predict_coup_knn(df_features_un_coup):
    """Prédit le type d'un coup unique en utilisant le modèle KNN chargé."""
    if KNN_MODEL is None or SCALER is None or IMPUTER is None: return "Indéterminé (Modèle non prêt)", {} 
    if df_features_un_coup is None or df_features_un_coup.empty: return "Indéterminé (Pas de features)", {}
    try:
        X_new_df = pd.DataFrame(columns=FEATURES_COLUMNS); X_new_df.loc[0] = np.nan
        for col in FEATURES_COLUMNS:
            if col in df_features_un_coup.columns: X_new_df[col] = df_features_un_coup[col].values[0]
        X_new_imputed = IMPUTER.transform(X_new_df) 
        X_new_scaled = SCALER.transform(X_new_imputed)
        prediction = KNN_MODEL.predict(X_new_scaled); proba = KNN_MODEL.predict_proba(X_new_scaled)
        probabilities = dict(zip(KNN_MODEL.classes_, proba[0]))
        details_prediction = {'type_determine_knn': prediction[0], 'score_knn_probabilities': probabilities, 'score_final': np.max(proba[0]) if proba.size > 0 else 0}
        details_prediction.update(X_new_df.iloc[0].to_dict())
        return prediction[0], details_prediction
    except Exception as e: print(f"Erreur prédiction KNN: {e}"); return "Indéterminé (Erreur Prédiction)", {}

def analyse_buffer_avec_knn(df_buffer_complet):
    """Analyse un buffer de données complet pour détecter, segmenter et classifier les coups."""
    if df_buffer_complet is None or df_buffer_complet.empty: return []
    cols_to_smooth = ['AccX', 'AccY', 'AccZ', 'Roll', 'Pitch', 'Yaw']
    for col in cols_to_smooth:
        if col in df_buffer_complet.columns: df_buffer_complet[f'{col}_Smoothed'] = smooth_data_knn(df_buffer_complet[col])
        elif col in ['AccX', 'AccY', 'AccZ']: return [] 
    df_buffer_complet['AccelMagnitude_Smoothed'] = calculate_accel_magnitude_smoothed(df_buffer_complet)
    if df_buffer_complet['AccelMagnitude_Smoothed'] is None: return []
    df_buffer_complet['EnergyEnvelope'] = calculate_energy_envelope(df_buffer_complet['AccelMagnitude_Smoothed'])
    if df_buffer_complet['EnergyEnvelope'].empty: return []
    
    detected_segments_indices = segment_coups_par_energie(df_buffer_complet, df_buffer_complet['EnergyEnvelope'], ENERGY_ACTIVITY_THRESHOLD_KNN)
    predictions_finales = []
    if not detected_segments_indices: return []
    
    for i, (p1_idx, p2_idx) in enumerate(detected_segments_indices):
        features_dict = extract_features_from_segment(df_buffer_complet, p1_idx, p2_idx)
        
        if features_dict:
            df_features_un_coup = pd.DataFrame([features_dict])
            
            type_predit, details_pred = predict_coup_knn(df_features_un_coup)
            
            details_pred['Force_coup_calculee'] = features_dict.get('Force_coup_calculee')
            details_pred['Flexion_poignet_ok'] = features_dict.get('Flexion_poignet_ok')
            
            if 'SeqNum' in df_buffer_complet.columns and p1_idx in df_buffer_complet.index: 
                details_pred['SeqNum_debut_coup'] = df_buffer_complet['SeqNum'].loc[p1_idx]
                
            if 'Time' in df_buffer_complet.columns and p1_idx in df_buffer_complet.index and p2_idx in df_buffer_complet.index:
                details_pred['Time_debut_coup'] = df_buffer_complet['Time'].loc[p1_idx]
                details_pred['Duree_coup_ms'] = (df_buffer_complet['Time'].loc[p2_idx] - df_buffer_complet['Time'].loc[p1_idx]).total_seconds() * 1000
                
            predictions_finales.append({"type_determine": type_predit, "details_coup": details_pred})
    return predictions_finales

