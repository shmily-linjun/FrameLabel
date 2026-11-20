-- ============================================================================
-- X-AnyLabeling 数据集数据库 schema v1（讨论稿 v0.12 资产）
-- 文件：<数据集根目录>/xanylabeling.db
-- 版本：PRAGMA user_version = 1（讨论稿阶段；正式迁移时按 §13.1 升版）
-- 规模：8 表 / 86 列 / 3 视图
-- 本轮变更（见 ../数据库设计-讨论稿.md §2.6）：
--   * D1  dataset.task（主任务提示，不限制数据用途）
--   * D6  image_file.author / author_modified_at（归属过渡列）
--   * D11 points_json 改为几何对象 {"schema_version":1,"outer":[...],"holes":[]}
--   * D16 rel_path 唯一索引使用 COLLATE NOCASE（一期 Windows）
--   * D17 移除 image_file.checked（改标签即核对；空图=未核对）
--   * D19 image_file.deleted_at（回收站；图片移入数据集内 .trash/）
-- 维护：本文件是讨论稿的 DDL 源，与 ../数据库设计-讨论稿.md §5 字段表及
--       本目录 demo.db / queries.sql / report.txt 同步维护。
-- 说明：
--   * 图片本体仍保存在文件系统；数据库只存标注与元数据。
--   * 一个数据库 = 一个数据集（dataset 表当前只有一行，为将来多数据集留位）。
--   * 所有时间戳为 UTC ISO-8601 文本（毫秒精度，形如 2026-11-11T10:00:00.000Z）。
--   * 所有 *_json 列存 JSON 文本，并由 json_valid() 约束。
--   * PRAGMA foreign_keys 不是持久设置，打开数据库的每个连接都必须执行。
--   * 几何格式版本随 schema 版本走（PRAGMA user_version），不另设几何版本列。
-- ============================================================================

PRAGMA user_version = 1;
-- 文件类型标识（'XALB' = 0x58414C42），防止把非本程序数据库当数据集打开
PRAGMA application_id = 1480674370;

-- ----------------------------------------------------------------------------
-- 0. 迁移记录（PRAGMA user_version 为主版本，此表只记录每次迁移的说明）
-- ----------------------------------------------------------------------------
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
    uuid        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL DEFAULT '',
    root_path   TEXT    NOT NULL DEFAULT '',   -- 空串=数据库文件所在目录；否则为绝对路径
    description TEXT    NOT NULL DEFAULT '',
    task        TEXT    NOT NULL DEFAULT '',   -- 主任务提示；不限制数据用途（det/seg/obb 可互转）
    app_version TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 2. 类别表（替代 .xanylabelingrc 的 labels / classes.txt / label_colors）
-- ----------------------------------------------------------------------------
CREATE TABLE category (
    id            INTEGER PRIMARY KEY,
    dataset_id    INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    color         TEXT,                          -- '#RRGGBB'
    sort_index    INTEGER NOT NULL DEFAULT 0,    -- 显示顺序，也是导出顺序权威（D7）
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
-- 3. 导入批次（只记录真实导入动作；同步/追加不建批次）
-- ----------------------------------------------------------------------------
CREATE TABLE import_session (
    id                INTEGER PRIMARY KEY,
    dataset_id        INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    source_format     TEXT    NOT NULL,
    source_path       TEXT    NOT NULL DEFAULT '',
    class_source      TEXT    NOT NULL DEFAULT '',
    options_json      TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(options_json)),
    category_map_json TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(category_map_json)),
    stats_json        TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    app_version       TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 4. 图片文件表（一行一张图片；图片本体在磁盘）
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
    split                TEXT    NOT NULL DEFAULT 'none'
                                 CHECK (split IN ('none', 'train', 'val', 'test')),
    description          TEXT    NOT NULL DEFAULT '',
    flags_json           TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(flags_json)),
    extra_json           TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)),
    author               TEXT    NOT NULL DEFAULT '',   -- 最后操作者（与 JSON author 同名同义）
    author_modified_at   TEXT    NOT NULL DEFAULT '',   -- 最后操作时间（ISO-8601）
    import_session_id    INTEGER REFERENCES import_session(id) ON DELETE SET NULL,
    imported_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    is_deleted           INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    deleted_at           TEXT CHECK (is_deleted = 1 OR deleted_at IS NULL),  -- 删除进回收站时间；未删必须为 NULL
    -- 来源标注文件快照（只读；原文件保持原位，不移动/不删除；可为空）
    source_label_path       TEXT,
    source_label_format     TEXT
);
-- Windows 文件系统大小写不敏感；一期只支持 Windows（D16）
CREATE UNIQUE INDEX ux_image_file_rel_path
    ON image_file(dataset_id, rel_path COLLATE NOCASE) WHERE is_deleted = 0;
CREATE INDEX ix_image_file_split   ON image_file(dataset_id, split) WHERE is_deleted = 0;
CREATE INDEX ix_image_file_session ON image_file(import_session_id);
CREATE INDEX ix_image_file_trash   ON image_file(dataset_id, deleted_at) WHERE is_deleted = 1;

-- ----------------------------------------------------------------------------
-- 5. 标注对象表（一行一个对象，原 shapes[] 元素）
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
    source_model     TEXT,
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
-- 6. 图片标签（原 tags[]，自由文本，不与类别绑定）
-- ----------------------------------------------------------------------------
CREATE TABLE image_tag (
    image_id   INTEGER NOT NULL REFERENCES image_file(id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,
    sort_index INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (image_id, tag)
) WITHOUT ROWID;
CREATE INDEX ix_image_tag_tag ON image_tag(tag);

-- ----------------------------------------------------------------------------
-- 7. 对象关系（原 relations[]；外键指向对象）
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
CREATE INDEX ix_relation_subject ON object_relation(subject_object_id);
CREATE INDEX ix_relation_object  ON object_relation(object_object_id);
CREATE UNIQUE INDEX ux_relation
    ON object_relation(image_id, subject_object_id, object_object_id, label);

-- ----------------------------------------------------------------------------
-- 8. 视图（口径封装，不是性能手段）
-- ----------------------------------------------------------------------------
CREATE VIEW v_image_summary AS
SELECT
    f.id            AS image_id,
    f.dataset_id,
    f.rel_path,
    f.file_name,
    f.split,
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

-- ----------------------------------------------------------------------------
-- 9. 首次建库种子（由程序在导入时写入；此处只示意，不自动执行）
-- ----------------------------------------------------------------------------
-- INSERT INTO dataset (uuid, name, task, app_version) VALUES (..., 'detect', ...);
-- INSERT INTO schema_migration (version, description) VALUES (1, '初始 schema：8 表 3 视图（v0.12）');
