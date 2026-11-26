"""Explicit SQLite lifecycle. Importing this module never creates a store."""
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import os
import logging
import sys
from pathlib import Path
import sqlite3
import tempfile
from rop_insight.models.managed_data import StoreError

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000


def _schema_sql():
    return files('rop_insight.migrations').joinpath('001_initial.sql').read_text(encoding='utf-8')


def _statements(script):
    statement = ''
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement
            statement = ''
    if statement.strip():
        raise StoreError('SCHEMA_UNSUPPORTED', '数据库迁移语句不完整')


def _apply_initial_schema(connection):
    for statement in _statements(_schema_sql()):
        connection.execute(statement)


def _signature(connection):
    return tuple(tuple(row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))


@lru_cache(maxsize=1)
def _expected_signature():
    with sqlite3.connect(':memory:') as connection:
        _apply_initial_schema(connection)
        result = _signature(connection)
    connection.close()
    return result


def _reject_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise StoreError('VALIDATION_ERROR', '数据仓库不能位于链接或重解析路径')


def _translate(error):
    code = getattr(error, 'sqlite_errorcode', 0) & 0xff
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return StoreError('STORE_BUSY', '数据库正忙，请稍后重试')
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return StoreError('STORE_CORRUPT', '数据库损坏或格式无效')
    if isinstance(error, sqlite3.IntegrityError):
        return StoreError('VALIDATION_ERROR', '数据库约束校验失败')
    return StoreError('STORE_IO_ERROR', '数据库读写失败，请检查权限和本地存储')


def _connect(path):
    _reject_links(path)
    connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None,
                                 timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute(f'PRAGMA busy_timeout={BUSY_TIMEOUT_MS}')
        if connection.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
            raise StoreError('SCHEMA_UNSUPPORTED', '不支持的数据仓库日志模式')
        connection.execute('PRAGMA synchronous=FULL')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise StoreError('SCHEMA_UNSUPPORTED', 'SQLite外键约束未启用')
        return connection
    except BaseException:
        connection.close()
        raise


@dataclass(frozen=True)
class DataStore:
    root: Path

    @property
    def path(self):
        return self.root / 'catalog.sqlite3'

    @contextmanager
    def transaction(self, *, write=False):
        connection = None
        try:
            connection = _connect(self.path)
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except BaseException as error:
            if connection is not None and connection.in_transaction:
                try:
                    connection.rollback()
                except sqlite3.Error as rollback_error:
                    raise StoreError('STORE_IO_ERROR', '数据库回滚失败，连接已关闭') from rollback_error
            if isinstance(error, sqlite3.Error):
                raise _translate(error) from error
            if isinstance(error, OSError):
                raise StoreError('STORE_IO_ERROR', '无法访问数据仓库') from error
            raise
        finally:
            if connection is not None:
                connection.close()

    def health_check(self):
        with self.transaction() as connection:
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise StoreError('SCHEMA_UNSUPPORTED', '不支持的数据仓库版本')
            if _signature(connection) != _expected_signature():
                raise StoreError('SCHEMA_UNSUPPORTED', '数据仓库结构与版本不一致')
            if [row[0] for row in connection.execute('PRAGMA quick_check')] != ['ok'] or list(connection.execute('PRAGMA foreign_key_check')):
                raise StoreError('STORE_CORRUPT', '数据库完整性或外键检查未通过')
            # Current identity must agree with its immutable revision even after external edits.
            if connection.execute('''SELECT 1 FROM cases c JOIN case_revisions r
                ON c.case_id=r.case_id AND c.current_revision_id=r.revision_id
                WHERE c.case_code<>r.case_code OR c.case_code_key<>r.case_code_key LIMIT 1''').fetchone():
                raise StoreError('STORE_CORRUPT', '病例身份与当前资料版本不一致')
        return dict(schema_version=SCHEMA_VERSION, database='ok', files='not_checked')


def _root_path(root):
    try:
        if not isinstance(root, (str, os.PathLike)) or not str(root).strip():
            raise ValueError()
        return Path(root).absolute()
    except (TypeError, ValueError):
        raise StoreError('VALIDATION_ERROR', '数据仓库路径无效') from None


def open_store(root):
    root = _root_path(root)
    try:
        _reject_links(root)
        if not root.is_dir() or not (root / 'catalog.sqlite3').is_file():
            raise StoreError('STORE_IO_ERROR', '数据仓库不存在，请先显式初始化')
        store = DataStore(root)
        store.health_check()
        return store
    except OSError as error:
        raise StoreError('STORE_IO_ERROR', '无法访问数据仓库') from error


def _publish(temporary, destination):
    # Windows rename refuses to replace an existing destination. POSIX link has the same no-clobber property.
    if os.name == 'nt':
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
        temporary.unlink()


def initialize_new_store(root):
    root = _root_path(root)
    temporary = None
    try:
        _reject_links(root)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise StoreError('VALIDATION_ERROR', '新仓库必须使用空目录，不覆盖已有内容')
        descriptor, name = tempfile.mkstemp(prefix='.p6-init-', suffix='.sqlite3', dir=root)
        os.close(descriptor)
        temporary = Path(name)
        with _connection_for_initialization(temporary) as connection:
            _apply_initial_schema(connection)
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION or _signature(connection) != _expected_signature() or list(connection.execute('PRAGMA foreign_key_check')) or connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise StoreError('STORE_CORRUPT', '初始化数据库检查失败')
        _publish(temporary, root / 'catalog.sqlite3')
        return DataStore(root)
    except sqlite3.Error as error:
        raise _translate(error) from error
    except OSError as error:
        raise StoreError('STORE_IO_ERROR', '初始化或发布数据库失败，未覆盖已有仓库') from error
    finally:
        if temporary is not None:
            failed = sys.exc_info()[0] is not None
            # Only this initialization's allocated files; never remove published stores.
            for path in (temporary, Path(str(temporary) + '-journal')):
                try:
                    path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    if failed:
                        logging.getLogger(__name__).exception('Initialization temporary-file cleanup failed')
                    else:
                        raise StoreError('STORE_IO_ERROR', '数据库临时文件清理失败') from cleanup_error


@contextmanager
def _connection_for_initialization(path):
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise StoreError('SCHEMA_UNSUPPORTED', 'SQLite外键约束未启用')
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
