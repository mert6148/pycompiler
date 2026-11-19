//! Local SQLite-backed code history for editor saves and Rust source files.

use rusqlite::{params, types::Type, Connection, OptionalExtension};
use serde::Serialize;
use std::error::Error;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

const MAX_VERSION_LIST_SIZE: usize = 100;

/// Identifies the kind of source stored in a code-history entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VersionSource {
    Editor,
    Rust,
}

impl VersionSource {
    fn as_database_value(self) -> &'static str {
        match self {
            Self::Editor => "editor",
            Self::Rust => "rust",
        }
    }

    fn from_database_value(value: String) -> rusqlite::Result<Self> {
        match value.as_str() {
            "editor" => Ok(Self::Editor),
            "rust" => Ok(Self::Rust),
            _ => Err(rusqlite::Error::FromSqlConversionFailure(
                0,
                Type::Text,
                Box::new(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("unknown code version source '{value}'"),
                )),
            )),
        }
    }
}

/// Describes one saved source version without including its full code.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodeVersionSummary {
    /// Database identifier used to retrieve or restore this version.
    pub id: i64,
    /// Project-relative source path, such as `src/compiler.rs`.
    pub file_path: String,
    /// UTC timestamp in RFC 3339 format.
    pub created_at: String,
    /// Whether this came from the editor or a Rust source file.
    pub source: VersionSource,
}

/// A version record together with the saved source text.
#[derive(Debug, Clone)]
pub struct CodeVersion {
    /// Public metadata for this version.
    pub summary: CodeVersionSummary,
    /// Exact UTF-8 source stored in SQLite.
    pub content: String,
}

/// SQLite store for deduplicated, recoverable source-code versions.
pub struct Database {
    connection: Connection,
}

impl Database {
    /// Opens or creates a code-history database and initializes its schema.
    pub fn open(path: &Path) -> Result<Self, Box<dyn Error>> {
        if let Some(parent) = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            fs::create_dir_all(parent)?;
        }

        let connection = Connection::open(path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA synchronous = FULL;
             CREATE TABLE IF NOT EXISTS code_versions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 file_path TEXT NOT NULL,
                 source TEXT NOT NULL CHECK (source IN ('editor', 'rust')),
                 content TEXT NOT NULL,
                 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
             );
             CREATE INDEX IF NOT EXISTS idx_code_versions_path_id
                 ON code_versions (file_path, id DESC);",
        )?;

        Ok(Self { connection })
    }

    /// Stores a new version unless the latest version for this path is unchanged.
    ///
    /// Returns the new row ID, or `None` if identical content is already the
    /// latest version.
    pub fn save_version(
        &self,
        file_path: &str,
        content: &str,
        source: VersionSource,
    ) -> rusqlite::Result<Option<i64>> {
        let latest_content = self
            .connection
            .query_row(
                "SELECT content FROM code_versions WHERE file_path = ?1 ORDER BY id DESC LIMIT 1",
                [file_path],
                |row| row.get::<_, String>(0),
            )
            .optional()?;

        if latest_content.as_deref() == Some(content) {
            return Ok(None);
        }

        self.connection.execute(
            "INSERT INTO code_versions (file_path, source, content) VALUES (?1, ?2, ?3)",
            params![file_path, source.as_database_value(), content],
        )?;
        Ok(Some(self.connection.last_insert_rowid()))
    }

    /// Returns up to 100 newest versions for a project-relative file path.
    pub fn list_versions(
        &self,
        file_path: &str,
        limit: usize,
    ) -> rusqlite::Result<Vec<CodeVersionSummary>> {
        let limit = limit.clamp(1, MAX_VERSION_LIST_SIZE) as i64;
        let mut statement = self.connection.prepare(
            "SELECT id, file_path, created_at, source
             FROM code_versions
             WHERE file_path = ?1
             ORDER BY id DESC
             LIMIT ?2",
        )?;
        let rows = statement.query_map(params![file_path, limit], |row| {
            let source: String = row.get(3)?;
            Ok(CodeVersionSummary {
                id: row.get(0)?,
                file_path: row.get(1)?,
                created_at: row.get(2)?,
                source: VersionSource::from_database_value(source)?,
            })
        })?;

        rows.collect()
    }

    /// Loads a version by ID, including its exact source text.
    pub fn load_version(&self, id: i64) -> rusqlite::Result<Option<CodeVersion>> {
        self.connection
            .query_row(
                "SELECT id, file_path, created_at, source, content
                 FROM code_versions
                 WHERE id = ?1",
                [id],
                |row| {
                    let source: String = row.get(3)?;
                    Ok(CodeVersion {
                        summary: CodeVersionSummary {
                            id: row.get(0)?,
                            file_path: row.get(1)?,
                            created_at: row.get(2)?,
                            source: VersionSource::from_database_value(source)?,
                        },
                        content: row.get(4)?,
                    })
                },
            )
            .optional()
    }

    /// Saves changed `.rs` files under `source_root` as project-relative versions.
    ///
    /// Files are sorted before storage so startup snapshots are deterministic.
    pub fn snapshot_rust_sources(
        &self,
        source_root: &Path,
        project_root: &Path,
    ) -> Result<usize, Box<dyn Error>> {
        let mut files = Vec::new();
        collect_rust_files(source_root, &mut files)?;
        files.sort();

        let mut saved_count = 0;
        for path in files {
            let relative_path = path.strip_prefix(project_root)?.to_string_lossy();
            let file_path = relative_path.replace('\\', "/");
            let content = fs::read_to_string(&path)?;
            if self
                .save_version(&file_path, &content, VersionSource::Rust)?
                .is_some()
            {
                saved_count += 1;
            }
        }

        Ok(saved_count)
    }
}

fn collect_rust_files(directory: &Path, files: &mut Vec<PathBuf>) -> io::Result<()> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;

        if file_type.is_dir() {
            collect_rust_files(&path, files)?;
        } else if file_type.is_file() && path.extension().is_some_and(|extension| extension == "rs")
        {
            files.push(path);
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Database, VersionSource};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temporary_directory(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after the Unix epoch")
            .as_nanos();
        std::env::temp_dir().join(format!("pycompiler-{name}-{}-{nonce}", std::process::id()))
    }

    #[test]
    fn saves_versions_deduplicates_and_loads_previous_code() {
        let directory = temporary_directory("history");
        fs::create_dir_all(&directory).expect("temporary directory should be created");
        let database =
            Database::open(&directory.join("history.sqlite3")).expect("database should open");

        let first = database
            .save_version("main.rusty", "print 1;", VersionSource::Editor)
            .expect("first version should save")
            .expect("first version should have an ID");
        assert_eq!(
            database
                .save_version("main.rusty", "print 1;", VersionSource::Editor)
                .expect("unchanged source should be checked"),
            None
        );
        let second = database
            .save_version("main.rusty", "print 2;", VersionSource::Editor)
            .expect("changed source should save")
            .expect("second version should have an ID");

        let versions = database
            .list_versions("main.rusty", 10)
            .expect("version history should load");
        assert_eq!(
            versions
                .iter()
                .map(|version| version.id)
                .collect::<Vec<_>>(),
            [second, first]
        );

        let restored = database
            .load_version(first)
            .expect("version lookup should work")
            .expect("first version should exist");
        assert_eq!(restored.content, "print 1;");
        assert_eq!(restored.summary.source, VersionSource::Editor);

        drop(database);
        fs::remove_dir_all(directory).expect("temporary database should be removed");
    }

    #[test]
    fn snapshots_only_rust_files_and_skips_unchanged_files() {
        let project_root = temporary_directory("sources");
        let source_root = project_root.join("src");
        fs::create_dir_all(source_root.join("nested"))
            .expect("source directories should be created");
        fs::write(source_root.join("lib.rs"), "pub fn answer() -> i32 { 42 }")
            .expect("Rust source should be written");
        fs::write(source_root.join("nested/compiler.rs"), "fn compile() {}")
            .expect("nested Rust source should be written");
        fs::write(source_root.join("notes.txt"), "not source")
            .expect("non-Rust file should be written");
        let database = Database::open(&project_root.join("data/history.sqlite3"))
            .expect("database should open");

        assert_eq!(
            database
                .snapshot_rust_sources(&source_root, &project_root)
                .expect("Rust sources should be snapshotted"),
            2
        );
        assert_eq!(
            database
                .snapshot_rust_sources(&source_root, &project_root)
                .expect("unchanged sources should be checked"),
            0
        );
        assert_eq!(
            database
                .list_versions("src/nested/compiler.rs", 10)
                .expect("nested source history should load")
                .len(),
            1
        );
        assert!(database
            .list_versions("src/notes.txt", 10)
            .expect("non-Rust files should have no history")
            .is_empty());

        drop(database);
        fs::remove_dir_all(project_root).expect("temporary source project should be removed");
    }
}
