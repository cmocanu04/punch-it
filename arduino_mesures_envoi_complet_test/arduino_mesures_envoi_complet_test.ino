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

// --- MODIFIÉ: Configuration Autres Capteurs ---
const int forcePin1 = A0; // Flexiforce 1
const int forcePin2 = A1; // Flexiforce 2
const int forcePin3 = A2; // Flexiforce 3
const int forcePin4 = A3; // Flexiforce 4
const int flexPin = A6;   // Capteur de flexion (poignet)

// Variables pour stocker les tensions lues
float voltageFlex = 0.0;
float voltageForce1 = 0.0;
float voltageForce2 = 0.0;
float voltageForce3 = 0.0;
float voltageForce4 = 0.0;

// --- Timing & Compteur ---
unsigned long previousMillis = 0;
const long interval = 10; // Intervalle de 10ms
unsigned long messageCounter = 0;

// --- LED Intégrée ---
const int ledPin = LED_BUILTIN;

// Tension de référence de l'ADC (généralement 3.3V pour les MKR)
const float ADC_REFERENCE_VOLTAGE = 3.3;
const float ADC_MAX_VALUE = 1023.0; // Pour un ADC 10 bits

// ==============================================================================
// SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Démarrage du Gant de Boxe Connecté (avec lecture tensions)...");

  pinMode(ledPin, OUTPUT);
  digitalWrite(ledPin, LOW);

  // --- Initialisation WiFi ---
  Serial.println("Vérification module WiFi...");
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("ERREUR: Module WiFi non détecté !");
    while (true) { digitalWrite(ledPin, HIGH); delay(100); digitalWrite(ledPin, LOW); delay(100); }
  }
  Serial.println("Tentative de connexion au WiFi...");
  while (status != WL_CONNECTED) {
    Serial.print("Connexion à : "); Serial.println(ssid);
    status = WiFi.begin(ssid, pass);
    unsigned long startTime = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startTime < 10000) {
      digitalWrite(ledPin, HIGH); delay(250); digitalWrite(ledPin, LOW); delay(250); Serial.print(".");
    }
    status = WiFi.status();
    if (status != WL_CONNECTED) {
      Serial.println("\nÉchec. Nouvelle tentative dans 5s...");
      WiFi.disconnect(); digitalWrite(ledPin, LOW); delay(5000);
    }
  }
  Serial.println("\nConnecté au WiFi!");
  digitalWrite(ledPin, HIGH);
  printWifiStatus();

  // --- Initialisation IMU ---
  Serial.println("Initialisation de la centrale inertielle...");
  Wire.begin();
  if (myIMU.begin() != 0) {
    Serial.println("ERREUR: IMU !");
    while (true) { digitalWrite(ledPin, HIGH); delay(500); digitalWrite(ledPin, LOW); delay(500); }
  } else {
    Serial.println("Centrale inertielle OK.");
  }

  // --- Initialisation Autres Capteurs (pas de pinMode spécifique pour analogRead) ---
  Serial.println("Capteurs analogiques (Flexion, Force) prêts pour la lecture.");

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
    // IMU
    aX = myIMU.readFloatAccelX(); aY = myIMU.readFloatAccelY(); aZ = myIMU.readFloatAccelZ();
    gX = myIMU.readFloatGyroX(); gY = myIMU.readFloatGyroY(); gZ = myIMU.readFloatGyroZ();

    // Capteurs analogiques - Lecture brute puis conversion en tension
    int rawFlex = analogRead(flexPin);
    voltageFlex = rawFlex * (ADC_REFERENCE_VOLTAGE / ADC_MAX_VALUE);

    int rawForce1 = analogRead(forcePin1);
    voltageForce1 = rawForce1 * (ADC_REFERENCE_VOLTAGE / ADC_MAX_VALUE);

    int rawForce2 = analogRead(forcePin2);
    voltageForce2 = rawForce2 * (ADC_REFERENCE_VOLTAGE / ADC_MAX_VALUE);

    int rawForce3 = analogRead(forcePin3);
    voltageForce3 = rawForce3 * (ADC_REFERENCE_VOLTAGE / ADC_MAX_VALUE);

    int rawForce4 = analogRead(forcePin4);
    voltageForce4 = rawForce4 * (ADC_REFERENCE_VOLTAGE / ADC_MAX_VALUE);

    // --- 2. Formater les données ---
    messageCounter++;
    String dataString = "";
    dataString += String(messageCounter); dataString += ",";     // 1. SeqNum
    dataString += String(aX, 4); dataString += ",";              // 2. AccX
    dataString += String(aY, 4); dataString += ",";              // 3. AccY
    dataString += String(aZ, 4); dataString += ",";              // 4. AccZ
    dataString += String(gX, 3); dataString += ",";              // 5. GyroX (Roll si renommé)
    dataString += String(gY, 3); dataString += ",";              // 6. GyroY (Pitch si renommé)
    dataString += String(gZ, 3); dataString += ",";              // 7. GyroZ (Yaw si renommé)
    dataString += String(voltageFlex, 3); dataString += ",";    // 8. Tension Flexion (3 décimales)
    dataString += String(voltageForce1, 3); dataString += ",";  // 9. Tension Force1
    dataString += String(voltageForce2, 3); dataString += ",";  // 10. Tension Force2
    dataString += String(voltageForce3, 3); dataString += ",";  // 11. Tension Force3
    dataString += String(voltageForce4, 3);                     // 12. Tension Force4 (pas de virgule à la fin)

    // --- 3. Envoyer les données et Gérer la LED ---
    if (!client.connected()) {
      digitalWrite(ledPin, LOW);
      client.stop();
      if (client.connect(serverIp, serverPort)) {
        Serial.println("Reconnecté au serveur !");
        digitalWrite(ledPin, HIGH);
      } else {
        messageCounter--; // Ne pas compter ce message non envoyé
        return; 
      }
    }

    if (client.connected()) {
      client.println(dataString);
      digitalWrite(ledPin, HIGH);
      // Serial.println(dataString); // Décommentez pour voir aussi sur le moniteur série
    } else {
       digitalWrite(ledPin, LOW);
       messageCounter--;
    }
  }

  // Gestion de la LED si la connexion WiFi générale est perdue
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Connexion WiFi générale perdue !");
    digitalWrite(ledPin, HIGH); delay(750);
    digitalWrite(ledPin, LOW); delay(750);
  }
}

// ==============================================================================
// Fonctions Utilitaires
// ==============================================================================
void printWifiStatus() {
  Serial.print("SSID: "); Serial.println(WiFi.SSID());
  IPAddress ip = WiFi.localIP();
  Serial.print("Adresse IP Arduino: "); Serial.println(ip);
}