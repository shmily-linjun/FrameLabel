-- ============================================================================
-- X-AnyLabeling 数据集数据库 schema v1（讨论稿资产，尚未接入软件代码）
-- 文件：<数据集根目录>/xanylabeling.db
-- 版本：PRAGMA user_version = 1
-- 维护：本文件是讨论稿的 DDL 源，与 ../数据库设计-讨论稿.md §6 字段表
--       及本目录 demo.db 同步维护；改动后运行 check_doc_vs_db.py 校验。
-- 说明：
--   * 图片本体仍保存在文件系统；数据库只存标注与元数据。
--   * 一个数据库 = 一个数据集（dataset 表当前只有一行，为将来多数据集留位）。
--   * 所有时间戳为 UTC ISO-8601 文本（毫秒精度，形如 2026-11-11T10:00:00.000Z）。
--   * 所有 *_json 列存放 JSON 文本，并用 json_valid() 约束。
--   * PRAGMA foreign_keys 不是持久设置，打开数据库的每个连接都必须执行。
-- ============================================================================

PRAGMA user_version = 1;
-- 文件类型标识（'XALB' = 0x58414C42），防止误把非本程序数据库当成数据集打开
PRAGMA application_id = 1480674370;

-- ----------------------------------------------------------------------------
-- 0. 库级元信息
-- ----------------------------------------------------------------------------
CREATE TABLE db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

-- 有序迁移记录（PRAGMA user_version 为主版本，此表记录每次迁移的说明）
CREATE TABLE schema_migration (
    version     INTEGER PRIMARY KEY,
    description TEXT    NOT NULL DEFAULT '',
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 1. 数据集（当前一个库一行；多数据集可作为将来的库级目录扩展）
-- ----------------------------------------------------------------------------
CREATE TABLE dataset (
    id          INTEGER PRIMARY KEY,
    uuid        TEXT    NOT NULL UNIQUE,   -- 对外稳定身份（未来项目包/跨库合并用；库内连接仍用整数 id）
    name        TEXT    NOT NULL DEFAULT '',
    root_path   TEXT    NOT NULL DEFAULT '',   -- 空串=数据库文件所在目录；否则为绝对路径
    description TEXT    NOT NULL DEFAULT '',
    app_version TEXT    NOT NULL DEFAULT '',   -- 最近写入本库的软件版本（诊断用）
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 2. 类别表（替代 .xanylabelingrc 的 labels / classes.txt / label_colors）
--    * 名称是标注事实，重命名直接 UPDATE，行 id 不变。
--    * in_class_list 表示是否在“当前类别清单”中；删除类别清单条目只改此列，
--      不删行，历史对象仍然有效（软删除由 is_deleted 表达）。
--    * sort_index 即类别顺序（YOLO/COCO 导出的 class_index 顺序）。
-- ----------------------------------------------------------------------------
CREATE TABLE category (
    id            INTEGER PRIMARY KEY,
    dataset_id    INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    group_name    TEXT,                          -- 类别分组（平台方向预留）
    color         TEXT,                          -- '#RRGGBB'，替代 config.label_colors
    sort_index    INTEGER NOT NULL DEFAULT 0,
    in_class_list INTEGER NOT NULL DEFAULT 1 CHECK (in_class_list IN (0, 1)),
    description   TEXT    NOT NULL DEFAULT '',
    is_deleted    INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX ux_category_name
    ON category(dataset_id, name) WHERE is_deleted = 0;
CREATE INDEX ix_category_sort ON category(dataset_id, sort_index);

-- ----------------------------------------------------------------------------
-- 3. 导入批次（替代“无来源追溯”的现状；支持幂等重导与排障）
-- ----------------------------------------------------------------------------
CREATE TABLE import_session (
    id                INTEGER PRIMARY KEY,
    dataset_id        INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    source_format     TEXT    NOT NULL,        -- 例：xlabel-json / coco:det / yolo:hbb / voc:det / dota / mask / mot / odvg / ppocr:rec / labelme-json / labelimg-voc
    source_path       TEXT    NOT NULL DEFAULT '',
    class_source      TEXT    NOT NULL DEFAULT '',  -- classes.txt / COCO categories / 内置
    options_json      TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(options_json)),
    category_map_json TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(category_map_json)),
    stats_json        TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    app_version       TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 4. 文件表（替代“图片 + 同名 .json + .xanylabeling_import_time.json”）
--    * rel_path 相对 dataset.root_path，统一使用 '/'；数据库可整体搬移。
--    * width/height 为应用 EXIF 显示方向后的尺寸（画布坐标系）；原图文件是尺寸
--      唯一权威，若需排障再读文件，不在库里存第二份。
--    * 图片本体不入库（BLOB 会让 SQLite 备份/搬移/读取变差，且制造第二事实源）。
--    * checked 三态：unchecked / passed / failed（对应原 bool / "failed"）。
--    * flags_json / extra_json 保存图片级 flags 与未知顶层键（chat_history、
--      vqaData、text 等），保证与旧 JSON 无损往返。
--    * 来源标注文件快照列（source_label_*）统一放在表末尾：它们可能不存在，
--      也可能不是 JSON（LabelImg 是 XML、YOLO 是 TXT），因此不叫 json 列。
-- ----------------------------------------------------------------------------
CREATE TABLE image_file (
    id                   INTEGER PRIMARY KEY,
    dataset_id           INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    rel_path             TEXT    NOT NULL,
    file_name            TEXT    NOT NULL,
    ext                  TEXT    NOT NULL DEFAULT '',
    width                INTEGER,
    height               INTEGER,
    size_bytes           INTEGER,
    mtime_ns             INTEGER,
    sha256               TEXT,                   -- 可选：跨库/去重/完整性校验的图片身份
    media_type           TEXT    NOT NULL DEFAULT 'image'
                                 CHECK (media_type IN ('image', 'video_frame', 'pointcloud')),
    split                TEXT    NOT NULL DEFAULT 'none'
                                 CHECK (split IN ('none', 'train', 'val', 'test')),
    checked              TEXT    NOT NULL DEFAULT 'unchecked'
                                 CHECK (checked IN ('unchecked', 'passed', 'failed')),
    description          TEXT    NOT NULL DEFAULT '',
    flags_json           TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(flags_json)),
    extra_json           TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)),
    import_session_id    INTEGER REFERENCES import_session(id) ON DELETE SET NULL,
    imported_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    is_deleted           INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    -- 来源标注文件快照（只读；原文件保持原位，不移动/不删除；可为空）
    source_label_path       TEXT,                -- 例：images/001.json / images/001.xml / labels/001.txt
    source_label_format     TEXT,                -- xlabel-json / labelme-json / voc-xml / yolo-txt …
    source_label_sha256     TEXT,                -- 导入时内容哈希，用于发现“导入后被外部改动”
    source_label_mtime_ns   INTEGER              -- 导入时修改时间
);
CREATE UNIQUE INDEX ux_image_file_rel_path
    ON image_file(dataset_id, rel_path) WHERE is_deleted = 0;
CREATE INDEX ix_image_file_split   ON image_file(dataset_id, split) WHERE is_deleted = 0;
CREATE INDEX ix_image_file_checked ON image_file(dataset_id, checked) WHERE is_deleted = 0;
CREATE INDEX ix_image_file_session ON image_file(import_session_id);

-- ----------------------------------------------------------------------------
-- 5. 图片标签（替代 JSON 顶层 "tags": [...] 数组）
-- ----------------------------------------------------------------------------
CREATE TABLE image_tag (
    image_id   INTEGER NOT NULL REFERENCES image_file(id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,
    sort_index INTEGER NOT NULL DEFAULT 0,   -- 保持原 tags[] 的显示顺序
    PRIMARY KEY (image_id, tag)
) WITHOUT ROWID;
CREATE INDEX ix_image_tag_tag ON image_tag(tag);

-- ----------------------------------------------------------------------------
-- 6. 对象表（替代原 JSON 的 shapes[]，一行 = 一个 Shape）
--    * uuid 是稳定标识；有 relation 的旧 shape_id 直接复用为 uuid。
--    * points_json 只存几何顶点 [[x,y],...]；类别在 category_id 列，方向在
--      direction 列；shape 级未知字段（cuboid3d、visible、text…）进 extra_json。
--    * score 为模型置信度；review_status 对应原 other_data.review_status。
--    * source 记录来源（manual / auto_labeling / imported:coco …），
--      解决现状“导入后无法追溯来源格式”的问题。
-- ----------------------------------------------------------------------------
CREATE TABLE annotation_object (
    id               INTEGER PRIMARY KEY,
    uuid             TEXT    NOT NULL UNIQUE,
    image_id         INTEGER NOT NULL REFERENCES image_file(id) ON DELETE CASCADE,
    category_id      INTEGER NOT NULL REFERENCES category(id),
    shape_type       TEXT    NOT NULL
                             CHECK (shape_type IN ('rectangle', 'rotation',
                                                   'quadrilateral', 'polygon',
                                                   'point', 'line', 'linestrip',
                                                   'circle', 'cuboid')),
    sort_index       INTEGER NOT NULL DEFAULT 0,   -- 原 shapes[] 顺序
    points_json      TEXT    NOT NULL CHECK (json_valid(points_json)),
    score            REAL,
    group_id         INTEGER,
    difficult        INTEGER NOT NULL DEFAULT 0 CHECK (difficult IN (0, 1)),
    direction        REAL,                          -- rotation 的弧度（原 direction）
    description      TEXT    NOT NULL DEFAULT '',
    review_status    TEXT    NOT NULL DEFAULT 'pending'
                             CHECK (review_status IN ('pending', 'missed', 'false_positive')),
    source           TEXT    NOT NULL DEFAULT 'manual',
    source_model     TEXT,                          -- 自动标注时的模型名
    attributes_json  TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(attributes_json)),
    flags_json       TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(flags_json)),
    kie_linking_json TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(kie_linking_json)),
    extra_json       TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    is_deleted       INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1))
);
CREATE INDEX ix_object_image    ON annotation_object(image_id) WHERE is_deleted = 0;
CREATE INDEX ix_object_category ON annotation_object(category_id) WHERE is_deleted = 0;
CREATE INDEX ix_object_type     ON annotation_object(shape_type) WHERE is_deleted = 0;
CREATE INDEX ix_object_review   ON annotation_object(review_status) WHERE is_deleted = 0;
CREATE INDEX ix_object_score    ON annotation_object(score);

-- ----------------------------------------------------------------------------
-- 7. 对象间关系（替代 JSON 顶层 "relations": [{subject_id,object_id,label,score}]）
-- ----------------------------------------------------------------------------
CREATE TABLE object_relation (
    id                INTEGER PRIMARY KEY,
    image_id          INTEGER NOT NULL REFERENCES image_file(id) ON DELETE CASCADE,
    subject_object_id INTEGER NOT NULL REFERENCES annotation_object(id) ON DELETE CASCADE,
    object_object_id  INTEGER NOT NULL REFERENCES annotation_object(id) ON DELETE CASCADE,
    label             TEXT    NOT NULL,
    score             REAL,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX ux_relation
    ON object_relation(image_id, subject_object_id, object_object_id, label);
CREATE INDEX ix_relation_subject ON object_relation(subject_object_id);
CREATE INDEX ix_relation_object  ON object_relation(object_object_id);

-- ----------------------------------------------------------------------------
-- 8. 标记定义（可选支撑表；替代 config.flags / label_flags 的“仅内存”）
--    值仍存 image_file.flags_json / annotation_object.flags_json。
-- ----------------------------------------------------------------------------
CREATE TABLE flag_def (
    id         INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    scope      TEXT    NOT NULL CHECK (scope IN ('image', 'label')),
    name       TEXT    NOT NULL,
    sort_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE (dataset_id, scope, name)
);

-- ----------------------------------------------------------------------------
-- 9. 对象属性定义（可选支撑表；替代“上传 attributes JSON 只存内存、重启丢失”）
--    注意：这不是“dataset 自己的属性”。dataset 表存数据集自身字段（名称/根路径）；
--    本表存“某类别的对象可以有哪些属性”的表单模板（如 crack 的 severity 只能是
--    minor/major），具体取值存 annotation_object.attributes_json。
--    数据集归属由 category 隐含，不再重复存 dataset_id。
-- ----------------------------------------------------------------------------
CREATE TABLE attribute_def (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    widget_type  TEXT    NOT NULL DEFAULT 'select',
    options_json TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(options_json)),
    sort_index   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category_id, name)
);

-- ============================================================================
-- 常用视图：供文件列表、统计页与搜索使用
-- ============================================================================

-- 文件 + 对象数（文件列表“对象”列、统计页“无对象”判定）
CREATE VIEW v_image_summary AS
SELECT
    f.id            AS image_id,
    f.dataset_id,
    f.rel_path,
    f.file_name,
    f.split,
    f.checked,
    f.imported_at,
    f.updated_at,
    COUNT(o.id)     AS object_count,
    GROUP_CONCAT(DISTINCT c.name) AS category_names
FROM image_file f
LEFT JOIN annotation_object o
       ON o.image_id = f.id AND o.is_deleted = 0
LEFT JOIN category c
       ON c.id = o.category_id
WHERE f.is_deleted = 0
GROUP BY f.id;

-- 对象明细（加载图片/导出/搜索用）
CREATE VIEW v_object_detail AS
SELECT
    o.id            AS object_id,
    o.uuid          AS object_uuid,
    f.id            AS image_id,
    f.rel_path,
    c.id            AS category_id,
    c.name          AS category_name,
    o.shape_type,
    o.sort_index,
    o.points_json,
    o.score,
    o.group_id,
    o.difficult,
    o.direction,
    o.description,
    o.review_status,
    o.source,
    o.attributes_json
FROM annotation_object o
JOIN image_file f ON f.id = o.image_id AND f.is_deleted = 0
JOIN category  c ON c.id = o.category_id
WHERE o.is_deleted = 0;

-- 统计页：类别 × split 的“包含该类别的图片数”（与现有 UI 口径一致）
CREATE VIEW v_category_split_stats AS
SELECT
    c.dataset_id,
    c.id                         AS category_id,
    c.name                       AS category_name,
    f.split,
    COUNT(DISTINCT f.id)         AS image_count,
    COUNT(o.id)                  AS object_count
FROM category c
JOIN annotation_object o
     ON o.category_id = c.id AND o.is_deleted = 0
JOIN image_file f
     ON f.id = o.image_id AND f.is_deleted = 0
WHERE c.is_deleted = 0
GROUP BY c.id, f.split;
