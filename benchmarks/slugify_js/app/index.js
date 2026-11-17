import transliterate from './lib/transliterate.js';

const defaultReplacements = [
	['&', ' and '],
	['🦄', ' unicorn '],
	['♥', ' love ']
];

const escapeRegex = string => string.replaceAll(/[\\^$.*+?()[\]{}|/-]/g, String.raw`\$&`);

function buildReplacements(custom) {
	const map = new Map(defaultReplacements);
	if (custom !== undefined) {
		if (custom === null || typeof custom[Symbol.iterator] !== 'function') {
			throw new TypeError('Expected `customReplacements` to be an array of [from, to] pairs');
		}

		for (const pair of custom) {
			if (!pair || typeof pair[0] !== 'string' || typeof pair[1] !== 'string') {
				throw new TypeError('Expected each custom replacement to be a [string, string] pair');
			}

			map.set(pair[0].normalize('NFC'), pair[1]);
		}
	}

	map.delete('');
	if (map.size === 0) {
		return string => string;
	}

	// Single pass, longest key first: replacement output is never re-replaced.
	const keys = [...map.keys()].sort((a, b) => b.length - a.length);
	const regex = new RegExp(keys.map(key => escapeRegex(key)).join('|'), 'gu');
	return string => string.replace(regex, match => map.get(match));
}

function decamelizeString(string) {
	return string
		.replaceAll(/([\p{Ll}\p{N}])(\p{Lu})/gu, '$1 $2') // FooBar -> Foo Bar, foo360BAR -> foo360 BAR
		.replaceAll(/(\p{Lu}+)(\p{Lu}\p{Ll})/gu, '$1 $2') // APISection -> API Section
		.replaceAll(/(\p{Lu}{2,})(\p{N})/gu, '$1 $2'); // FOO360 -> FOO 360
}

export default function slugify(string, options) {
	if (typeof string !== 'string') {
		throw new TypeError(`Expected a string, got \`${typeof string}\``);
	}

	if (options !== undefined && (options === null || typeof options !== 'object')) {
		throw new TypeError('Expected `options` to be an object');
	}

	const {
		separator = '-',
		lowercase = true,
		decamelize = true,
		customReplacements,
		preserveLeadingUnderscore = false,
		preserveTrailingDash = false,
		preserveCharacters = [],
		locale,
		transliterate: shouldTransliterate = true
	} = options ?? {};

	if (typeof separator !== 'string') {
		throw new TypeError('Expected `separator` to be a string');
	}

	if (!Array.isArray(preserveCharacters)) {
		throw new TypeError('Expected `preserveCharacters` to be an array of strings');
	}

	const preserved = new Set();
	for (const character of preserveCharacters) {
		if (typeof character !== 'string') {
			throw new TypeError('Expected `preserveCharacters` to be an array of strings');
		}

		const normalized = character.normalize('NFC');
		if (separator !== '' && normalized !== '' && separator.includes(normalized)) {
			throw new Error('The `separator` option cannot be included in `preserveCharacters`');
		}

		if (normalized !== '') {
			preserved.add(normalized);
		}
	}

	const original = string.normalize('NFC');
	let text = buildReplacements(customReplacements)(original);

	if (decamelize) {
		text = decamelizeString(text);
	}

	// Apostrophes inside words are removed rather than treated as separators.
	if (preserved.has('\'') || preserved.has('’')) {
		// Preserved apostrophes survive, except word-final 's / 't.
		text = text.replaceAll(/(?<=[\p{L}\p{N}])['’](?=[st](?![\p{L}\p{N}]))/gu, '');
	} else {
		text = text.replaceAll(/(?<=[\p{L}\p{N}])['’](?=[\p{L}\p{N}])/gu, '');
	}

	if (shouldTransliterate) {
		text = transliterate(text, {locale, keep: preserved});
	}

	if (lowercase) {
		text = text.toLowerCase();
	}

	const extra = [...preserved].map(character => escapeRegex(character)).join('');
	const allowed = shouldTransliterate ? 'a-zA-Z0-9' : String.raw`\p{L}\p{N}\p{M}`;
	const splitter = new RegExp(`[^${allowed}${extra}]+`, 'u');

	let slug = text.split(splitter).filter(Boolean).join(separator);

	if (slug !== '') {
		if (preserveLeadingUnderscore && original.startsWith('_')) {
			slug = `_${slug}`;
		}

		if (preserveTrailingDash && original.endsWith('-') && !slug.endsWith('-')) {
			slug += '-';
		}
	}

	return slug;
}

export {slugify};

export function slugifyWithCounter() {
	let used = new Set();
	let counts = new Map();

	const counted = (string, options) => {
		const base = slugify(string, options);
		const separator = options?.separator ?? '-';
		let slug = base;

		if (used.has(slug)) {
			let count = counts.get(base) ?? 1;
			do {
				count++;
				slug = `${base}${separator}${count}`;
			} while (used.has(slug));

			counts.set(base, count);
		}

		used.add(slug);
		return slug;
	};

	counted.reset = () => {
		used = new Set();
		counts = new Map();
	};

	return counted;
}
