// tests/run_converter_test.mjs — Node.js runner that tests the converter against reference files
import { readFileSync, writeFileSync, unlinkSync } from 'fs';
import { spawnSync } from 'child_process';
import h5wasm from 'h5wasm/node';

// Setup global h5wasm (our converter expects it)
globalThis.h5wasm = h5wasm;
await h5wasm.ready;
globalThis.__h5wasmReady = true;

// Dynamically import our converter
const { convert } = await import('../src/converter.js');

// Test all three reference types
const tests = ['ut', 'pa', 'tfm'];
let allPassed = true;

for (const type of tests) {
    const ndePath = `tests/fixtures/reference_${type}.nde`;
    const expectedPath = `tests/fixtures/reference_${type}_expected.onde`;
    const outputPath = `/tmp/converter_test_${type}.onde`;

    console.log(`\n═══ Testing ${type.toUpperCase()} — NDE → ONDE ═══`);

    try {
        // Read NDE file
        const ndeBuf = readFileSync(ndePath);
        console.log(`  Input: ${ndePath} (${ndeBuf.length} bytes)`);

        // Run converter
        let result;
        try {
            result = await convert(ndeBuf.buffer);
            console.log(`  Converted: ${result.format}, ${result.stats.datasetsProcessed} datasets, ${result.stats.groupsProcessed} groups`);
            if (result.stats.warnings.length > 0) {
                console.log(`  Warnings: ${result.stats.warnings.join('; ')}`);
            }
        } catch (e) {
            console.error(`  ❌ CONVERSION ERROR: ${e.message}`);
            allPassed = false;
            continue;
        }

        // Write output
        writeFileSync(outputPath, Buffer.from(result.buffer));
        console.log(`  Output written: ${outputPath} (${result.buffer.byteLength} bytes)`);

        // Compare with Python reference checker
        const proc = spawnSync('python3', [
            'tests/compare_reference.py',
            outputPath,
            expectedPath
        ], {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe']
        });

        console.log(proc.stdout.trimEnd());
        if (proc.stderr) console.error(proc.stderr.trimEnd());

        if (proc.status === 0) {
            console.log(`  ✅ ${type.toUpperCase()}: PASSED`);
        } else {
            console.log(`  ❌ ${type.toUpperCase()}: FAILED (exit ${proc.status})`);
            allPassed = false;
        }

        // Clean up
        try { unlinkSync(outputPath); } catch (_) {}

    } catch (e) {
        console.error(`  ❌ TEST ERROR: ${e.message}`);
        console.error(e.stack);
        allPassed = false;
    }
}

console.log('\n══════════════════════════════════════');
if (allPassed) {
    console.log('  ALL TESTS PASSED ✅');
    process.exit(0);
} else {
    console.log('  SOME TESTS FAILED ❌');
    process.exit(1);
}
