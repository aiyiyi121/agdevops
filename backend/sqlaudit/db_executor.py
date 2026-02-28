"""
MySQL 数据库执行器
通过 pymysql 连接 MySQL 实例执行 SQL。
"""
import time
import pymysql
from pymysql.cursors import DictCursor


def test_connection(datasource):
    """
    测试数据源连通性。
    返回 (success: bool, message: str)
    """
    try:
        conn = pymysql.connect(
            host=datasource.host,
            port=datasource.port,
            user=datasource.user,
            password=datasource.password,
            charset=datasource.charset,
            connect_timeout=5,
        )
        conn.close()
        return True, '连接成功'
    except pymysql.Error as e:
        return False, f'连接失败: {e}'
    except Exception as e:
        return False, f'连接异常: {e}'


def get_databases(datasource):
    """
    获取数据源中的数据库列表。
    """
    try:
        conn = pymysql.connect(
            host=datasource.host,
            port=datasource.port,
            user=datasource.user,
            password=datasource.password,
            charset=datasource.charset,
            connect_timeout=5,
        )
        with conn.cursor() as cursor:
            cursor.execute('SHOW DATABASES')
            databases = [row[0] for row in cursor.fetchall()]
            # 过滤系统库
            system_dbs = {'information_schema', 'mysql', 'performance_schema', 'sys'}
            databases = [db for db in databases if db not in system_dbs]
        conn.close()
        return databases
    except Exception as e:
        return []


def execute_sql(datasource, database, sql_content):
    """
    执行 DDL/DML SQL (非 SELECT)。
    返回 (success, affected_rows, duration_ms, log)
    """
    start = time.time()
    try:
        conn = pymysql.connect(
            host=datasource.host,
            port=datasource.port,
            user=datasource.user,
            password=datasource.password,
            database=database,
            charset=datasource.charset,
            connect_timeout=10,
            autocommit=False,
        )
        total_affected = 0
        logs = []

        try:
            with conn.cursor() as cursor:
                # 按分号切分多条语句
                statements = [s.strip() for s in sql_content.split(';') if s.strip()]
                for i, stmt in enumerate(statements, 1):
                    cursor.execute(stmt)
                    affected = cursor.rowcount
                    total_affected += max(affected, 0)
                    logs.append(f'语句 #{i}: 影响 {affected} 行')

            conn.commit()
            duration = int((time.time() - start) * 1000)
            return True, total_affected, duration, '\n'.join(logs)
        except Exception as e:
            conn.rollback()
            duration = int((time.time() - start) * 1000)
            return False, 0, duration, f'执行失败: {e}'
        finally:
            conn.close()
    except pymysql.Error as e:
        duration = int((time.time() - start) * 1000)
        return False, 0, duration, f'连接失败: {e}'


def execute_query(datasource, database, sql_content, limit=200):
    """
    执行 SELECT 查询。
    返回 (success, columns, rows, count, duration_ms, error)
    """
    start = time.time()
    try:
        conn = pymysql.connect(
            host=datasource.host,
            port=datasource.port,
            user=datasource.user,
            password=datasource.password,
            database=database,
            charset=datasource.charset,
            connect_timeout=10,
            cursorclass=DictCursor,
        )
        with conn.cursor() as cursor:
            cursor.execute(sql_content)
            rows = cursor.fetchmany(limit)
            count = cursor.rowcount
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

        conn.close()
        duration = int((time.time() - start) * 1000)
        return True, columns, rows, count, duration, None
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return False, [], [], 0, duration, str(e)
