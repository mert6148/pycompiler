<?php

declare(strict_types=1);

header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
header('Cache-Control: no-store');
header('X-Robots-Tag: noindex, nofollow');

$remoteAddress = $_SERVER['REMOTE_ADDR'] ?? '';
if (!in_array($remoteAddress, ['127.0.0.1', '::1'], true)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo "Bu yerel yönetim paneline yalnızca localhost üzerinden erişilebilir.\n";
    exit;
}

header('Content-Type: text/html; charset=utf-8');

function escapeHtml(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function renderErrorPage(string $message, int $statusCode): never
{
    http_response_code($statusCode);
    echo '<!doctype html><html lang="tr"><meta charset="utf-8"><title>PyCompiler yönetim paneli</title>';
    echo '<body><h1>Yönetim paneli açılamadı</h1><p>' . escapeHtml($message) . '</p></body></html>';
    exit;
}

if (!in_array('sqlite', PDO::getAvailableDrivers(), true)) {
    renderErrorPage('PDO SQLite eklentisi etkin değil. PHP yapılandırmasında pdo_sqlite eklentisini etkinleştirin.', 503);
}

$dataDirectory = sys_get_temp_dir()
    . DIRECTORY_SEPARATOR
    . 'pycompiler-admin-'
    . substr(hash('sha256', dirname(__DIR__, 2)), 0, 16);

if (!is_dir($dataDirectory) && !mkdir($dataDirectory, 0700, true) && !is_dir($dataDirectory)) {
    error_log('PyCompiler admin panel could not create its SQLite data directory.');
    renderErrorPage('Yerel veri klasörü oluşturulamadı. Klasör izinlerini kontrol edin.', 500);
}

$databasePath = $dataDirectory . DIRECTORY_SEPARATOR . 'dashboard.sqlite';

try {
    $database = new PDO('sqlite:' . $databasePath, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $database->exec(
        'CREATE TABLE IF NOT EXISTS app_metadata (
            metadata_key TEXT PRIMARY KEY,
            metadata_value TEXT NOT NULL
        )'
    );

    $saveInstallTime = $database->prepare(
        'INSERT OR IGNORE INTO app_metadata (metadata_key, metadata_value)
         VALUES (:metadata_key, :metadata_value)'
    );
    $saveInstallTime->execute([
        'metadata_key' => 'initialized_at_utc',
        'metadata_value' => gmdate('Y-m-d H:i:s') . ' UTC',
    ]);

    $installTime = $database->query(
        "SELECT metadata_value FROM app_metadata WHERE metadata_key = 'initialized_at_utc'"
    )->fetchColumn();
} catch (PDOException $exception) {
    error_log('PyCompiler admin panel SQLite error: ' . $exception->getMessage());
    renderErrorPage('SQLite veritabanı açılamadı. PHP hata günlüğünü ve yerel klasör izinlerini kontrol edin.', 500);
}

$sqliteVersion = $database->query('SELECT sqlite_version()')->fetchColumn();
clearstatcache(true, $databasePath);
$databaseSize = filesize($databasePath);
$databaseSizeLabel = $databaseSize === false
    ? 'Ölçülemedi'
    : ($databaseSize < 1024 * 1024
        ? number_format($databaseSize, 0, ',', '.') . ' bayt'
        : number_format($databaseSize / (1024 * 1024), 2, ',', '.') . ' MB');

$checks = [
    'PHP çalışma zamanı' => PHP_VERSION,
    'Çalışma biçimi' => PHP_SAPI,
    'SQLite sürümü' => (string) $sqliteVersion,
    'Veritabanı boyutu' => $databaseSizeLabel,
    'Gerekli PDO SQLite sürücüsü' => 'Etkin',
    'Kurulum zamanı (UTC)' => (string) $installTime,
];
?>
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101114">
  <title>Yönetim paneli | PyCompiler</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: "Segoe UI", sans-serif;
      color: #efeff2;
      background: #101114;
      --muted: #a8a9b2;
      --accent: #c4f46a;
      --panel: #191a1f;
      --border: #2b2c33;
    }

    * { box-sizing: border-box; }
    body { min-height: 100vh; margin: 0; padding: 32px 20px; }
    main { width: min(100%, 960px); margin: 0 auto; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 32px; }
    .brand { color: var(--accent); font: 500 14px Consolas, monospace; }
    h1 { margin: 10px 0 0; font-size: clamp(28px, 5vw, 40px); letter-spacing: -1.5px; }
    h1 span { color: var(--accent); }
    a { color: var(--accent); }
    .back-link { white-space: nowrap; }
    .intro, .notice { color: var(--muted); line-height: 1.65; }
    .notice { margin: 0 0 24px; padding: 14px 16px; border: 1px solid #5b4924; border-radius: 8px; background: #282216; }
    .status { display: inline-flex; align-items: center; gap: 8px; color: var(--accent); font-size: 13px; font-weight: 700; }
    .status::before { width: 8px; height: 8px; border-radius: 50%; background: currentColor; content: ""; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin-top: 24px; }
    article { padding: 20px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); }
    h2 { margin: 0 0 16px; font-size: 16px; }
    dl { display: grid; gap: 13px; margin: 0; }
    dl div { display: flex; justify-content: space-between; gap: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
    dl div:last-child { padding-bottom: 0; border-bottom: 0; }
    dt { color: var(--muted); }
    dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
    footer { margin-top: 28px; color: var(--muted); font-size: 12px; }
    @media (max-width: 560px) {
      body { padding: 24px 16px; }
      header { align-items: flex-start; flex-direction: column; }
      dl div { flex-direction: column; gap: 4px; }
      dd { text-align: left; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="brand" aria-hidden="true">&lt;/&gt; pycompiler.</div>
        <h1>Yönetim <span>paneli</span></h1>
      </div>
      <a class="back-link" href="../index.html">Derleyiciye dön</a>
    </header>

    <p class="intro">Yerel uygulama çalışma zamanı ve SQLite bağlantı durumu.</p>
    <p class="notice">Bu panel giriş ekranı içermez ve yalnızca localhost bağlantılarını kabul eder. Gerçek veya ağ üzerinden erişilen ortamlarda kullanmayın.</p>
    <p class="status">Uygulama çalışıyor</p>

    <section class="grid" aria-label="Sistem durumu">
      <article>
        <h2>Çalışma zamanı</h2>
        <dl>
          <?php foreach (array_slice($checks, 0, 2, true) as $label => $value): ?>
            <div><dt><?= escapeHtml($label) ?></dt><dd><?= escapeHtml($value) ?></dd></div>
          <?php endforeach; ?>
        </dl>
      </article>
      <article>
        <h2>Veritabanı</h2>
        <dl>
          <?php foreach (array_slice($checks, 2, null, true) as $label => $value): ?>
            <div><dt><?= escapeHtml($label) ?></dt><dd><?= escapeHtml($value) ?></dd></div>
          <?php endforeach; ?>
        </dl>
      </article>
    </section>

    <footer>Veritabanı proje web kökünün dışındaki yerel geçici klasörde tutulur. Bu ekran istek geçmişi veya kişisel veri kaydetmez.</footer>
  </main>
</body>
</html>
