const fs = require('fs');
const path = require('path');

const workbenchPath =
  '/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/vs/code/browser/workbench/workbench.js';
const backupPath = `${workbenchPath}.bak-local-handshake-20260327`;
const extensionHostPath =
  '/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/vs/workbench/api/node/extensionHostProcess.js';
const extensionHostBackupPath = `${extensionHostPath}.bak-local-handshake-20260327`;

const legacyOriginalSnippet =
  'if(s.logService.trace(`${n} 4/6. received SignRequest control message.`),!await kRt(s.signService.validate(l,d.signedData),i)){const p=new Error("Refused to connect to unsupported server");throw p.code="VSCODE_CONNECTION_ERROR",p}const f=await kRt(s.signService.sign(d.data),i),g={type:"connectionType",commit:s.commit,signedData:f,desiredConnectionType:e};';

const previousPatchedSnippet =
  'const __ruijingValidateOk=await kRt(s.signService.validate(l,d.signedData),i);if(s.logService.trace(`${n} 4/6. received SignRequest control message.`),!__ruijingValidateOk){const __ruijingAllowLocal=typeof location<"u"&&/^(localhost|127\\\\.0\\\\.0\\\\.1)(:\\\\d+)?$/.test(location.host);if(__ruijingAllowLocal)s.logService.warn(`${n} local handshake validation failed; bypassing unsupported-server guard for local code-server.`);else{const p=new Error("Refused to connect to unsupported server");throw p.code="VSCODE_CONNECTION_ERROR",p}}const f=await kRt(s.signService.sign(d.data),i),g={type:"connectionType",commit:s.commit,signedData:f,desiredConnectionType:e};';

const originalFlowSnippet =
  'const l=await kRt(s.signService.createNewMessage(Ht()),i),c={type:"auth",auth:s.connectionToken||"00000000000000000000",data:l.data};r.sendControl(He.fromString(JSON.stringify(c)));try{const d=await pFn(r,gFn(i,H7i(1e4)));if(d.type!=="sign"||typeof d.data!="string"){const p=new Error("Unexpected handshake message");throw p.code="VSCODE_CONNECTION_ERROR",p}const __ruijingValidateOk=await kRt(s.signService.validate(l,d.signedData),i);if(s.logService.trace(`${n} 4/6. received SignRequest control message.`),!__ruijingValidateOk){const __ruijingAllowLocal=typeof location<"u"&&/^(localhost|127\\\\.0\\\\.0\\\\.1)(:\\\\d+)?$/.test(location.host);if(__ruijingAllowLocal)s.logService.warn(`${n} local handshake validation failed; bypassing unsupported-server guard for local code-server.`);else{const p=new Error("Refused to connect to unsupported server");throw p.code="VSCODE_CONNECTION_ERROR",p}}const f=await kRt(s.signService.sign(d.data),i),g={type:"connectionType",commit:s.commit,signedData:f,desiredConnectionType:e};';

const localBypassFlowSnippet =
  'const __ruijingAllowLocal=typeof location<"u"&&/^(localhost|127\\\\.0\\\\.0\\\\.1)(:\\\\d+)?$/.test(location.host),l=__ruijingAllowLocal?{data:Ht()}:await kRt(s.signService.createNewMessage(Ht()),i),c={type:"auth",auth:s.connectionToken||"00000000000000000000",data:l.data};r.sendControl(He.fromString(JSON.stringify(c)));try{const d=await pFn(r,gFn(i,H7i(1e4)));if(d.type!=="sign"||typeof d.data!="string"){const p=new Error("Unexpected handshake message");throw p.code="VSCODE_CONNECTION_ERROR",p}if(s.logService.trace(`${n} 4/6. received SignRequest control message.`),!__ruijingAllowLocal){const __ruijingValidateOk=await kRt(s.signService.validate(l,d.signedData),i);if(!__ruijingValidateOk){const p=new Error("Refused to connect to unsupported server");throw p.code="VSCODE_CONNECTION_ERROR",p}}else s.logService.warn(`${n} bypassing remote handshake signatures for local code-server.`);const f=__ruijingAllowLocal?Ht():await kRt(s.signService.sign(d.data),i),g={type:"connectionType",commit:s.commit,signedData:f,desiredConnectionType:e};';

const forcedBypassFlowSnippet =
  'const __ruijingAllowLocal=!0,l={data:Ht()},c={type:"auth",auth:s.connectionToken||"00000000000000000000",data:l.data};r.sendControl(He.fromString(JSON.stringify(c)));try{const d=await pFn(r,gFn(i,H7i(1e4)));if(d.type!=="sign"||typeof d.data!="string"){const p=new Error("Unexpected handshake message");throw p.code="VSCODE_CONNECTION_ERROR",p}s.logService.trace(`${n} 4/6. received SignRequest control message.`),s.logService.warn(`${n} bypassing remote handshake signatures for local code-server.`);const f=Ht(),g={type:"connectionType",commit:s.commit,signedData:f,desiredConnectionType:e};';

const originalSignServiceSnippet = 'const m=new $Be(t);s.set(LBe,m);';

const localSignServiceSnippet =
  'const m=typeof location<"u"&&/^(localhost|127\\\\.0\\\\.0\\\\.1)(:\\\\d+)?$/.test(location.host)?new c6n:new $Be(t);s.set(LBe,m);';

const forcedSignServiceSnippet = 'const m=new c6n;s.set(LBe,m);';

const extensionHostOriginalFlowSnippet =
  'const c=await eC(e.signService.createNewMessage(gt()),s),l={type:"auth",auth:e.connectionToken||"00000000000000000000",data:c.data};o.sendControl(B.fromString(JSON.stringify(l)));try{const u=await Die(o,$ie(s,aR(1e4)));if(u.type!=="sign"||typeof u.data!="string"){const g=new Error("Unexpected handshake message");throw g.code="VSCODE_CONNECTION_ERROR",g}if(e.logService.trace(`${r} 4/6. received SignRequest control message.`),!await eC(e.signService.validate(c,u.signedData),s)){const g=new Error("Refused to connect to unsupported server");throw g.code="VSCODE_CONNECTION_ERROR",g}const f=await eC(e.signService.sign(u.data),s),p={type:"connectionType",commit:e.commit,signedData:f,desiredConnectionType:t};';

const extensionHostPatchedFlowSnippet =
  'const __ruijingAllowLocal=typeof location<"u"&&/^(localhost|127\\\\.0\\\\.0\\\\.1)(:\\\\d+)?$/.test(location.host),c=__ruijingAllowLocal?{data:gt()}:await eC(e.signService.createNewMessage(gt()),s),l={type:"auth",auth:e.connectionToken||"00000000000000000000",data:c.data};o.sendControl(B.fromString(JSON.stringify(l)));try{const u=await Die(o,$ie(s,aR(1e4)));if(u.type!=="sign"||typeof u.data!="string"){const g=new Error("Unexpected handshake message");throw g.code="VSCODE_CONNECTION_ERROR",g}if(e.logService.trace(`${r} 4/6. received SignRequest control message.`),!__ruijingAllowLocal){const __ruijingValidateOk=await eC(e.signService.validate(c,u.signedData),s);if(!__ruijingValidateOk){const g=new Error("Refused to connect to unsupported server");throw g.code="VSCODE_CONNECTION_ERROR",g}}else e.logService.warn(`${r} bypassing extension-host handshake signatures for local code-server.`);const f=__ruijingAllowLocal?gt():await eC(e.signService.sign(u.data),s),p={type:"connectionType",commit:e.commit,signedData:f,desiredConnectionType:t};';

const extensionHostForcedBypassFlowSnippet =
  'const __ruijingAllowLocal=!0,c={data:gt()},l={type:"auth",auth:e.connectionToken||"00000000000000000000",data:c.data};o.sendControl(B.fromString(JSON.stringify(l)));try{const u=await Die(o,$ie(s,aR(1e4)));if(u.type!=="sign"||typeof u.data!="string"){const g=new Error("Unexpected handshake message");throw g.code="VSCODE_CONNECTION_ERROR",g}e.logService.trace(`${r} 4/6. received SignRequest control message.`),e.logService.warn(`${r} bypassing extension-host handshake signatures for local code-server.`);const f=gt(),p={type:"connectionType",commit:e.commit,signedData:f,desiredConnectionType:t};';

function patchFile(filePath, backupFilePath, replacements) {
  const source = fs.readFileSync(filePath, 'utf8');

  let updated = source;
  for (const [from, to] of replacements) {
    updated = updated.replace(from, to);
  }

  if (updated === source) {
    return false;
  }

  if (!fs.existsSync(backupFilePath)) {
    fs.copyFileSync(filePath, backupFilePath);
  }

  fs.writeFileSync(filePath, updated, 'utf8');
  return true;
}

function main() {
  const workbenchPatched = patchFile(workbenchPath, backupPath, [
    [legacyOriginalSnippet, previousPatchedSnippet],
    [originalFlowSnippet, localBypassFlowSnippet],
    [localBypassFlowSnippet, forcedBypassFlowSnippet],
    [originalSignServiceSnippet, localSignServiceSnippet],
    [localSignServiceSnippet, forcedSignServiceSnippet],
  ]);

  const extensionHostPatched = patchFile(extensionHostPath, extensionHostBackupPath, [
    [extensionHostOriginalFlowSnippet, extensionHostPatchedFlowSnippet],
    [extensionHostPatchedFlowSnippet, extensionHostForcedBypassFlowSnippet],
  ]);

  if (!workbenchPatched) {
    const workbenchSource = fs.readFileSync(workbenchPath, 'utf8');
    if (!workbenchSource.includes('bypassing remote handshake signatures for local code-server')) {
      throw new Error('Could not locate handshake snippet in workbench.js');
    }
  }

  if (!extensionHostPatched) {
    const extensionSource = fs.readFileSync(extensionHostPath, 'utf8');
    if (
      !extensionSource.includes('bypassing extension-host handshake signatures for local code-server')
    ) {
      throw new Error('Could not locate handshake snippet in extensionHostProcess.js');
    }
  }

  console.log(
    `Patched local handshake guard in ${path.basename(workbenchPath)} and ${path.basename(extensionHostPath)}`
  );
}

main();
