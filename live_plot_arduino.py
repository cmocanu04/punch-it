# live_plot_arduino.py

import socket
import threading
import time
from datetime import datetime
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import os

# --- Configuration ---
HOST = '0.0.0.0'
PORT = 12345
DATA_POINTS_TO_DISPLAY = 500 
PLOT_UPDATE_INTERVAL_MS = 100 # Vous pouvez essayer d'augmenter si c'est encore trop lent

# ... (définition des deques de données - INCHANGÉ) ...
data_queue = collections.deque(maxlen=DATA_POINTS_TO_DISPLAY + 100)
time_axis_data = collections.deque(maxlen=DATA_POINTS_TO_DISPLAY)
accel_data = { 'x': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'y': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'z': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY) }
gyro_data = { 'roll': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'pitch': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'yaw': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY) }
flexiforce_data = { 'f1': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'f2': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'f3': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY), 'f4': collections.deque(maxlen=DATA_POINTS_TO_DISPLAY) }
flexion_sensor_data = collections.deque(maxlen=DATA_POINTS_TO_DISPLAY)
shutdown_event = threading.Event()

# --- Thread Serveur Socket (socket_server_thread_func) ---
# (INCHANGÉ - celui de la réponse précédente avec os.getpid())
def socket_server_thread_func():
    global data_queue, shutdown_event
    print(f"Thread serveur socket démarré. PID: {os.getpid()}, Thread ID: {threading.get_ident()}")
    time.sleep(1) 
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1.0)
        try:
            s.bind((HOST, PORT))
            s.listen()
            print(f"Serveur d'écoute démarré sur {HOST}:{PORT} pour le tracé en temps réel...")
        except Exception as e:
            print(f"ERREUR BIND/LISTEN: {e}. Le port est peut-être déjà utilisé.")
            shutdown_event.set()
            return
        conn = None
        while not shutdown_event.is_set():
            try:
                conn, addr = s.accept()
                print(f"Connecté par {addr} pour le tracé.")
                conn.settimeout(1.0) 
                buffer = ""
                while not shutdown_event.is_set():
                    try:
                        data_chunk = conn.recv(1024)
                        if not data_chunk: print("Client déconnecté (pas de chunk)."); break
                        buffer += data_chunk.decode('utf-8', errors='ignore')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line: continue
                            parts = line.split(',')
                            if len(parts) == 12:
                                try:
                                    parsed_data = tuple([int(parts[0])] + [float(p) for p in parts[1:]])
                                    data_queue.append(parsed_data)
                                except ValueError: print(f"Avertissement: Ligne non parsable: {line}")
                            else: print(f"Avertissement: Ligne malformée ({len(parts)} parties): {line}")
                    except socket.timeout:
                        if shutdown_event.is_set(): break
                        continue 
                    except ConnectionResetError: print("Client déconnecté (reset)."); break
                    except Exception as e_inner: print(f"Erreur socket client: {e_inner}"); break
                if conn: conn.close(); conn = None; print(f"Connexion avec {addr} fermée.")
                if shutdown_event.is_set(): break
            except socket.timeout:
                 if shutdown_event.is_set(): break
                 continue
            except Exception as e_outer:
                print(f"Erreur serveur socket: {e_outer}")
                if shutdown_event.is_set(): break
                time.sleep(0.5)
        if conn: conn.close()
    print("Thread serveur socket terminé.")


# --- Animation Matplotlib ---
fig, axs = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

# Initialisation des lignes
line_accX, = axs[0].plot([], [], lw=1, label='AccX', animated=True) # animated=True pour blit
line_accY, = axs[0].plot([], [], lw=1, label='AccY', animated=True)
line_accZ, = axs[0].plot([], [], lw=1, label='AccZ', animated=True)

line_roll, = axs[1].plot([], [], lw=1, label='Roll (GyroX)', animated=True)
line_pitch, = axs[1].plot([], [], lw=1, label='Pitch (GyroY)', animated=True)
line_yaw, = axs[1].plot([], [], lw=1, label='Yaw (GyroZ)', animated=True)

line_f1, = axs[2].plot([], [], lw=1, label='Force1 (A0)', animated=True)
line_f2, = axs[2].plot([], [], lw=1, label='Force2 (A1)', animated=True)
line_f3, = axs[2].plot([], [], lw=1, label='Force3 (A2)', animated=True)
line_f4, = axs[2].plot([], [], lw=1, label='Force4 (A3)', animated=True)

line_flex, = axs[3].plot([], [], lw=1, label='Flexion Poignet (A6)', animated=True)

# Liste de tous les artistes qui seront mis à jour et retournés
plot_lines_all = [
    line_accX, line_accY, line_accZ, 
    line_roll, line_pitch, line_yaw,
    line_f1, line_f2, line_f3, line_f4, 
    line_flex
]

def init_plots_func():
    """Initialise les graphiques avec des échelles Y FIXES."""
    axs[0].set_title('Accélérations')
    axs[0].set_ylabel('Acc (G)')
    axs[0].legend(loc='upper left', fontsize='x-small'); axs[0].grid(True)
    axs[0].set_ylim(-16, 16) # Votre échelle fixe

    axs[1].set_title('Vitesses Angulaires (Roll/Pitch/Yaw)')
    axs[1].set_ylabel('Vitesse (dps)')
    axs[1].legend(loc='upper left', fontsize='x-small'); axs[1].grid(True)
    axs[1].set_ylim(-1500, 1500) # Votre échelle fixe

    axs[2].set_title('Force Flexiforce (A0-A3)')
    axs[2].set_ylabel('Kg')
    axs[2].legend(loc='upper left', fontsize='x-small'); axs[2].grid(True)
    axs[2].set_ylim(-0.2, 20) 

    axs[3].set_title('Tension Capteur de Flexion Poignet (A6)')
    axs[3].set_ylabel('Tension (V)')
    axs[3].set_xlabel('Échantillon (Numéro de Séquence)')
    axs[3].legend(loc='upper left', fontsize='x-small'); axs[3].grid(True)
    axs[3].set_ylim(0.5, 1.5)
    
    # Mettre les limites X initiales pour tous les axes
    for ax in axs:
        ax.set_xlim(0, DATA_POINTS_TO_DISPLAY)
    
    # La fonction init doit retourner les artistes à dessiner
    return plot_lines_all 

def update_plot_func(frame):
    """Met à jour les données des graphiques SANS changer les échelles Y."""
    global time_axis_data, accel_data, gyro_data, flexiforce_data, flexion_sensor_data
    
    data_processed_this_frame = False
    while data_queue: # Vider la file
        try:
            data_point = data_queue.popleft()
            data_processed_this_frame = True
            time_axis_data.append(data_point[0])
            accel_data['x'].append(data_point[1]); accel_data['y'].append(data_point[2]); accel_data['z'].append(data_point[3])
            gyro_data['roll'].append(data_point[4]); gyro_data['pitch'].append(data_point[5]); gyro_data['yaw'].append(data_point[6])
            flexion_sensor_data.append(data_point[7])
            flexiforce_data['f1'].append(data_point[8]); flexiforce_data['f2'].append(data_point[9]);
            flexiforce_data['f3'].append(data_point[10]); flexiforce_data['f4'].append(data_point[11])
        except IndexError:
            continue # Ignorer les points malformés
            
    if data_processed_this_frame:
        line_accX.set_data(time_axis_data, accel_data['x'])
        line_accY.set_data(time_axis_data, accel_data['y'])
        line_accZ.set_data(time_axis_data, accel_data['z'])

        line_roll.set_data(time_axis_data, gyro_data['roll'])
        line_pitch.set_data(time_axis_data, gyro_data['pitch'])
        line_yaw.set_data(time_axis_data, gyro_data['yaw'])

        line_f1.set_data(time_axis_data, flexiforce_data['f1'])
        line_f2.set_data(time_axis_data, flexiforce_data['f2'])
        line_f3.set_data(time_axis_data, flexiforce_data['f3'])
        line_f4.set_data(time_axis_data, flexiforce_data['f4'])
        
        line_flex.set_data(time_axis_data, flexion_sensor_data)

        # Mettre à jour les limites de l'axe X pour un effet de défilement
        if time_axis_data:
            current_max_seq = time_axis_data[-1]
            # Pour une fenêtre glissante stricte, le min_x dépend du max_x et de la taille de la fenêtre
            plot_min_x = current_max_seq - DATA_POINTS_TO_DISPLAY + 1 if len(time_axis_data) == DATA_POINTS_TO_DISPLAY else time_axis_data[0]
            plot_max_x = current_max_seq
            
            for ax_idx, ax in enumerate(axs):
                ax.set_xlim(plot_min_x, plot_max_x if plot_max_x > plot_min_x else plot_min_x + 1)
                # Avec blit=True et des limites Y fixes, on ne devrait pas avoir besoin de relim/autoscale pour Y.
                # Cependant, si l'axe X change, l'arrière-plan doit être redessiné. Blit peut parfois mal le gérer.
                # Si les axes X ne se mettent pas à jour correctement, il faudra peut-être retourner aussi les axes
                # ou forcer un redraw complet (ce qui annule l'effet de blit).

    return plot_lines_all # Retourne la liste des artistes modifiés

# --- Démarrage ---
if __name__ == '__main__':
    server_thread = threading.Thread(target=socket_server_thread_func, daemon=True)
    server_thread.start()

    ani = animation.FuncAnimation(fig, update_plot_func, init_func=init_plots_func, 
                                  interval=PLOT_UPDATE_INTERVAL_MS, 
                                  blit=True, # <--- REVENIR À BLIT=TRUE
                                  cache_frame_data=False, 
                                  save_count=50) # save_count aide à gérer le cache interne de l'animation
    
    plt.tight_layout(pad=2.5)
    try:
        plt.show()
    except KeyboardInterrupt:
        print("Interruption clavier (Matplotlib).")
    finally:
        print("Fenêtre de tracé fermée ou interruption, signalement d'arrêt...")
        shutdown_event.set()
        if server_thread.is_alive():
            print("Attente de la fin du thread serveur socket...")
            server_thread.join(timeout=2.0)
    print("Script de tracé en temps réel terminé.")