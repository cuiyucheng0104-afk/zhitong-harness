-- W8 迁移：把旧库 project / project_file 导出为 JSON Lines，供 export-projects.py --json 读取。
-- 每行一个 JSON 对象，table 字段写表名；JSON_OBJECT 会把字符串里的换行、制表符转义，所以一行就是一条记录。
-- 用法见 runbook.md 第 3 步（mysql -N -B -r，口令取容器里的 $MYSQL_ROOT_PASSWORD）。只读：只有 SELECT。
-- 不导人名、电话等个人信息列；project 的金额、规模是旧系统登记值，迁移后标 needs_manual。
SELECT JSON_OBJECT(
  'table', 'project',
  'id', id, 'sys_company_code', sys_company_code, 'name', name, 'nature', nature, 'folder_path', folder_path,
  'eng_category', eng_category, 'project_node', project_node, 'report_code', report_code,
  'entrusted_company', entrusted_company, 'contract_begin_date', contract_begin_date,
  'contract_end_date', contract_end_date, 'scale', scale, 'scale_unit_code', scale_unit_code,
  'total_amount', total_amount, 'engineering_address', engineering_address,
  'del_flag', del_flag, 'create_time', create_time, 'modify_time', modify_time)
FROM project;
SELECT JSON_OBJECT(
  'table', 'project_file',
  'id', id, 'project_id', project_id, 'parent_id', parent_id,
  'relative_parent_folder', relative_parent_folder, 'disk_relative_parent_folder', disk_relative_parent_folder,
  'file_name', file_name, 'disk_file_name', disk_file_name, 'item_type', item_type, 'source', source,
  'suffix', suffix, 'file_info', file_info, 'sha256', sha256, 'history_list', history_list,
  'sys_company_code', sys_company_code, 'del_flag', del_flag, 'create_time', create_time, 'modify_time', modify_time)
FROM project_file;
