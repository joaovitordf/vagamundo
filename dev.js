const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');

console.log('\x1b[35m%s\x1b[0m', '==================================================');
console.log('\x1b[35m%s\x1b[0m', '   🚀 Vagamundo - Iniciando Ambiente Completo     ');
console.log('\x1b[35m%s\x1b[0m', '==================================================\n');

// 1. Libera apenas processos LISTENING nas portas 8765 (Python) e 4200 (Angular)
function killPort(port) {
  try {
    const stdout = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
    const lines = stdout.trim().split('\n');
    const killedPids = new Set();
    for (const line of lines) {
      if (!line.includes('LISTENING')) continue;
      const parts = line.trim().split(/\s+/);
      const pid = parseInt(parts[parts.length - 1], 10);
      if (pid && pid > 0 && pid !== process.pid && !killedPids.has(pid)) {
        killedPids.add(pid);
        try {
          execSync(`taskkill /PID ${pid} /F /T`, { stdio: 'ignore' });
        } catch (_) {}
      }
    }
  } catch (_) {}
}

killPort(8765);
killPort(4200);

// 2. Inicia o Backend Python
console.log('\x1b[36m[backend]\x1b[0m Iniciando servidor FastAPI / Uvicorn (porta 8765)...');
const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
const backend = spawn(pythonCmd, ['-m', 'uvicorn', 'backend.api.app:app', '--port', '8765', '--host', '127.0.0.1'], {
  cwd: __dirname,
  stdio: ['inherit', 'pipe', 'pipe']
});

backend.stdout.on('data', (data) => {
  const msg = data.toString();
  process.stdout.write(`\x1b[36m[backend]\x1b[0m ${msg}`);
});

backend.stderr.on('data', (data) => {
  process.stderr.write(`\x1b[31m[backend-err]\x1b[0m ${data.toString()}`);
});

// 3. Aguarda o backend responder antes de ligar o frontend
function waitForBackend(callback, retries = 25) {
  if (retries <= 0) {
    console.log('\x1b[33m[backend]\x1b[0m Tempo limite de espera, iniciando frontend...\x1b[0m');
    return callback();
  }
  const req = http.get('http://127.0.0.1:8765/api/token', (res) => {
    res.resume();
    if (res.statusCode === 200) {
      console.log('\x1b[32m[backend]\x1b[0m Backend pronto e respondendo em http://127.0.0.1:8765/\x1b[0m');
      callback();
    } else {
      setTimeout(() => waitForBackend(callback, retries - 1), 250);
    }
  });
  req.on('error', () => {
    setTimeout(() => waitForBackend(callback, retries - 1), 250);
  });
}

// 4. Inicia o Frontend Angular executando o binário JS do Angular CLI diretamente pelo Node
let frontend = null;
waitForBackend(() => {
  console.log('\x1b[34m[frontend]\x1b[0m Iniciando Angular dev server (porta 4200)...\x1b[0m\n');
  const ngBin = path.join(__dirname, 'frontend', 'node_modules', '@angular', 'cli', 'bin', 'ng.js');
  frontend = spawn(process.execPath, [ngBin, 'serve'], {
    cwd: path.join(__dirname, 'frontend'),
    stdio: 'inherit'
  });

  frontend.on('exit', (code) => {
    cleanup();
    process.exit(code || 0);
  });
});

// 5. Finalização limpa ao pressionar Ctrl+C
let isCleaningUp = false;
function cleanup() {
  if (isCleaningUp) return;
  isCleaningUp = true;
  console.log('\n\x1b[35m[vagamundo]\x1b[0m Encerrando serviços...');
  if (backend && backend.pid) {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /PID ${backend.pid} /F /T`, { stdio: 'ignore' });
      } else {
        backend.kill('SIGTERM');
      }
    } catch (_) {}
  }
  if (frontend && frontend.pid) {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /PID ${frontend.pid} /F /T`, { stdio: 'ignore' });
      } else {
        frontend.kill('SIGTERM');
      }
    } catch (_) {}
  }
}

process.on('SIGINT', () => {
  cleanup();
  process.exit(0);
});

process.on('SIGTERM', () => {
  cleanup();
  process.exit(0);
});

process.on('exit', () => {
  cleanup();
});
