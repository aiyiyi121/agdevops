"""
SQL 语法检查规则引擎
纯 Python 实现，检测常见 SQL 安全和规范问题。
"""
import re


class CheckItem:
    """单条检查结果"""
    def __init__(self, level, rule_name, message, line_no=None):
        self.level = level          # error / warning / info
        self.rule_name = rule_name
        self.message = message
        self.line_no = line_no

    def to_dict(self):
        return {
            'level': self.level,
            'rule_name': self.rule_name,
            'message': self.message,
            'line_no': self.line_no,
        }


def check_sql(sql_content, sql_type='DML'):
    """
    对 SQL 文本进行语法/安全检查。
    返回 CheckItem 列表。
    """
    results = []
    # 按分号切分多条语句
    statements = _split_statements(sql_content)

    for idx, stmt in enumerate(statements, 1):
        stmt_stripped = stmt.strip()
        if not stmt_stripped:
            continue

        upper = stmt_stripped.upper()

        # —— 通用规则 ——
        # 1. 禁止无 WHERE 的 DELETE
        if upper.startswith('DELETE') and 'WHERE' not in upper:
            results.append(CheckItem(
                'error', 'NO_WHERE_DELETE',
                f'语句 #{idx}: DELETE 语句缺少 WHERE 条件，可能删除全表数据',
                line_no=idx,
            ))

        # 2. 禁止无 WHERE 的 UPDATE
        if upper.startswith('UPDATE') and 'WHERE' not in upper:
            results.append(CheckItem(
                'error', 'NO_WHERE_UPDATE',
                f'语句 #{idx}: UPDATE 语句缺少 WHERE 条件，可能更新全表数据',
                line_no=idx,
            ))

        # 3. 检测 SELECT *
        if re.search(r'\bSELECT\s+\*', upper):
            results.append(CheckItem(
                'warning', 'SELECT_STAR',
                f'语句 #{idx}: 建议指定具体列名，避免使用 SELECT *',
                line_no=idx,
            ))

        # 4. INSERT 无显式列名
        if upper.startswith('INSERT') and re.search(r'INSERT\s+INTO\s+\S+\s+VALUES', upper):
            results.append(CheckItem(
                'warning', 'INSERT_NO_COLUMNS',
                f'语句 #{idx}: INSERT 语句建议指定目标列名',
                line_no=idx,
            ))

        # 5. 禁止 TRUNCATE
        if upper.startswith('TRUNCATE'):
            results.append(CheckItem(
                'error', 'TRUNCATE_TABLE',
                f'语句 #{idx}: TRUNCATE TABLE 操作风险极高，建议使用 DELETE 并添加 WHERE 条件',
                line_no=idx,
            ))

        # 6. 禁止 DROP TABLE (DML 模式下)
        if sql_type == 'DML' and upper.startswith('DROP'):
            results.append(CheckItem(
                'error', 'DROP_IN_DML',
                f'语句 #{idx}: DML 工单中不允许 DROP 操作，请提交 DDL 工单',
                line_no=idx,
            ))

        # 7. DDL 表名规范
        if sql_type == 'DDL' and upper.startswith('CREATE TABLE'):
            table_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?(\w+)[`"]?', upper)
            if table_match:
                table_name = table_match.group(1)
                if not re.match(r'^[a-z][a-z0-9_]*$', table_name, re.IGNORECASE):
                    results.append(CheckItem(
                        'warning', 'TABLE_NAME_CONVENTION',
                        f'语句 #{idx}: 表名 "{table_name}" 建议使用字母开头的小写 + 下划线命名',
                        line_no=idx,
                    ))

        # 8. 超长 SQL 警告
        if len(stmt_stripped) > 10000:
            results.append(CheckItem(
                'warning', 'SQL_TOO_LONG',
                f'语句 #{idx}: SQL 长度超过 10000 字符，建议拆分',
                line_no=idx,
            ))

        # 9. 检查是否包含注释型注入模式
        if re.search(r';\s*--', stmt_stripped) or re.search(r'/\*.*\*/', stmt_stripped):
            results.append(CheckItem(
                'info', 'COMMENT_PATTERN',
                f'语句 #{idx}: 检测到注释模式，请确认是否为预期内容',
                line_no=idx,
            ))

    # 如果全部通过
    if not results:
        results.append(CheckItem(
            'info', 'ALL_PASSED',
            '所有检查项已通过',
        ))

    return results


def _split_statements(sql_content):
    """
    按分号切分 SQL 语句，简单实现。
    忽略字符串内的分号。
    """
    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False

    for char in sql_content:
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == ';' and not in_single_quote and not in_double_quote:
            statements.append(''.join(current))
            current = []
            continue
        current.append(char)

    # 最后一条
    remaining = ''.join(current).strip()
    if remaining:
        statements.append(remaining)

    return statements
