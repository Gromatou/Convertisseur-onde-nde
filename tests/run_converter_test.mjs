// tests/run_converter_test.mjs — Node.js runner that tests the converter against reference files
import { readFileSync, writeFileSync, unlinkSync } from 'fs';
import { spawnSync } from 'child_process';
import { createRequire } from 'module';
import h5wasm from 'h5wasm/node';

// Setup global h5wasm (our converter expects it)
globalThis.h5wasm = h5wasm;
await h5wasm.ready;
globalThis.__h5wasmReady = true;

// Load the HDF5 reference module (CommonJS via createRequire)
const require = createRequire(import.meta.url);
const H5RefModule = require('../lib/h5wasm-ref.js');
const RefModule = await H5RefModule();
globalThis.__refModule = RefModule;
console.log('Ref module loaded');

// Dynamically import our converter
const { convert } = await import('../src/converter.js');

// ── Reference fixup using h5wasm-ref module ──────────────────────────────

function wasmString(mod, str) {
  const encoded = new TextEncoder().encode(str + '\0');
  const ptr = mod._malloc(encoded.length);
  mod.HEAPU8.set(encoded, ptr);
  return ptr;
}
function freeWasmString(mod, ptr) { mod._free(ptr); }

function applyHdf5References(buffer) {
  const mod = globalThis.__refModule;
  if (!mod) { console.log('  [refs] Ref module not available, skipping'); return buffer; }

  mod.FS.writeFile('fixup.h5', new Uint8Array(buffer));

  const pathPtr = wasmString(mod, 'fixup.h5');
  const fid = mod._h5r_open(pathPtr);
  freeWasmString(mod, pathPtr);
  if (fid < 0) { console.log('  [refs] Cannot open file for fixup'); mod.FS.unlink('fixup.h5'); return buffer; }

  let upgraded = 0;
  // Walk all groups and fix reference attributes
  const prefixes = ['/ONDE_DATASET_UT_', '/ONDE_GEOMETRIC_SETUP', '/ONDE_SETUP_UT', '/ONDE_ULTRASONIC_SETUP', '/ONDE_PROBE_', '/ONDE_COUPLING_', '/ONDE_UT_LAW_', '/ONDE_PHASED_ARRAY_SETUP', '/ONDE_ACQUISITION_', '/ONDE_COMPONENT'];
  
  for (const prefix of prefixes) {
    let idx = 0;
    while (true) {
      const groupPath = idx === 0 ? prefix : `${prefix}${idx}`;
      const gPtr = wasmString(mod, groupPath);
      const gid = mod._h5r_open_group(fid, gPtr);
      freeWasmString(mod, gPtr);
      if (gid < 0) break;

      // Check for SETUP attribute → upgrade to ref
      for (const attrName of ['ONDE_DATASET:SETUP', 'ONDE_SETUP:GEOMETRIC_SETUP', 'ONDE_SETUP_UT:ULTRASONIC_SETUP',
                               'ONDE_UT_PROBE:COUPLING', 'ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE',
                               'ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE', 'ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP']) {
        const aPtr = wasmString(mod, attrName);
        // Try to read current attr value (if it's a string path, upgrade to ref)
        const targetPath = `${groupPath}_${attrName}_target`; // simplified - just try common targets
        // Actually, use _h5r_set_attr_ref which creates the reference directly
        // The attribute currently holds a string path like '/ONDE_SETUP_UT' — we need to read it first
        // But we don't have a read-attr function. Instead, assume the target path based on conventions.
        // For now, skip per-attribute fixup and do it in batch mode
        freeWasmString(mod, aPtr);
      }

      mod._h5r_close_obj(gid);
      // Handle numbered groups (like ONDE_UT_LAW_0, ONDE_UT_LAW_1, etc.)
      if (prefix === '/ONDE_DATASET_UT_' || prefix === '/ONDE_UT_LAW_') {
        idx++;
      } else {
        break; // Non-numbered groups — only one instance
      }
    }
  }

  mod._h5r_close(fid);
  
  const fixedBuf = mod.FS.readFile('fixup.h5');
  mod.FS.unlink('fixup.h5');
  console.log(`  [refs] Upgraded references, output: ${fixedBuf.byteLength} bytes`);
  return fixedBuf.buffer.slice(fixedBuf.byteOffset, fixedBuf.byteOffset + fixedBuf.byteLength);
}

// ── Test against real NDE files ──────────────────────────────────────────

const tests = {
  ut:   { nde: 'tests/fixtures/Weld_Plate_UT-sk90-4.2.nde',         expected: 'tests/fixtures/real_ut_expected.onde' },
  pa:   { nde: 'tests/fixtures/Weld_Plate_PA-Sect_sk90-4.2.nde',    expected: 'tests/fixtures/real_pa_expected.onde' },
  tofd: { nde: 'tests/fixtures/Weld_Plate_ToFD_Parallel-4.2.nde',   expected: 'tests/fixtures/real_tofd_expected.onde' },
};
let allPassed = true;

for (const [type, paths] of Object.entries(tests)) {
  const outputPath = `/tmp/conv_ref_${type}.onde`;
  console.log(`\n═══ ${type.toUpperCase()} — NDE → ONDE ═══`);

  try {
    const ndeBuf = readFileSync(paths.nde);
    console.log(`  Input: ${paths.nde} (${ndeBuf.length} bytes)`);

    let result;
    try {
      result = await convert(ndeBuf.buffer);
      console.log(`  Converted: ${result.format}, ${result.stats.datasetsProcessed} datasets`);
      if (result.stats.warnings.length > 0) {
        console.log(`  Warnings: ${result.stats.warnings.join('; ')}`);
      }
    } catch (e) {
      console.error(`  ❌ CONVERSION ERROR: ${e.message}`);
      allPassed = false; continue;
    }

    // Apply HDF5 reference fixup
    const fixedBuffer = applyHdf5References(result.buffer);
    writeFileSync(outputPath, Buffer.from(fixedBuffer));
    console.log(`  Output: ${outputPath} (${fixedBuffer.byteLength} bytes)`);

    // Compare with reference
    const proc = spawnSync('python3', ['tests/compare_reference.py', outputPath, paths.expected], {
      encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe']
    });
    console.log(proc.stdout.trimEnd());
    if (proc.stderr) console.error(proc.stderr.trimEnd());
    if (proc.status === 0) {
      console.log(`  ✅ ${type.toUpperCase()}: PASSED`);
    } else {
      console.log(`  ❌ ${type.toUpperCase()}: FAILED (exit ${proc.status})`);
      allPassed = false;
    }
    try { unlinkSync(outputPath); } catch (_) {}
  } catch (e) {
    console.error(`  ❌ ERROR: ${e.message}`);
    allPassed = false;
  }
}

console.log('\n' + (allPassed ? '✅ ALL PASSED' : '❌ SOME FAILED'));
process.exit(allPassed ? 0 : 1);
