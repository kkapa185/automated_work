import assert from 'node:assert/strict';
import slugify, {slugifyWithCounter} from '../index.js';

assert.equal(slugify('I ♥ Dogs'), 'i-love-dogs');
assert.equal(slugify('я люблю единорогов'), 'ya-lyublyu-edinorogov');
const counter = slugifyWithCounter();
assert.equal(counter('foo'), 'foo');
assert.equal(counter('foo'), 'foo-2');
console.log(slugify(process.argv[2] ?? '  Déjà Vu!  '));
