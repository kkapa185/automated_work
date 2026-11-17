import {build} from './tables.js';

// Language-specific overrides applied on top of the general table.
const specs = {
	de: 'ä:ae ö:oe ü:ue ß:ss',
	da: 'ä:ae ö:oe ü:ue æ:ae ø:oe å:aa',
	nb: 'ä:ae ö:o æ:ae ø:o å:a',
	nn: 'ä:ae ö:o æ:ae ø:o å:a',
	no: 'ä:ae ö:o æ:ae ø:o å:a',
	sv: 'ä:a ö:o å:a ü:u æ:ae ø:o',
	fi: 'ä:a ö:o å:a ü:u',
	et: 'ä:a ö:o õ:o ü:u',
	is: 'þ:th ð:d æ:ae ö:o',
	tr: 'ç:c ğ:g ı:i ö:o ş:s ü:u İ:i',
	az: 'ç:c ğ:g ı:i ə:e ö:o ş:s ü:u',
	hu: 'ö:o ü:u ő:o ű:u',
	ru: 'х:kh ц:ts ч:ch ш:sh щ:shch ю:yu я:ya й:i ы:y э:e',
	uk: 'г:h ґ:g е:e є:ie и:y і:i ї:i й:i х:kh ц:ts щ:shch ю:iu я:ia',
	be: 'г:h ў:u і:i',
	bg: 'ъ:a щ:sht ю:yu я:ya й:y х:h ц:ts',
	sr: 'ђ:dj ј:j љ:lj њ:nj ћ:c џ:dz х:h',
	mk: 'ѓ:gj ќ:kj ѕ:dz ј:j љ:lj њ:nj џ:dz х:h',
	kk: 'ә:a ғ:g қ:k ң:n ө:o ұ:u ү:u һ:h і:i',
	el: 'β:v γ:g η:i υ:y χ:ch'
};

const cache = new Map();

/** Resolve a locale tag ('sv', 'sv-SE', 'sv_SE') to an override Map, or undefined. */
export function getLocaleTable(locale) {
	if (typeof locale !== 'string' || locale === '') {
		return undefined;
	}

	const tag = locale.toLowerCase().replaceAll('_', '-');
	const key = [tag, tag.split('-')[0]].find(candidate => candidate in specs);
	if (key === undefined) {
		return undefined;
	}

	if (!cache.has(key)) {
		cache.set(key, build(specs[key]));
	}

	return cache.get(key);
}
