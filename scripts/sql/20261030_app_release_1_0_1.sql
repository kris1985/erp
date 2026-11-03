-- 运营端发布 Android 生产包 1.0.1。
-- 安装包放到服务器 data/uploads/tyulan-1.0.1.apk，对外地址见 download_url。
-- 可重复执行：同一版本号只保留一条当前整包记录。

CREATE TABLE IF NOT EXISTS `app_releases` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `platform` VARCHAR(16) NOT NULL DEFAULT 'android',
  `kind` VARCHAR(16) NOT NULL DEFAULT 'native',
  `version_name` VARCHAR(32) NOT NULL,
  `version_code` INT NOT NULL,
  `download_url` VARCHAR(500) NOT NULL DEFAULT '',
  `notes` TEXT NULL,
  `force_update` TINYINT(1) NOT NULL DEFAULT 0,
  `is_published` TINYINT(1) NOT NULL DEFAULT 1,
  `is_current` TINYINT(1) NOT NULL DEFAULT 1,
  `published_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `min_native_version_code` INT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_app_releases_platform_current` (`platform`, `is_current`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

UPDATE `app_releases`
SET `is_current` = 0
WHERE `platform` = 'android'
  AND `kind` = 'native'
  AND `is_current` = 1
  AND `version_code` <> 101;

INSERT INTO `app_releases` (
  `platform`, `kind`, `version_name`, `version_code`, `download_url`,
  `notes`, `force_update`, `is_published`, `is_current`, `published_at`
)
SELECT
  'android', 'native', '1.0.1', 101,
  'https://tyulan.cn/uploads/tyulan-1.0.1.apk',
  'Android 生产包 1.0.1',
  0, 1, 1, NOW()
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM `app_releases`
  WHERE `platform` = 'android' AND `kind` = 'native' AND `version_code` = 101
);

UPDATE `app_releases`
SET
  `version_name` = '1.0.1',
  `download_url` = 'https://tyulan.cn/uploads/tyulan-1.0.1.apk',
  `notes` = 'Android 生产包 1.0.1',
  `force_update` = 0,
  `is_published` = 1,
  `is_current` = 1,
  `published_at` = NOW()
WHERE `platform` = 'android' AND `kind` = 'native' AND `version_code` = 101;
