import unittest
from unittest import mock

import program_store


class ProgramStoreValidationTests(unittest.TestCase):
    def test_accepts_program_payload(self):
        payload = {
            "name": "  Demo  ",
            "source_type": "pycompiler",
            "source_code": "print(1)",
            "target_language": "python",
        }

        self.assertEqual(
            program_store.validate_program(payload),
            {
                "name": "Demo",
                "source_type": "pycompiler",
                "source_code": "print(1)",
                "target_language": "python",
                "generated_code": None,
            },
        )

    def test_rejects_invalid_fields_and_oversized_source(self):
        valid = {
            "name": "Demo",
            "source_type": "pycompiler",
            "source_code": "print(1)",
            "target_language": "python",
        }
        invalid_payloads = (
            {**valid, "extra": True},
            {**valid, "source_type": "unknown"},
            {**valid, "target_language": "unknown"},
            {**valid, "name": " "},
            {**valid, "source_code": "\ud800"},
            {**valid, "source_code": "é" * (program_store.MAX_PROGRAM_BYTES // 2 + 1)},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload.keys()), self.assertRaises(
                program_store.ProgramValidationError
            ):
                program_store.validate_program(payload)


class ProgramStoreTransactionTests(unittest.TestCase):
    def test_update_archives_previous_revision_atomically(self):
        previous = {
            "id": 4,
            "name": "Old",
            "source_type": "pycompiler",
            "source_code": "print(1)",
            "target_language": "python",
            "generated_code": "print(1)",
        }
        updated = {
            **previous,
            "name": "New",
            "source_code": "print(2)",
            "generated_code": "print(2)",
        }
        connection = _FakeConnection(previous, updated)
        payload = {
            "name": "New",
            "source_type": "pycompiler",
            "source_code": "print(2)",
            "target_language": "python",
            "generated_code": "print(2)",
        }

        with mock.patch.object(program_store, "_connect", return_value=connection):
            result = program_store.update_program(4, payload)

        self.assertEqual(result, updated)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(
            any("INSERT INTO compiler_programs_history" in query for query, _ in connection.queries)
        )
        self.assertTrue(
            any("UPDATE compiler_programs SET" in query for query, _ in connection.queries)
        )
        connection.close.assert_called_once()

    def test_missing_program_rolls_back(self):
        connection = _FakeConnection(None, None)
        payload = {
            "name": "New",
            "source_type": "pycompiler",
            "source_code": "print(2)",
            "target_language": "python",
        }

        with (
            mock.patch.object(program_store, "_connect", return_value=connection),
            self.assertRaises(program_store.ProgramNotFound),
        ):
            program_store.update_program(4, payload)

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters=()):
        self.connection.queries.append((query, parameters))
        if "FOR UPDATE" in query:
            self.row = self.connection.previous
        elif query.startswith("SELECT id, name"):
            self.row = self.connection.updated

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, previous, updated):
        self.previous = previous
        self.updated = updated
        self.queries = []
        self.committed = False
        self.rolled_back = False
        self._cursor = _FakeCursor(self)
        self.close = mock.Mock()

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


if __name__ == "__main__":
    unittest.main()
