'use strict'
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

let proxyBase = ''
try {
  const cfg = fs.readFileSync(path.join(__dirname, 'vibe-serve-config'), 'utf8')
  const m = cfg.match(/^PROXY_BASE=(.+)$/m)
  if (m) proxyBase = m[1].trim()
} catch (_) {}

const args = ['vue-cli-service', 'serve', ...process.argv.slice(2)]
const proc = spawn('npx', args, { cwd: __dirname, stdio: ['inherit', 'pipe', 'pipe'], env: process.env })

let announced = false
function handleLine(line) {
  process.stdout.write(line + '\n')
  if (!announced) {
    const m = line.match(/Local:\s+https?:\/\/localhost:(\d+)/)
    if (m) {
      if (proxyBase) process.stdout.write('  - Public:  ' + proxyBase + '/proxy/' + m[1] + '/\n')
      announced = true
    }
  }
}
function pipeStream(s) {
  let buf = ''
  s.setEncoding('utf8')
  s.on('data', c => { buf += c; const lines = buf.split('\n'); buf = lines.pop(); lines.forEach(handleLine) })
  s.on('end', () => { if (buf) handleLine(buf) })
}
pipeStream(proc.stdout)
pipeStream(proc.stderr)
proc.on('exit', code => process.exit(code ?? 0))
