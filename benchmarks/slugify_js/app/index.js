import {generalTable, localeTables} from './lib/tables.js';

const defaultReplacements = [
	['&', ' and '],
	['🦄', ' unicorn '],
	['♥', ' love '],
];

const APOSTROPHES = new Set(['\'', '’', 'ʼ', '‘', '′']);
const MARKS = /\p{M}/u;

function normalizeReplacements(input) {
	if (input === undefined) {
		return [];
	}

	if (input === null || typeof input !== 'object' || typeof input[Symbol.iterator] !== 'function') {
		throw new TypeError('Expected `customReplacements` to be an array of [from, to] pairs or a Map');
	}

	const pairs = [];
	for (const pair of input) {
		if (!Array.isArray(pair) || pair.length < 2 || typeof pair[0] !== 'string' || typeof pair[1] !== 'string') {
			throw new TypeError('Each `customReplacements` entry must be a [from, to] pair of strings');
		}

		pairs.push([pair[0], pair[1]]);
	}

	return pairs;
}

function mergeReplacements(userPairs) {
	const merged = new Map(defaultReplacements);
	for (const [from, to] of userPairs) {
		merged.set(from, to);
	}

	return [...merged].filter(([from]) => from !== '');
}

function decamelizeString(string) {
	return string
		.replace(/([\p{Ll}\p{N}])(\p{Lu})/gu, '$1 $2')
		.replace(/(\p{Lu}+)(\p{Lu}\p{Ll})/gu, '$1 $2')
		.replace(/(\p{Lu}{2,})(\p{N})/gu, '$1 $2');
}

function languageOf(locale) {
	if (locale === undefined || locale === null || locale === '') {
		return undefined;
	}

	if (typeof locale !== 'string') {
		throw new TypeError('Expected `locale` to be a string');
	}

	return locale.split(/[-_]/)[0].toLowerCase();
}

function transliterateChar(char, localeTable) {
	if (localeTable && Object.hasOwn(localeTable, char)) {
		return localeTable[char];
	}

	if (Object.hasOwn(generalTable, char)) {
		return generalTable[char];
	}

	const code = char.codePointAt(0);
	if (code < 128) {
		return char;
	}

	// Fallback: compatibility decomposition, dropping combining marks.
	let output = '';
	for (const part of char.normalize('NFKD')) {
		if (part === char) {
			output += MARKS.test(part) ? '' : ' ';
		} else if (MARKS.test(part)) {
			// Dropped.
		} else {
			output += transliterateChar(part, localeTable);
		}
	}

	return output;
}

function escapeClass(characters) {
	return characters.replace(/[\\\]^\-[]/g, String.raw`\$&`);
}

export default function slugify(string, options) {
	if (typeof string !== 'string') {
		throw new TypeError(`Expected a string, got \`${typeof string}\``);
	}

	if (options !== undefined && (options === null || typeof options !== 'object' || Array.isArray(options))) {
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
		transliterate = true,
	} = options ?? {};

	if (typeof separator !== 'string') {
		throw new TypeError('Expected `separator` to be a string');
	}

	if (!Array.isArray(preserveCharacters) || preserveCharacters.some(c => typeof c !== 'string')) {
		throw new TypeError('Expected `preserveCharacters` to be an array of strings');
	}

	if (separator !== '' && preserveCharacters.includes(separator)) {
		throw new Error(`The separator \`${separator}\` cannot be included in \`preserveCharacters\``);
	}

	const replacements = mergeReplacements(normalizeReplacements(customReplacements));
	const language = languageOf(locale);
	const localeTable = language ? localeTables[language] : undefined;
	const preserved = new Set(preserveCharacters.flatMap(c => [...c]));

	const endsWithDash = string.endsWith('-');
	const startsWithUnderscore = string.startsWith('_');

	let text = string;
	for (const [from, to] of replacements) {
		text = text.split(from).join(to);
	}

	text = text.normalize('NFC');

	if (decamelize) {
		text = decamelizeString(text);
	}

	let converted = '';
	for (const char of text) {
		if (preserved.has(char)) {
			converted += char;
		} else if (APOSTROPHES.has(char)) {
			// Apostrophes are dropped so that "Conway's" stays one word.
		} else if (transliterate) {
			converted += transliterateChar(char, localeTable);
		} else {
			converted += /[\p{L}\p{N}\p{M}]/u.test(char) ? char : ' ';
		}
	}

	if (lowercase) {
		converted = converted.toLowerCase();
	}

	const extra = escapeClass([...preserved].join(''));
	const wordPattern = transliterate
		? new RegExp(`[a-zA-Z0-9${extra}]+`, 'gu')
		: new RegExp(`[\\p{L}\\p{N}\\p{M}${extra}]+`, 'gu');

	let slug = (converted.match(wordPattern) ?? []).join(separator);

	if (preserveLeadingUnderscore && startsWithUnderscore) {
		slug = `_${slug}`;
	}

	if (preserveTrailingDash && endsWithDash) {
		slug = `${slug}-`;
	}

	return slug;
}

export function slugifyWithCounter() {
	const issued = new Set();
	const counts = new Map();

	const counter = (string, options) => {
		const slug = slugify(string, options);
		if (!issued.has(slug)) {
			issued.add(slug);
			counts.set(slug, 1);
			return slug;
		}

		const separator = options?.separator ?? '-';
		let n = counts.get(slug) ?? 1;
		let candidate;
		do {
			n++;
			candidate = `${slug}${separator}${n}`;
		} while (issued.has(candidate));

		counts.set(slug, n);
		issued.add(candidate);
		counts.set(candidate, 1);
		return candidate;
	};

	counter.reset = () => {
		issued.clear();
		counts.clear();
	};

	return counter;
}
