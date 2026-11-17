import {general} from './tables.js';
import {getLocaleTable} from './locales.js';

const isMark = ch => /^\p{M}$/u.test(ch);

function lookup(ch, locale) {
	const value = locale?.get(ch) ?? general.get(ch);
	if (value !== undefined) {
		return value;
	}

	if (isMark(ch)) {
		return '';
	}

	// Generic fallback: strip diacritics (NFD) and look the base letters up again.
	const decomposed = ch.normalize('NFD');
	if (decomposed !== ch) {
		let result = '';
		for (const part of decomposed) {
			result += part.codePointAt(0) < 128 ? part : lookup(part, locale);
		}

		return result;
	}

	return ' '; // Unknown character: acts as a word boundary.
}

/**
Transliterate to ASCII. Characters in `keep` are left untouched.
Unknown characters become a space.
*/
export default function transliterate(string, {locale, keep = new Set()} = {}) {
	const table = getLocaleTable(locale);
	let output = '';
	for (const ch of string) {
		output += ch.codePointAt(0) < 128 || keep.has(ch) ? ch : lookup(ch, table);
	}

	return output;
}
