-- W8 迁移：把旧库 knowledge_file 导出为 JSON Lines（追加到 export-rows.sql 的输出之后），用于还原知识库文件的显示名。
-- 旧库没有 knowledge_file 表（后端/sql/knowledge-file-schema-20260823.sql 未执行）时本语句报错，跳过即可：
-- relayout 会按磁盘名迁移知识库文件。只读：只有 SELECT。
SELECT JSON_OBJECT(
  'table', 'knowledge_file',
  'id', id, 'category_id', category_id,
  'relative_parent_folder', relative_parent_folder, 'disk_relative_parent_folder', disk_relative_parent_folder,
  'file_name', file_name, 'disk_file_name', disk_file_name, 'item_type', item_type, 'suffix', suffix,
  'file_info', file_info, 'sha256', sha256, 'history_list', history_list,
  'sys_company_code', sys_company_code, 'del_flag', del_flag)
FROM knowledge_file;
