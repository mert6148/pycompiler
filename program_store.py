"""MySQL persistence for compiler programs and their revision history."""

from __future__ import annotations

import os
from typing import Any


SOURCE_TYPES = {
    "pycompiler",
    "python",
    "javascript",
    "cpp",
    "csharp",
    "c",
    "java",
    "php",
    "sql",
    "html",
    "css",
}
TARGET_LANGUAGES = {"python", "javascript", "cpp", "csharp", "php", "sql", "html", "css"}
MAX_PROGRAM_BYTES = 1_000_000
LIST_LIMIT = 100
HISTORY_LIMIT = 100


class ProgramStoreError(Exception):
    """Base error for program storage operations."""


class DatabaseNotConfigured(ProgramStoreError):
    """Raised when the MySQL connection settings are incomplete."""


class DatabaseDependencyMissing(ProgramStoreError):
    """Raised when the MySQL driver is not installed."""


class DatabaseConnectionFailed(ProgramStoreError):
    """Raised when the configured MySQL server cannot be reached."""


class ProgramNotFound(ProgramStoreError):
    """Raised when a requested program does not exist."""


class ProgramValidationError(ValueError):
    """Raised when a program payload contains invalid fields."""


def _utf8_size(value: str, message: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProgramValidationError(message) from error


def is_configured(environ: dict[str, str] | None = None) -> bool:
    environment = os.environ if environ is None else environ
    return all(
        environment.get(key, "").strip()
        for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE")
    )


def validate_program(payload: Any) -> dict[str, str | None]:
    required = {"name", "source_type", "source_code", "target_language"}
    allowed = required | {"generated_code"}
    if not isinstance(payload, dict) or not required.issubset(payload) or not set(payload).issubset(allowed):
        raise ProgramValidationError(
            "Program alanları name, source_type, source_code, target_language ve isteğe bağlı generated_code olmalıdır."
        )

    name = payload["name"]
    source_type = payload["source_type"]
    source_code = payload["source_code"]
    target_language = payload["target_language"]
    generated_code = payload.get("generated_code")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 150:
        raise ProgramValidationError("Program adı 1-150 karakter olmalıdır.")
    _utf8_size(name, "Program adı geçerli UTF-8 metin olmalıdır.")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise ProgramValidationError("Kaynak dili desteklenmiyor.")
    if not isinstance(source_code, str):
        raise ProgramValidationError("Kaynak kod metin olmalı ve 1 MB sınırını aşmamalıdır.")
    if _utf8_size(source_code, "Kaynak kod geçerli UTF-8 metin olmalıdır.") > MAX_PROGRAM_BYTES:
        raise ProgramValidationError("Kaynak kod metin olmalı ve 1 MB sınırını aşmamalıdır.")
    if not isinstance(target_language, str) or target_language not in TARGET_LANGUAGES:
        raise ProgramValidationError("Hedef dili desteklenmiyor.")
    if generated_code is not None and (
        not isinstance(generated_code, str)
    ):
        raise ProgramValidationError("Üretilen kod metin olmalı ve 1 MB sınırını aşmamalıdır.")
    if generated_code is not None and _utf8_size(
        generated_code,
        "Üretilen kod geçerli UTF-8 metin olmalıdır.",
    ) > MAX_PROGRAM_BYTES:
        raise ProgramValidationError("Üretilen kod metin olmalı ve 1 MB sınırını aşmamalıdır.")

    return {
        "name": name.strip(),
        "source_type": source_type,
        "source_code": source_code,
        "target_language": target_language,
        "generated_code": generated_code,
    }


def _connect():
    if not is_configured():
        raise DatabaseNotConfigured(
            "MySQL ayarları eksik. MYSQL_HOST, MYSQL_USER ve MYSQL_DATABASE değişkenlerini tanımlayın."
        )

    try:
        port = int(os.environ.get("MYSQL_PORT", "3306"))
    except ValueError as error:
        raise DatabaseNotConfigured("MYSQL_PORT 1-65535 arasında bir sayı olmalıdır.") from error
    if not 1 <= port <= 65535:
        raise DatabaseNotConfigured("MYSQL_PORT 1-65535 arasında bir sayı olmalıdır.")

    try:
        import pymysql
    except ModuleNotFoundError as error:
        raise DatabaseDependencyMissing(
            "MySQL sürücüsü eksik. python -m pip install -r requirements.txt komutunu çalıştırın."
        ) from error

    try:
        return pymysql.connect(
            host=os.environ["MYSQL_HOST"].strip(),
            port=port,
            user=os.environ["MYSQL_USER"].strip(),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ["MYSQL_DATABASE"].strip(),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
            read_timeout=10,
            write_timeout=10,
            autocommit=False,
        )
    except pymysql.MySQLError as error:
        raise DatabaseConnectionFailed(
            "MySQL bağlantısı kurulamadı. Sunucu, veritabanı ve erişim bilgilerini kontrol edin."
        ) from error


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat(sep=" ") if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def list_programs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    bounded_limit = min(max(int(limit), 1), LIST_LIMIT)
    bounded_offset = max(int(offset), 0)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, source_type, target_language, created_at, updated_at "
                "FROM compiler_programs ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
                (bounded_limit, bounded_offset),
            )
            return [_clean_row(row) for row in cursor.fetchall()]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_program(program_id: int) -> dict[str, Any]:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, source_type, source_code, target_language, generated_code, "
                "created_at, updated_at FROM compiler_programs WHERE id = %s",
                (program_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ProgramNotFound("Program bulunamadı.")
        return _clean_row(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_program(payload: Any) -> dict[str, Any]:
    program = validate_program(payload)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO compiler_programs "
                "(name, source_type, source_code, target_language, generated_code) "
                "VALUES (%s, %s, %s, %s, %s)",
                tuple(program[key] for key in (
                    "name", "source_type", "source_code", "target_language", "generated_code"
                )),
            )
            program_id = cursor.lastrowid
            cursor.execute(
                "SELECT id, name, source_type, source_code, target_language, generated_code, "
                "created_at, updated_at FROM compiler_programs WHERE id = %s",
                (program_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        if row is None:
            raise ProgramStoreError("Kaydedilen program yeniden okunamadı.")
        return _clean_row(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_program(program_id: int, payload: Any) -> dict[str, Any]:
    program = validate_program(payload)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, source_type, source_code, target_language, generated_code "
                "FROM compiler_programs WHERE id = %s FOR UPDATE",
                (program_id,),
            )
            previous = cursor.fetchone()
            if previous is None:
                raise ProgramNotFound("Program bulunamadı.")

            keys = ("name", "source_type", "source_code", "target_language", "generated_code")
            if any(previous[key] != program[key] for key in keys):
                cursor.execute(
                    "INSERT INTO compiler_programs_history "
                    "(compiler_program_id, name, source_type, source_code, target_language, generated_code) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        program_id,
                        *(previous[key] for key in keys),
                    ),
                )
                cursor.execute(
                    "UPDATE compiler_programs SET name = %s, source_type = %s, source_code = %s, "
                    "target_language = %s, generated_code = %s WHERE id = %s",
                    (*(program[key] for key in keys), program_id),
                )

            cursor.execute(
                "SELECT id, name, source_type, source_code, target_language, generated_code, "
                "created_at, updated_at FROM compiler_programs WHERE id = %s",
                (program_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        if row is None:
            raise ProgramStoreError("Güncellenen program yeniden okunamadı.")
        return _clean_row(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_program(program_id: int) -> None:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM compiler_programs WHERE id = %s", (program_id,))
            deleted = cursor.rowcount
        if deleted != 1:
            raise ProgramNotFound("Program bulunamadı.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_history(program_id: int, limit: int = 50) -> list[dict[str, Any]]:
    bounded_limit = min(max(int(limit), 1), HISTORY_LIMIT)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, compiler_program_id, name, source_type, source_code, "
                "target_language, generated_code, created_at "
                "FROM compiler_programs_history WHERE compiler_program_id = %s "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                (program_id, bounded_limit),
            )
            rows = cursor.fetchall()
            if not rows:
                cursor.execute(
                    "SELECT id FROM compiler_programs WHERE id = %s",
                    (program_id,),
                )
                if cursor.fetchone() is None:
                    raise ProgramNotFound("Program bulunamadı.")
            return [_clean_row(row) for row in rows]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
