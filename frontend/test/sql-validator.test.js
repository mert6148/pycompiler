import assert from "node:assert/strict";
import test from "node:test";
import { SqlValidationError, validateSql } from "../src/sql-validator.js";

test("checks SQL statement structure and supports comments and multiple statements", () => {
  assert.deepEqual(validateSql(`-- a comment
SELECT 'value; with delimiter' AS label;
UPDATE users SET active = 1 WHERE id = 2;`), { statementCount: 2 });
});

test("accepts the project's MySQL schema statements", () => {
  assert.deepEqual(validateSql(`CREATE DATABASE IF NOT EXISTS pycompiler;
USE pycompiler;
CREATE TABLE compiler_programs (
  id BIGINT NOT NULL,
  name VARCHAR(150) NOT NULL
);`), { statementCount: 3 });
});

test("reports unclosed delimiters and mismatched parentheses with source position", () => {
  assert.throws(() => validateSql("SELECT (1"), (error) => {
    assert.ok(error instanceof SqlValidationError);
    assert.match(error.message, /^1:8:/);
    return true;
  });
  assert.throws(() => validateSql("SELECT 'unfinished"), /1:8: Kapatılmamış tırnak/);
  assert.throws(() => validateSql("SELECT 1)"), /1:9: Eşleşmeyen/);
});

test("rejects empty and incomplete SQL statements", () => {
  assert.throws(() => validateSql("-- comment only"), /Denetlenecek bir SQL sorgusu/);
  assert.throws(() => validateSql("SELECT FROM users"), /SELECT ifadesinde/);
  assert.throws(() => validateSql("UPDATE users WHERE id = 1"), /SET bölümü/);
  assert.throws(() => validateSql("DELETE users"), /FROM bölümü/);
  assert.throws(() => validateSql("MERGE INTO users"), /tanınmayan SQL/);
});
