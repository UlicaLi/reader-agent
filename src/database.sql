-- 文档表结构
-- 用于存储文档的基本信息和元数据

CREATE TABLE documents (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    uuid CHAR(36) NOT NULL COMMENT '唯一标识符',
    user_uuid CHAR(36) NOT NULL COMMENT '用户UUID',
    upload_uuid CHAR(36) NOT NULL COMMENT '上传UUID',
    filename VARCHAR(255) NOT NULL COMMENT '文件名',
    pages_num INT(11) NOT NULL DEFAULT 0 COMMENT '页数',
    file_ext VARCHAR(16) NOT NULL COMMENT '文件扩展名',
    file_size BIGINT NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
    md5_hash CHAR(32) NOT NULL COMMENT 'MD5 哈希',
    sha1_hash CHAR(40) NOT NULL COMMENT 'SHA1 哈希',
    bucket VARCHAR(64) NOT NULL COMMENT '存储桶',
    path VARCHAR(512) NOT NULL COMMENT '存储路径',
    summary TEXT NULL DEFAULT NULL COMMENT '摘要',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间',
);

-- 页面表结构
-- 用于存储文档的每个页面信息和内容

CREATE TABLE pages (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    uuid CHAR(36) NOT NULL COMMENT '唯一标识符',
    document_uuid CHAR(36) NOT NULL COMMENT '文档UUID',
    page_number INT(11) NOT NULL DEFAULT 1 COMMENT '页码',
    page_width INT(11) NOT NULL DEFAULT 0 COMMENT '页像素宽度',
    page_height INT(11) NOT NULL DEFAULT 0 COMMENT '页像素高度',
    markdown_content LONGTEXT NULL DEFAULT NULL COMMENT 'Markdown内容',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间', 
);

-- 块表结构
-- 用于存储文档页面中的文本块信息，支持语义搜索和内容分析

CREATE TABLE blocks (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    uuid CHAR(36) NOT NULL COMMENT '唯一标识符',
    document_uuid CHAR(36) NOT NULL COMMENT '文档UUID',
    page_uuid CHAR(36) NOT NULL COMMENT '页UUID',
    label VARCHAR(64) NULL DEFAULT NULL COMMENT '标签',
    content TEXT NULL DEFAULT NULL COMMENT '内容',
    font_size_px DECIMAL(5, 2) NULL DEFAULT NULL COMMENT '字体大小（单位：px）',
    bbox_left_ratio DECIMAL(10, 6) NULL DEFAULT NULL COMMENT '边界框左侧位置比例(%)',
    bbox_top_ratio DECIMAL(10, 6) NULL DEFAULT NULL COMMENT '边界框顶部位置比例(%)',
    bbox_width INT NULL DEFAULT NULL COMMENT '边界框宽度（单位：px）',
    bbox_height INT NULL DEFAULT NULL COMMENT '边界框高度（单位：px）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间',
);

-- 块翻译表结构
-- 用于存储块的翻译结果
CREATE TABLE translations (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    block_uuid CHAR(36) NOT NULL COMMENT '块UUID',
    lang VARCHAR(16) NOT NULL COMMENT '语言',
    content TEXT NULL DEFAULT NULL COMMENT '翻译内容',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间',
);

-- 块索引表结构
-- 用于存储文档的语义分块信息，支持向量检索和语义搜索

CREATE TABLE chunks (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    document_uuid CHAR(36) NOT NULL COMMENT '文档UUID',
    `index` INT(11) NOT NULL DEFAULT 0 COMMENT '块索引',
    content TEXT NULL DEFAULT NULL COMMENT '内容',
    meta JSON NULL DEFAULT NULL COMMENT '元数据',
    page_numbers VARCHAR(128) NULL DEFAULT NULL COMMENT '页码列表',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间',
);

-- 问题列表结构
-- 用于存储每个新对话的问题列表

CREATE TABLE questions (
    id BIGINT(20) NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    uuid CHAR(36) NOT NULL COMMENT '唯一标识符',
    user_uuid CHAR(36) NOT NULL COMMENT '用户UUID',
    document_uuid CHAR(36) NOT NULL COMMENT '文档UUID',
    question TEXT NULL DEFAULT NULL COMMENT '推荐问题',
    question_type VARCHAR(16) NOT NULL COMMENT '推荐问题类型',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    deleted_at DATETIME NULL DEFAULT NULL COMMENT '删除时间',
);

CREATE TABLE uploads (
  id bigint NOT NULL AUTO_INCREMENT,
  uuid varchar(36) NOT NULL,
  file_size bigint NOT NULL,
  file_ext varchar(10) NOT NULL,
  mime_type varchar(100) NOT NULL,
  md5_hash varchar(32) NOT NULL,
  sha1_hash varchar(40) NOT NULL,
  path varchar(500) NOT NULL,
  bucket varchar(100) NOT NULL,
  width int DEFAULT NULL,
  height int DEFAULT NULL,
  meta text,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
);