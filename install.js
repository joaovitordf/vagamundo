#!/usr/bin/env node
/**
 * Instalador multiplataforma de primeira instalação do Vagamundo.
 *
 * Uso:
 *   node install.js               # instala frontend, Python (requirements.txt) e CLIs dos portais
 *   node install.js --portals-only
 *   node install.js --skip-python
 */

const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const args = new Set(process.argv.slice(2));
const portalsOnly = args.has('--portals-only');
const skipPython = args.has('--skip-python');

function run(cmd, cmdArgs, cwd = ROOT) {
  const res = spawnSync(cmd, cmdArgs, {
    cwd,
    stdio: 'inherit',
    shell: process.platform === 'win32' && /\.(cmd|bat)$/i.test(cmd),
  });
  return res.status === 0;
}

function npmBin() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm';
}

function findPython() {
  const candidates = [
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(ROOT, '.venv', 'bin', 'python'),
    path.join(ROOT, 'backend', '.venv', 'Scripts', 'python.exe'),
    path.join(ROOT, 'backend', '.venv', 'bin', 'python'),
  ];

  for (const binPath of candidates) {
    if (fs.existsSync(binPath)) {
      return { cmd: binPath, prefixArgs: [] };
    }
  }

  const probes = process.platform === 'win32'
    ? [
        { cmd: 'python', prefixArgs: [] },
        { cmd: 'py', prefixArgs: ['-3'] },
        { cmd: 'python3', prefixArgs: [] },
      ]
    : [
        { cmd: 'python3', prefixArgs: [] },
        { cmd: 'python', prefixArgs: [] },
      ];

  for (const probe of probes) {
    try {
      execFileSync(probe.cmd, [...probe.prefixArgs, '--version'], { stdio: 'ignore' });
      return probe;
    } catch (_) {
      // tenta próximo candidato
    }
  }
  return null;
}

function main() {
  if (!portalsOnly) {
    console.log('\n[1/3] Instalando dependências do frontend Angular...');
    if (!run(npmBin(), ['--prefix', 'frontend', 'install'])) {
      console.error('Falha ao instalar dependências do frontend.');
      process.exit(1);
    }
  }

  const py = findPython();
  if (!py) {
    console.error('Python 3.10+ não encontrado no PATH. Instale o Python e execute novamente.');
    process.exit(1);
  }

  if (!portalsOnly && !skipPython) {
    const reqPath = path.join(ROOT, 'requirements.txt');
    if (fs.existsSync(reqPath)) {
      console.log(`\n[2/3] Instalando dependências Python (${py.cmd})...`);
      const ok = run(py.cmd, [...py.prefixArgs, '-m', 'pip', 'install', '-r', 'requirements.txt']);
      if (!ok) {
        console.warn(
          '\nAviso: `pip install -r requirements.txt` falhou. ' +
          'Se estiver usando ambiente gerenciado pelo sistema, crie/ative um `.venv` e rode `pip install -r requirements.txt`.'
        );
        process.exit(1);
      }
    }
  }

  console.log('\n[3/3] Instalando dependências das CLIs de portais...');
  const okPortals = run(py.cmd, [...py.prefixArgs, path.join('backend', 'tools', 'install_portal_clis.py')]);
  if (!okPortals) {
    process.exit(1);
  }

  console.log('\nInstalação concluída. Inicie o Vagamundo com: npm run dev');
}

if (require.main === module) {
  main();
}

module.exports = { findPython };

