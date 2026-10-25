// Check the binary contract expected by Tree-sitter's dynamic WASM loader.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const manifest = JSON.parse(readFileSync('tree-sitter.json', 'utf8'));
for (const { name } of manifest.grammars) {
    const bytes = readFileSync(join(process.argv[2], `${name}.wasm`));
    assert.ok(WebAssembly.validate(bytes), 'invalid WebAssembly module');
    const module = new WebAssembly.Module(bytes);
    assert.ok(
        WebAssembly.Module.exports(module).some(
            item => item.name === `tree_sitter_${name}` && item.kind === 'function',
        ),
    );
    assert.equal(WebAssembly.Module.customSections(module, 'dylink.0').length, 1);
    if (name === 'repl') {
        // Scanner callbacks are referenced through the language's function table.
        // Its allocation imports must resolve in Tree-sitter's external-scanner stdlib.
        const functions = WebAssembly.Module.imports(module).filter(item => item.kind === 'function');
        const supported = new Set(['calloc', 'free', 'memcpy', 'memset']);
        assert.ok(functions.every(item => item.module === 'env' && supported.has(item.name)));
        assert.ok(functions.some(item => item.name === 'calloc'));
        assert.ok(functions.some(item => item.name === 'free'));
    }
    console.log(`WASM validates and exports the ${name} grammar with dynamic linking metadata`);
}
