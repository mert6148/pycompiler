-- MySQL / MariaDB schema for program storage and revision history.
-- Run this script in phpMyAdmin or a MySQL-compatible client.
-- The current PyCompiler frontend does not connect to this database; a backend
-- API is required before the UI can save or load programs.
-- This script is for a new installation. CREATE TABLE IF NOT EXISTS does not
-- migrate tables that were created by an older version of this script.

CREATE DATABASE IF NOT EXISTS `pycompiler`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `pycompiler`;

CREATE TABLE IF NOT EXISTS `compiler_programs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(150) NOT NULL,
    `source_type` VARCHAR(20) NOT NULL DEFAULT 'pycompiler',
    `source_code` MEDIUMTEXT NOT NULL,
    `target_language` VARCHAR(20) NOT NULL DEFAULT 'python',
    `generated_code` MEDIUMTEXT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_compiler_programs_target_language` (`target_language`),
    KEY `idx_compiler_programs_updated_at` (`updated_at`)
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `compiler_programs_history` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `compiler_program_id` BIGINT UNSIGNED NOT NULL,
    `name` VARCHAR(150) NOT NULL,
    `source_type` VARCHAR(20) NOT NULL DEFAULT 'pycompiler',
    `source_code` MEDIUMTEXT NOT NULL,
    `target_language` VARCHAR(20) NOT NULL DEFAULT 'python',
    `generated_code` MEDIUMTEXT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_program_history_program_created`
        (`compiler_program_id`, `created_at`),
    CONSTRAINT `fk_program_history_program`
        FOREIGN KEY (`compiler_program_id`)
        REFERENCES `compiler_programs` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `compiler_programs_history_diff` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `compiler_program_history_id` BIGINT UNSIGNED NOT NULL,
    `diff` MEDIUMTEXT NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_program_history_diff_history_created`
        (`compiler_program_history_id`, `created_at`),
    CONSTRAINT `fk_program_history_diff_history`
        FOREIGN KEY (`compiler_program_history_id`)
        REFERENCES `compiler_programs_history` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `compiler_programs_history_diff_files` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `compiler_program_history_diff_id` BIGINT UNSIGNED NOT NULL,
    `file_name` VARCHAR(255) NOT NULL,
    `diff` MEDIUMTEXT NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_program_history_diff_files_diff`
        (`compiler_program_history_diff_id`),
    CONSTRAINT `fk_program_history_diff_files_diff`
        FOREIGN KEY (`compiler_program_history_diff_id`)
        REFERENCES `compiler_programs_history_diff` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
