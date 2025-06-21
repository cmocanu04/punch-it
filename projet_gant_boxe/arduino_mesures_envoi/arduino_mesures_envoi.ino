#include <WiFiNINA.h>
#include <SPI.h>
#include <LSM6DS3.h>
#include <Wire.h>
#include "arduino_secrets.h" // N'oubliez pas ce fichier !

// --- Configuration WiFi ---
char ssid[] = SECRET_SSID;
char pass[] = SECRET_PASS;
int status = WL_IDLE_STATUS;

// --- Configuration Serveur (Votre PC) ---
char serverIp[] = "192.168.243.125"; // !! METTEZ L'IP DE VOTRE PC !!
int serverPort = 12345;

// --- Client WiFi ---
WiFiClient client;

// --- Configuration IMU ---
LSM6DS3 myIMU(I2C_MODE, 0x6A);
float aX, aY, aZ, gX, gY, gZ;

// --- Configuration Autres Capteurs ---
const int flexPin = A6;
const int forcePin0 = A0;
const int forcePin1 = A1;
const int forcePin2 = A2;
const int forcePin3 = A3;
float flexValue = 0;
float force0 = 0, force1 = 0, force2 = 0, force3 = 0;

// --- Constantes pour la conversion Analogique -> Tension ---
const float Vcc = 3.3;              // Tension d'alimentation de 3.3V
const float resolutionADC = 1023.0; // Résolution du convertisseur analogique-numérique

// --- Timing & Compteur ---
unsigned long previousMillis = 0;
const long interval = 10;
unsigned long messageCounter = 0;

// --- LED Intégrée ---
const int ledPin = LED_BUILTIN;

// ==============================================================================
// SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Démarrage du Gant de Boxe Connecté...");

  pinMode(ledPin, OUTPUT);
  digitalWrite(ledPin, LOW);

  Serial.println("Vérification module WiFi...");
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("ERREUR: Module WiFi non détecté !");
    while (true) {
      digitalWrite(ledPin, HIGH); delay(100);
      digitalWrite(ledPin, LOW); delay(100);
    }
  }

  Serial.println("Tentative de connexion au WiFi...");
  while (status != WL_CONNECTED) {
    Serial.print("Connexion à : ");
    Serial.println(ssid);
    status = WiFi.begin(ssid, pass);

    unsigned long startTime = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startTime < 10000) {
      digitalWrite(ledPin, HIGH); delay(250);
      digitalWrite(ledPin, LOW); delay(250);
      Serial.print(".");
    }
    status = WiFi.status();

    if (status != WL_CONNECTED) {
        Serial.println("\nÉchec. Nouvelle tentative dans 5s...");
        WiFi.disconnect();
        digitalWrite(ledPin, LOW);
        delay(5000);
    }
  }

  Serial.println("\nConnecté au WiFi!");
  digitalWrite(ledPin, HIGH);
  printWifiStatus();

  Serial.println("Initialisation de la centrale inertielle...");
  Wire.begin();
  if (myIMU.begin() != 0) {
    Serial.println("ERREUR: IMU !");
    while (true) {
      digitalWrite(ledPin, HIGH); delay(500);
      digitalWrite(ledPin, LOW); delay(500);
    }
  } else {
    Serial.println("Centrale inertielle OK.");
  }

  Serial.println("Initialisation des autres capteurs...");
  pinMode(flexPin, INPUT);
  pinMode(forcePin0, INPUT);
  pinMode(forcePin1, INPUT);
  pinMode(forcePin2, INPUT);
  pinMode(forcePin3, INPUT);
  Serial.println("Tous les capteurs sont prêts.");

  Serial.println("\n===== Démarrage de l'envoi des données =====");
  digitalWrite(ledPin, HIGH);
}

// ==============================================================================
// LOOP
// ==============================================================================
void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // --- 1. Lire les capteurs ---
    aX = myIMU.readFloatAccelX(); aY = myIMU.readFloatAccelY(); aZ = myIMU.readFloatAccelZ();
    gX = myIMU.readFloatGyroX(); gY = myIMU.readFloatGyroY(); gZ = myIMU.readFloatGyroZ();
    flexValue = analogRead(flexPin) * 3.3 / 1023.0;
    
    // --- NOUVEAU CALCUL DE FORCE ---
    // Lire la tension (Vout) puis calculer la force via les nouvelles fonctions
    float vout0 = (analogRead(forcePin0) / resolutionADC) * Vcc;
    force0 = calculerForce0(vout0);

    float vout1 = (analogRead(forcePin1) / resolutionADC) * Vcc;
    force1 = calculerForce1(vout1);

    float vout2 = (analogRead(forcePin2) / resolutionADC) * Vcc;
    force2 = calculerForce2(vout2);

    float vout3 = (analogRead(forcePin3) / resolutionADC) * Vcc;
    force3 = calculerForce3(vout3);
    
    // --- 2. Formater les données ---
    messageCounter++;
    String dataString = String(messageCounter) + "," + String(aX, 4) + "," + String(aY, 4) + "," +
                      String(aZ, 4) + "," + String(gX, 3) + "," + String(gY, 3) + "," +
                      String(gZ, 3) + "," + String(flexValue) + "," + String(force0, 4) + "," +
                      String(force1, 4) + "," + String(force2, 4) + "," + String(force3, 4);
    

    /*Serial.println();
    Serial.print("force0 ");
    Serial.println(force0);
    
    Serial.print("force1 ");
    Serial.println(force1);
    Serial.print("force2 ");
    Serial.println(force2);
    Serial.print("force3 ");
    Serial.println(force3);
    */

    // --- 3. Envoyer les données et Gérer la LED ---
    if (!client.connected()) {
        digitalWrite(ledPin, LOW);
        client.stop();
        if (client.connect(serverIp, serverPort)) {
            Serial.println("Reconnecté au serveur !");
            digitalWrite(ledPin, HIGH);
        } else {
            messageCounter--;
            return;
        }
    }

    if (client.connected()) {
        client.println(dataString);
        digitalWrite(ledPin, HIGH);
    } else {
       digitalWrite(ledPin, LOW);
       messageCounter--;
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
     Serial.println("Connexion WiFi générale perdue !");
     digitalWrite(ledPin, HIGH); delay(750);
     digitalWrite(ledPin, LOW); delay(750);
  }
}

// ==============================================================================
// NOUVELLES Fonctions de Calcul de Force (basées sur les polynômes)
// ==============================================================================
/**
 * @brief Calcule la force pour le capteur 0 (FF0_2). F0 en Newtons.
 * @param V0 La tension de sortie (Vout) mesurée.
 */
float calculerForce0(float V0) {
  // Équation: F0 = -515.19898 * V0^2 + 1071.25800 * V0 + 9.11293
  float force = -515.198984593164710 * (V0 * V0) + 1071.258004946775827 * V0 + 9.112931353437329;
  return (force > 0) ? force : 0.0; // Empêche les valeurs de force négatives
}

/**
 * @brief Calcule la force pour le capteur 1 (FF1_2). F0 en Newtons.
 * @param V0 La tension de sortie (Vout) mesurée.
 */
float calculerForce1(float V0) {
  // Équation: F0 = -1143.99819 * V0^2 + 1565.51882 * V0 + 22.01861
  float force = -1143.998197279131546 * (V0 * V0) + 1565.518829834247299 * V0 + 2.018611565732517;
  return (force > 0) ? force : 0.0;
}

/**
 * @brief Calcule la force pour le capteur 2 (FF2_1). F0 en Newtons.
 * @param V0 La tension de sortie (Vout) mesurée.
 */
float calculerForce2(float V0) {
  // Équation: F0 = -59.96347 * V0^2 + 464.58438 * V0 + 4.64357
  float force = -59.963474506451959 * (V0 * V0) + 464.584381011761536 * V0 + 4.643579614114014;
  return (force > 0) ? force : 0.0;
}

/**
 * @brief Calcule la force pour le capteur 3 (FF3). F0 en Newtons.
 * @param V0 La tension de sortie (Vout) mesurée.
 */
float calculerForce3(float V0) {
  // Équation: F0 = 25.32073 * V0^2 + 318.87550 * V0 + 2.33577
  float force = 25.320737643516988 * (V0 * V0) + 318.875504767434961 * V0 + 2.335772354201391;
  return (force > 0) ? force : 0.0;
}


// ==============================================================================
// Fonctions Utilitaires
// ==============================================================================
void printWifiStatus() {
  Serial.print("SSID: ");
  Serial.println(WiFi.SSID());
  IPAddress ip = WiFi.localIP();
  Serial.print("Adresse IP Arduino: ");
  Serial.println(ip);
}