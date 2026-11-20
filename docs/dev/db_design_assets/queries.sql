-- ============================================================================
-- demo.db 查询示例（与 schema.sql v1 / 讨论稿 v0.13 的 8 表 86 列 3 视图对应）
-- 本目录随 docs/dev/数据库设计-讨论稿.md 保留，不是一次性临时文件。
-- 运行方式（仓库根目录，Windows；python -m sqlite3 需 Python 3.12+）：
--   python -m sqlite3 docs/dev/db_design_assets/demo.db ".read docs/dev/db_design_assets/queries.sql"
-- 或逐条复制到任意 SQLite 客户端（只读 SELECT，可直接执行）。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. 库结构与版本
-- ---------------------------------------------------------------------------
SELECT name, type FROM sqlite_master
 WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
 ORDER BY type, name;

PRAGMA user_version;
PRAGMA application_id;
PRAGMA journal_mode;

SELECT * FROM dataset;
SELECT * FROM schema_migration;

-- ---------------------------------------------------------------------------
-- 1. 文件列表常用字段（文件 / 对象数 / 划分 / 导入时间 / 尺寸 / 归属）
--    文件表另有“推理”“标签”两列，数据源见讨论稿 §6.4。
-- ---------------------------------------------------------------------------
SELECT
    f.rel_path                    AS 文件,
    COUNT(o.id)                   AS 对象数,
    f.split                       AS 划分,
    f.imported_at                 AS 导入时间,
    f.width || 'x' || f.height    AS 尺寸,
    f.editor                      AS 最后编辑者
FROM image_file f
LEFT JOIN annotation_object o
       ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0
GROUP BY f.id
ORDER BY f.rel_path;

-- 复用视图（少写 GROUP BY）
SELECT * FROM v_image_summary ORDER BY rel_path;

-- ---------------------------------------------------------------------------
-- 2. 统计页：类别 x split（口径 = “包含该类别的图片数”，与现有 UI 一致）
-- ---------------------------------------------------------------------------
SELECT
    category_name                        AS 类别,
    SUM(CASE WHEN split = 'train' THEN image_count ELSE 0 END) AS 训练,
    SUM(CASE WHEN split = 'val'   THEN image_count ELSE 0 END) AS 验证,
    SUM(CASE WHEN split = 'test'  THEN image_count ELSE 0 END) AS 测试,
    SUM(CASE WHEN split = 'none'  THEN image_count ELSE 0 END) AS 未划分,
    SUM(image_count)                     AS 合计
FROM v_category_split_stats
GROUP BY category_name
ORDER BY category_name;

-- 每个 split 的文件总数（统计表 Total 行）
SELECT split, COUNT(*) AS files FROM image_file
 WHERE is_deleted = 0 GROUP BY split ORDER BY split;

-- “无对象”图片（含无标注文件和空标注，口径与现有 UI 相同）
SELECT f.rel_path
FROM image_file f
WHERE f.is_deleted = 0
  AND NOT EXISTS (
      SELECT 1 FROM annotation_object o
       WHERE o.image_id = f.id AND o.is_deleted = 0
  )
ORDER BY f.rel_path;

-- ---------------------------------------------------------------------------
-- 3. 搜索语法 -> SQL（现有搜索字段：label/split/shape/type/gid/difficult/
--    review/score/description + 文件名子串；AND=',' OR='|' NOT='!'；
--    `#N` 已废弃，文件名正则留在应用层，见讨论稿 §2.6-D14）
-- ---------------------------------------------------------------------------

-- 3.1 label::crack,split::train
SELECT f.rel_path
FROM image_file f
WHERE f.is_deleted = 0
  AND f.split = 'train'
  AND EXISTS (
      SELECT 1 FROM annotation_object o
      JOIN category c ON c.id = o.category_id
      WHERE o.image_id = f.id AND o.is_deleted = 0 AND c.name = 'crack'
  );

-- 3.2 label::crack|rust  （任意一个类别）
SELECT f.rel_path
FROM image_file f
WHERE f.is_deleted = 0
  AND EXISTS (
      SELECT 1 FROM annotation_object o
      JOIN category c ON c.id = o.category_id
      WHERE o.image_id = f.id AND o.is_deleted = 0
        AND c.name IN ('crack', 'rust')
  );

-- 3.3 shape::1 （有对象） / shape::0 （无对象）
SELECT rel_path, object_count FROM v_image_summary
 WHERE object_count > 0;

-- 3.4 type::rotation,split::test
SELECT f.rel_path
FROM image_file f
WHERE f.is_deleted = 0 AND f.split = 'test'
  AND EXISTS (
      SELECT 1 FROM annotation_object o
      WHERE o.image_id = f.id AND o.is_deleted = 0
        AND o.shape_type = 'rotation'
  );

-- 3.5 gid::0 （组号）
SELECT f.rel_path, COUNT(*) AS n
FROM image_file f
JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0 AND o.group_id = 0
GROUP BY f.id;

-- 3.6 difficult::1
SELECT DISTINCT f.rel_path
FROM image_file f
JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0 AND o.difficult = 1;

-- 3.7 review::false_positive
SELECT DISTINCT f.rel_path, o.review_status
FROM image_file f
JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0 AND o.review_status = 'false_positive';

-- 3.8 score::[0.5,1.0]
SELECT DISTINCT f.rel_path
FROM image_file f
JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0 AND o.score BETWEEN 0.5 AND 1.0;

-- 3.9 description::1 （图片或对象有描述）
SELECT DISTINCT f.rel_path
FROM image_file f
LEFT JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
WHERE f.is_deleted = 0
  AND (TRIM(f.description) <> '' OR TRIM(COALESCE(o.description, '')) <> '');

-- 3.10 文件名子串（原搜索的裸文本行为）
SELECT rel_path FROM image_file
 WHERE is_deleted = 0 AND file_name LIKE '%plate%';

-- ---------------------------------------------------------------------------
-- 4. 类别表 / 训练类别清单
-- ---------------------------------------------------------------------------
-- 4.1 类别及使用量
SELECT c.name, c.sort_index, c.in_class_list, c.color,
       (SELECT COUNT(*) FROM annotation_object o
         WHERE o.category_id = c.id AND o.is_deleted = 0) AS objects
FROM category c
WHERE c.dataset_id = 1 AND c.is_deleted = 0
ORDER BY c.sort_index;

-- 4.2 训练类别（YOLO/COCO 导出的 class_index 依据）
SELECT sort_index AS class_index, name
FROM category
WHERE dataset_id = 1 AND is_deleted = 0 AND in_class_list = 1
ORDER BY sort_index;

-- 4.3 不在训练类别清单中的标注类别（只标注、不训练）
SELECT c.name, COUNT(o.id) AS objects
FROM category c
LEFT JOIN annotation_object o ON o.category_id = c.id AND o.is_deleted = 0
WHERE c.dataset_id = 1 AND c.is_deleted = 0 AND c.in_class_list = 0
GROUP BY c.id;

-- ---------------------------------------------------------------------------
-- 5. 对象明细 / 关系 / 来源
-- ---------------------------------------------------------------------------
SELECT * FROM v_object_detail ORDER BY image_id, sort_index;

-- 关系（原 JSON relations：subject_id/object_id/label/score）
SELECT f.rel_path,
       sc.name AS subject_category,
       oc.name AS object_category,
       r.label, r.score
FROM object_relation r
JOIN annotation_object so ON so.id = r.subject_object_id
JOIN annotation_object oo ON oo.id = r.object_object_id
JOIN category sc ON sc.id = so.category_id
JOIN category oc ON oc.id = oo.category_id
JOIN image_file f ON f.id = r.image_id;

-- 自动标注/模型结果（score 非空）
SELECT f.rel_path, c.name, o.shape_type, o.score, o.source, o.source_model
FROM annotation_object o
JOIN image_file f ON f.id = o.image_id
JOIN category c ON c.id = o.category_id
WHERE o.is_deleted = 0 AND o.score IS NOT NULL
ORDER BY o.score DESC;

-- 导入批次（来源可追溯）
SELECT id, source_format, source_path, class_source, stats_json, category_map_json
FROM import_session ORDER BY id;

-- ---------------------------------------------------------------------------
-- 6. JSON 字段查询（SQLite JSON1）
-- ---------------------------------------------------------------------------
-- 6.1 顶点数 / 孔洞数 / 首点坐标（几何对象：schema_version/outer/holes）
SELECT f.rel_path, c.name, o.shape_type,
       json_array_length(o.points_json, '$.outer') AS n_points,
       json_array_length(o.points_json, '$.holes') AS n_holes,
       json_extract(o.points_json, '$.outer[0][0]') AS x0,
       json_extract(o.points_json, '$.outer[0][1]') AS y0
FROM annotation_object o
JOIN image_file f ON f.id = o.image_id
JOIN category c ON c.id = o.category_id
WHERE o.is_deleted = 0
ORDER BY f.rel_path, o.sort_index;

-- 6.2 带属性的对象
SELECT f.rel_path, c.name, o.attributes_json
FROM annotation_object o
JOIN image_file f ON f.id = o.image_id
JOIN category c ON c.id = o.category_id
WHERE o.is_deleted = 0 AND o.attributes_json <> '{}';

-- 6.3 图片级 flags / 未知扩展字段
SELECT rel_path,
       json_extract(flags_json, '$.blurry') AS blurry,
       extra_json
FROM image_file
WHERE flags_json <> '{}' OR extra_json <> '{}';

-- 6.4 来源标注文件快照（导入时记录；原文件保持原位且导入后不再读取）
--     格式可能是 json / xml / txt，所以列名统一叫 source_label_*
SELECT rel_path, source_label_path, source_label_format
FROM image_file
WHERE source_label_path IS NOT NULL
ORDER BY rel_path;

-- ---------------------------------------------------------------------------
-- 7. 导出准备：按图片聚合标注（程序侧再按格式转换）
-- ---------------------------------------------------------------------------
-- 7.1 YOLO hbb/seg/obb 的输入（类别顺序 + 几何）
SELECT f.rel_path, f.width, f.height,
       c.sort_index AS class_index, c.name AS class_name,
       o.shape_type, o.points_json, o.difficult
FROM image_file f
JOIN annotation_object o ON o.image_id = f.id AND o.is_deleted = 0
JOIN category c ON c.id = o.category_id
WHERE f.is_deleted = 0 AND c.in_class_list = 1
ORDER BY f.rel_path, o.sort_index;

-- 7.2 仅导出有对象的图片（对应“跳过空标注”；按复核状态跳过已随 D17 移除）
SELECT f.rel_path
FROM image_file f
WHERE f.is_deleted = 0
  AND EXISTS (
      SELECT 1 FROM annotation_object o
       WHERE o.image_id = f.id AND o.is_deleted = 0
  );

-- ---------------------------------------------------------------------------
-- 8. 写操作示例（事务；实际由服务层封装，不要手改库）
-- ---------------------------------------------------------------------------
-- 8.1 修改划分
-- BEGIN;
-- UPDATE image_file SET split = 'val', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
--  WHERE rel_path = 'images/steel_plate_001.jpg' AND is_deleted = 0;
-- COMMIT;

-- 8.2 类别改名（对象自动跟随，无需批量改组）
-- BEGIN;
-- UPDATE category SET name = 'crack_wide', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
--  WHERE dataset_id = 1 AND name = 'crack' AND is_deleted = 0;
-- COMMIT;

-- 8.3 软删除一个对象（保留历史，不物理删除）
-- BEGIN;
-- UPDATE annotation_object SET is_deleted = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
--  WHERE uuid = '<object-uuid>';
-- COMMIT;

-- 8.4 替换某图对象（应用保存时应在同一事务内完成：删旧 + 插新 + 重建关系）
-- BEGIN;
-- DELETE FROM object_relation WHERE image_id = 2;
-- DELETE FROM annotation_object WHERE image_id = 2;
-- -- INSERT ... （应用代码）
-- COMMIT;

-- 8.5 回收站（D19）：删除文件 = 软删库行 + 图片移入 .trash/；恢复 = 移回 + 置 0
-- 删除（程序同时把图片移到 <数据集根>/.trash/<image_id>/）
-- BEGIN;
-- UPDATE image_file
--    SET is_deleted = 1,
--        deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
--        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
--  WHERE rel_path = 'images/steel_plate_001.jpg' AND is_deleted = 0;
-- COMMIT;

-- 恢复（程序把图片移回原 rel_path）
-- BEGIN;
-- UPDATE image_file
--    SET is_deleted = 0, deleted_at = NULL,
--        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
--  WHERE id = 3 AND is_deleted = 1;
-- COMMIT;

-- 回收站列表
SELECT id, rel_path, deleted_at, editor
FROM image_file
WHERE is_deleted = 1
ORDER BY deleted_at DESC;

-- 清空回收站（物理删除库行；程序同时删除 .trash/ 下的文件）
-- DELETE FROM image_file WHERE is_deleted = 1 AND deleted_at < '2026-01-01T00:00:00.000Z';

-- ---------------------------------------------------------------------------
-- 9. 完整性与维护
-- ---------------------------------------------------------------------------
PRAGMA integrity_check;
PRAGMA foreign_key_check;

-- 一致性检查：孤儿对象 / 跨图关系 / 重复类别名 / 悬空关系
SELECT 'orphan_object' AS issue, o.id FROM annotation_object o
 LEFT JOIN image_file f ON f.id = o.image_id
 WHERE o.is_deleted = 0 AND f.id IS NULL
UNION ALL
SELECT 'cross_image_relation', r.id FROM object_relation r
 JOIN annotation_object s ON s.id = r.subject_object_id
 JOIN annotation_object t ON t.id = r.object_object_id
 WHERE s.image_id <> r.image_id OR t.image_id <> r.image_id;

-- 备份：SQLite 在线安全备份（不覆盖原库）
-- VACUUM INTO '<目标目录>/demo_backup.db';

-- WAL 检查点（关闭前/打包备份前）
-- PRAGMA wal_checkpoint(TRUNCATE);


