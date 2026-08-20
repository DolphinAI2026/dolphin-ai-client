import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);

async function read(relativePath) {
  return readFile(new URL(relativePath, root), 'utf8');
}

test('desktop workflows install the repository-pinned Rust toolchain', async () => {
  const toolchain = await read('rust-toolchain.toml');
  const channel = toolchain.match(/^channel\s*=\s*"([^"]+)"/m)?.[1];
  const components = toolchain.match(/^components\s*=\s*\[([^\]]+)\]/m)?.[1]
    .split(',')
    .map((value) => value.trim().replaceAll('"', ''))
    .join(',');

  assert.equal(channel, '1.93');
  assert.equal(components, 'clippy,rustfmt');

  for (const workflowPath of [
    '.github/workflows/desktop-release.yml',
    '.github/workflows/desktop-windows.yml',
  ]) {
    const workflow = await read(workflowPath);
    const installs = [...workflow.matchAll(/- uses: dtolnay\/rust-toolchain@stable(?<config>[\s\S]*?)(?=\n\s*- (?:uses:|name:|id:)|$)/g)];

    assert.ok(installs.length > 0, `${workflowPath} must install Rust`);
    for (const install of installs) {
      assert.match(install.groups.config, new RegExp(`toolchain:\\s*['"]?${channel}['"]?`));
      assert.match(install.groups.config, new RegExp(`components:\\s*['"]?${components}['"]?`));
    }
  }
});
