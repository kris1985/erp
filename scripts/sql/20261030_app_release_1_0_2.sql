-- 运营端发布 Android 生产包 1.0.2。
-- 安装包放到服务器 data/uploads/tyulan-1.0.2.apk，对外地址见 download_url。
-- 可重复执行：同一版本号只保留一条当前整包记录。

UPDATE `app_releases`
SET `is_current` = 0
WHERE `platform` = 'android'
  AND `kind` = 'native'
  AND `is_current` = 1
  AND `version_code` <> 102;

INSERT INTO `app_releases` (
  `platform`, `kind`, `version_name`, `version_code`, `download_url`,
  `notes`, `force_update`, `is_published`, `is_current`, `published_at`
)
SELECT
  'android', 'native', '1.0.2', 102,
  'https://tyulan.cn/uploads/tyulan-1.0.2.apk',
  'Android 生产包 1.0.2',
  0, 1, 1, NOW()
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM `app_releases`
  WHERE `platform` = 'android' AND `kind` = 'native' AND `version_code` = 102
);

UPDATE `app_releases`
SET
  `version_name` = '1.0.2',
  `download_url` = 'https://tyulan.cn/uploads/tyulan-1.0.2.apk',
  `notes` = 'Android 生产包 1.0.2',
  `force_update` = 0,
  `is_published` = 1,
  `is_current` = 1,
  `published_at` = NOW()
WHERE `platform` = 'android' AND `kind` = 'native' AND `version_code` = 102;
