// Check the binary contract expected by Tree-sitter's dynamic WASM loader.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const bytes = readFileSync(process.argv[2]);
assert.ok(WebAssembly.validate(bytes), 'invalid WebAssembly module');
const module = new WebAssembly.Module(bytes);
assert.ok(
    WebAssembly.Module.exports(module).some(item => item.name === 'tree_sitter_resc' && item.kind === 'function'),
);
assert.equal(WebAssembly.Module.customSections(module, 'dylink.0').length, 1);
console.log('WASM validates and exports the resc grammar with dynamic linking metadata');
