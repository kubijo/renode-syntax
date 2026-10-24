// Compile every translated expression with its declared JavaScript flags. Source extraction and
// translation live in Python; this small bridge checks the actual consumer engine.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const data = JSON.parse(readFileSync(process.argv[2], 'utf8'));
assert.ok(Array.isArray(data.tokenizer));
assert.ok(data.tokenizer.length > 0);
for (const rule of data.tokenizer) {
    assert.equal(typeof rule.javascript, 'string');
    assert.equal(rule.javascript_flags, 'u');
    const pattern = new RegExp(`^(?:${rule.javascript})`, rule.javascript_flags);
    assert.ok(!pattern.test(''), `${rule.kind}: token may not match an empty string`);
    if (rule.kind === 'HexToken') {
        assert.equal(pattern.exec('0xAb1')?.[0], '0xAb1');
        assert.equal(pattern.exec('0xG'), null);
    }
    if (rule.kind === 'VariableToken') {
        assert.equal(pattern.exec('$global.name')?.[0], '$global.name');
        assert.equal(pattern.exec('$é'), null);
    }
    if (rule.kind === 'DecimalIntegerToken') {
        assert.equal(pattern.exec('١٢٣')?.[0], '١٢٣');
    }
    if (rule.kind === 'Whitespace') {
        assert.equal(pattern.exec('\u0085')?.[0], '\u0085');
        assert.equal(pattern.exec('\uFEFF'), null);
    }
}
console.log(`${data.tokenizer.length} translated JavaScript regexes compile; consumer probes pass`);
