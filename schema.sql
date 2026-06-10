-- MineSecur (ISEP) - Schéma mis à jour selon le diagramme Drizzle
-- Note: 'SERIAL' en Drizzle/Postgres équivaut à 'BIGINT UNSIGNED NOT NULL AUTO_INCREMENT' en MySQL.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- 1. Table Actionneurs
CREATE TABLE IF NOT EXISTS actionneurs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type TEXT NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Table Capteurs (contient les seuils)
CREATE TABLE IF NOT EXISTS capteurs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type TEXT NOT NULL,
  actionneur BIGINT UNSIGNED NOT NULL,
  seuilmin DOUBLE NULL,
  seuilmax DOUBLE NULL,
  PRIMARY KEY (id),
  KEY idx_capteurs_actionneur (actionneur),
  CONSTRAINT fk_capteurs_actionneur FOREIGN KEY (actionneur) REFERENCES actionneurs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Table Captures (les relevés)
CREATE TABLE IF NOT EXISTS captures (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  idCapteur BIGINT UNSIGNED NOT NULL,
  date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  valeur DOUBLE NOT NULL,
  PRIMARY KEY (id),
  KEY idx_captures_capteur (idCapteur),
  CONSTRAINT fk_captures_capteur FOREIGN KEY (idCapteur) REFERENCES capteurs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Table Utilisateurs (ajout de password_hash pour Flask)
CREATE TABLE IF NOT EXISTS utilisateurs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NOT NULL, -- Nécessaire pour l'auth Python
  role ENUM('user', 'admin') NOT NULL DEFAULT 'user',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_utilisateurs_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Initialisation des données par défaut
INSERT INTO actionneurs (id, type) VALUES 
  (1, 'Buzzer Température'),
  (2, 'Buzzer Humidité'),
  (3, 'Buzzer Luminosité'),
  (4, 'Buzzer Présence'),
  (5, 'Buzzer CO2'),
  (6, 'Buzzer Méthane')
ON DUPLICATE KEY UPDATE type=VALUES(type);

INSERT INTO capteurs (id, type, actionneur, seuilmin, seuilmax) VALUES
  (1, 'temperature', 1, NULL, 35),
  (2, 'humidite', 2, NULL, 80),
  (3, 'lumiere', 3, 120, NULL),
  (4, 'presence', 4, NULL, 0),
  (5, 'co2', 5, NULL, 1000),
  (6, 'ch4', 6, NULL, 2)
ON DUPLICATE KEY UPDATE 
  type=VALUES(type), 
  actionneur=VALUES(actionneur), 
  seuilmin=VALUES(seuilmin), 
  seuilmax=VALUES(seuilmax);
