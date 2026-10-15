'use strict';
// Source-checked for official 0.5.95. Not executed against an image yet.
const fs = require('node:fs');
const {spawn} = require('node:child_process');
const {DatabaseSync} = require('node:sqlite');
process.umask(0o077);
try {
  if (process.getuid() !== 1000 || process.env.DATA_DIR !== '/app/data') throw new Error('identity');
  if (process.env.ENABLE_REQUEST_LOGS !== 'false' || process.env.OBSERVABILITY_ENABLED !== 'false') throw new Error('logging');
  const password = fs.readFileSync('/run/secrets/dashboard-password', 'utf8').trim();
  const jwt = fs.readFileSync('/run/secrets/jwt-secret', 'utf8').trim();
  if (password.length < 24 || !/^[a-f0-9]{64}$/i.test(jwt)) throw new Error('secret-format');
  const dbDir = '/app/data/db';
  fs.mkdirSync(dbDir, {recursive: true, mode: 0o700});
  const db = new DatabaseSync(dbDir + '/data.sqlite');
  db.exec('PRAGMA busy_timeout=5000; CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL); BEGIN IMMEDIATE;');
  const row = db.prepare('SELECT data FROM settings WHERE id=1').get();
  const settings = row ? JSON.parse(row.data) : {};
  Object.assign(settings, {
    requireLogin: true, requireApiKey: true,
    cloudEnabled: false, tunnelEnabled: false, tailscaleEnabled: false,
    tunnelDashboardAccess: false,
    rtkEnabled: false, cavemanEnabled: false, headroomEnabled: false,
    ponytailEnabled: false, pxpipeEnabled: false, pxpipeAutoInstall: false,
    enableObservability: false,
    capacityAdapter: {
      vision: {enabled: false, models: []}, pdf: {enabled: false, models: []},
      audioInput: {enabled: false, models: []}, videoInput: {enabled: false, models: []}
    }
  });
  db.prepare('INSERT INTO settings(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data').run(JSON.stringify(settings));
  db.exec('COMMIT;');
  db.close();
  fs.chmodSync(dbDir + '/data.sqlite', 0o600);
  // Drop all raw application stdout/stderr, including unsanitized upstream errors.
  // Benchmark evidence comes from the separate allowlisted test harness.
  const child = spawn(process.execPath, ['/app/custom-server.js'], {
    cwd: '/app', stdio: ['ignore', 'ignore', 'ignore'],
    env: {...process.env, INITIAL_PASSWORD: password, JWT_SECRET: jwt}
  });
  console.log('STAGING_SECURITY_SETTINGS_SEEDED');
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
  child.on('error', () => {console.error('STAGING_APPLICATION_START_FAILED'); process.exit(1);});
  child.on('exit', (code, signal) => {
    console.log('STAGING_APPLICATION_EXITED');
    process.exit(signal ? 1 : (code ?? 1));
  });
} catch {
  console.error('STAGING_BOOTSTRAP_REFUSED');
  process.exit(1);
}
