@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 (
    >&2 echo Could not open the project directory.
    exit /b 1
)

where cargo >nul 2>&1
if errorlevel 1 (
    >&2 echo Rust and Cargo are required. Install Rust from https://rustup.rs and try again.
    popd
    exit /b 1
)

cargo run
set "result=%ERRORLEVEL%"

popd
exit /b %result%
