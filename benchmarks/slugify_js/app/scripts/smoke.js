import slugify, {slugifyWithCounter} from '../index.js';

const results = [
	[slugify('I ♥ Dogs'), 'i-love-dogs'],
	[slugify('я люблю единорогов'), 'ya-lyublyu-edinorogov']
];
const counter = slugifyWithCounter();
results.push([counter('foo bar') + counter('foo bar'), 'foo-barfoo-bar-2']);

for (const [actual, expected] of results) {
	if (actual !== expected) {
		console.error(`FAIL: ${actual} !== ${expected}`);
		process.exit(1);
	}
}

console.log('smoke ok');
