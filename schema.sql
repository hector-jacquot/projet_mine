-- MineSecur (ISEP) - Schéma MySQL compatible Drizzle (snake_case)
-- Note: Drizzle (TypeScript) gère vos migrations ; ce fichier sert de référence / initialisation.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS utilisateurs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('user','admin') NOT NULL DEFAULT 'user',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_utilisateurs_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS seuils_config (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  capteur_type VARCHAR(32) NOT NULL,
  seuil_min DOUBLE NULL,
  seuil_max DOUBLE NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_seuils_config_capteur_type (capteur_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mine_donnees (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  capteur_type VARCHAR(32) NOT NULL,
  valeur DOUBLE NOT NULL,
  zone VARCHAR(64) NULL,
  buzzer_on TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_mine_donnees_type_time (capteur_type, created_at),
  KEY idx_mine_donnees_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seuils par défaut (à ajuster via la page "Gestion")
INSERT INTO seuils_config (capteur_type, seuil_min, seuil_max) VALUES
  ('temperature', NULL, 35),
  ('humidite', NULL, 80),
  ('lumiere', 120, NULL),
  ('presence', NULL, 0),
  ('co2', NULL, 1000),
  ('ch4', NULL, 2)
ON DUPLICATE KEY UPDATE
  seuil_min = VALUES(seuil_min),
  seuil_max = VALUES(seuil_max);

