use pycompiler::compiler::compile_and_run;
use pycompiler::database::{Database, VersionSource};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::time::Duration;

const MAX_REQUEST_SIZE: usize = 1024 * 1024;
const DEFAULT_ADDRESS: &str = "127.0.0.1:3030";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let project_root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let data_directory = match std::env::var_os("RUSTY_DATA_DIR") {
        Some(path) => Path::new(&path).to_path_buf(),
        None => project_root.join("data"),
    };
    let database_path = data_directory.join("code-history.sqlite3");
    let database = Database::open(&database_path)?;
    let saved_sources = database.snapshot_rust_sources(&project_root.join("src"), project_root)?;
    println!("Stored {saved_sources} changed Rust source file(s) in code history.");

    let address: SocketAddr = std::env::var("RUSTY_BIND_ADDRESS")
        .unwrap_or_else(|_| DEFAULT_ADDRESS.to_owned())
        .parse()?;
    let listener = TcpListener::bind(address)?;
    println!("Rust IDE is ready at http://{address}");

    for connection in listener.incoming() {
        match connection {
            Ok(stream) => {
                if let Err(error) = handle_connection(stream, &database) {
                    eprintln!("Request failed: {error}");
                }
            }
            Err(error) => eprintln!("Connection failed: {error}"),
        }
    }

    Ok(())
}

fn handle_connection(mut stream: TcpStream, database: &Database) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;

    let response = match read_request(&mut stream) {
        Ok((method, path, body)) => route(&method, &path, &body, database),
        Err((status, message)) => Response::text(status, message),
    };

    write!(
        stream,
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'\r\n\r\n",
        response.status,
        response.reason(),
        response.content_type,
        response.body.len()
    )?;
    stream.write_all(&response.body)
}

fn read_request(stream: &mut TcpStream) -> Result<(String, String, Vec<u8>), (u16, String)> {
    let mut request = Vec::new();
    let mut chunk = [0; 4096];
    let header_end = loop {
        if request.len() > MAX_REQUEST_SIZE {
            return Err((413, "Request is too large.".into()));
        }
        let count = stream
            .read(&mut chunk)
            .map_err(|error| (400, format!("Could not read request: {error}")))?;
        if count == 0 {
            return Err((400, "Incomplete request.".into()));
        }
        request.extend_from_slice(&chunk[..count]);
        if let Some(position) = request.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            break position + 4;
        }
    };

    let headers = std::str::from_utf8(&request[..header_end])
        .map_err(|_| (400, "Invalid request headers.".into()))?;
    let mut lines = headers.split("\r\n");
    let mut request_line = lines
        .next()
        .ok_or_else(|| (400, "Missing request line.".into()))?
        .split_whitespace();
    let method = request_line
        .next()
        .ok_or_else(|| (400, "Missing HTTP method.".into()))?
        .to_owned();
    let path = request_line
        .next()
        .ok_or_else(|| (400, "Missing request path.".into()))?
        .to_owned();
    let content_length = lines
        .filter_map(|line| line.split_once(':'))
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        .map(|(_, value)| value.trim().parse::<usize>())
        .transpose()
        .map_err(|_| (400, "Invalid content length.".into()))?
        .unwrap_or(0);

    if content_length > MAX_REQUEST_SIZE {
        return Err((413, "Request is too large.".into()));
    }

    let body_start = header_end;
    let expected_length = body_start + content_length;
    while request.len() < expected_length {
        let count = stream
            .read(&mut chunk)
            .map_err(|error| (400, format!("Could not read request body: {error}")))?;
        if count == 0 {
            return Err((400, "Incomplete request body.".into()));
        }
        request.extend_from_slice(&chunk[..count]);
    }

    Ok((method, path, request[body_start..expected_length].to_vec()))
}

fn route(method: &str, path: &str, body: &[u8], database: &Database) -> Response {
    if method == "GET" {
        return match path {
            "/" => Response::html(include_bytes!("../web/index.html")),
            "/style.css" => Response::css(include_bytes!("../web/style.css")),
            "/app.js" => Response::javascript(include_bytes!("../web/app.js")),
            "/api/versions" => match database.list_versions("main.rusty", 50) {
                Ok(versions) => match serde_json::to_vec(&versions) {
                    Ok(body) => Response::json(body),
                    Err(error) => database_failure("serialize code history", error),
                },
                Err(error) => database_failure("read code history", error),
            },
            _ => Response::text(404, "Not found."),
        };
    }

    if method == "POST" && path == "/api/save" {
        return match std::str::from_utf8(body) {
            Ok(source) => {
                match database.save_version("main.rusty", source, VersionSource::Editor) {
                    Ok(Some(version_id)) => {
                        Response::text(200, format!("Saved version {version_id}."))
                    }
                    Ok(None) => Response::text(200, "Code is already up to date."),
                    Err(error) => database_failure("save editor source", error),
                }
            }
            Err(_) => Response::text(400, "Source code must be valid UTF-8."),
        };
    }

    if method == "POST" && path == "/api/restore" {
        let version_id = match std::str::from_utf8(body)
            .ok()
            .and_then(|value| value.trim().parse::<i64>().ok())
        {
            Some(id) if id > 0 => id,
            _ => return Response::text(400, "Version ID must be a positive integer."),
        };

        return match database.load_version(version_id) {
            Ok(Some(version))
                if version.summary.file_path == "main.rusty"
                    && version.summary.source == VersionSource::Editor =>
            {
                Response::text(200, version.content)
            }
            Ok(_) => Response::text(404, "Editor version not found."),
            Err(error) => database_failure("restore editor source", error),
        };
    }

    if method == "POST" && path == "/api/run" {
        return match std::str::from_utf8(body) {
            Ok(source) => match compile_and_run(source) {
                Ok(output) => Response::text(200, output),
                Err(error) => Response::text(400, error.to_string()),
            },
            Err(_) => Response::text(400, "Source code must be valid UTF-8."),
        };
    }

    Response::text(404, "Not found.")
}

fn database_failure(context: &str, error: impl std::fmt::Display) -> Response {
    eprintln!("Could not {context}: {error}");
    Response::text(
        500,
        format!("Database error while attempting to {context}."),
    )
}

struct Response {
    status: u16,
    content_type: &'static str,
    body: Vec<u8>,
}

impl Response {
    fn text(status: u16, body: impl Into<String>) -> Self {
        Self {
            status,
            content_type: "text/plain; charset=utf-8",
            body: body.into().into_bytes(),
        }
    }

    fn html(body: &'static [u8]) -> Self {
        Self::asset("text/html; charset=utf-8", body)
    }

    fn css(body: &'static [u8]) -> Self {
        Self::asset("text/css; charset=utf-8", body)
    }

    fn javascript(body: &'static [u8]) -> Self {
        Self::asset("text/javascript; charset=utf-8", body)
    }

    fn json(body: Vec<u8>) -> Self {
        Self {
            status: 200,
            content_type: "application/json; charset=utf-8",
            body,
        }
    }

    fn asset(content_type: &'static str, body: &'static [u8]) -> Self {
        Self {
            status: 200,
            content_type,
            body: body.to_vec(),
        }
    }

    fn reason(&self) -> &'static str {
        match self.status {
            200 => "OK",
            400 => "Bad Request",
            404 => "Not Found",
            413 => "Payload Too Large",
            _ => "Internal Server Error",
        }
    }
}
