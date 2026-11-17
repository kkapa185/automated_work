import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import slugify from '../index.js';

const t = (input, expected, options) => assert.equal(slugify(input, options), expected);

test('R17 Latin diacritics', () => {
	t('Àéîõü ñ ç', 'aeioue-n-c');
	t('Ærøskøbing Œuvre', 'aeroskobing-oeuvre');
	t('Straße', 'strasse');
	t('Łódź Đà Nẵng', 'lodz-da-nang');
	t('Þór Ðorđe', 'thor-dorde');
	t('Çağrı İstanbul ışık', 'cagri-istanbul-isik');
	t('Şişli Ğ', 'sisli-g');
	t('Mañana', 'manana');
});

test('R17 Vietnamese', () => {
	t('Tiếng Việt', 'tieng-viet');
	t('Nguyễn Thị Ánh', 'nguyen-thi-anh');
	t('Hạnh phúc ơ ư', 'hanh-phuc-o-u');
});

test('R17 Greek', () => {
	t('Ελληνικά', 'ellinika');
	t('Αθήνα', 'athina');
	t('ψυχή θάλασσα χαρά', 'psychi-thalassa-chara');
	t('ΣΟΦΊΑ', 'sofia', undefined);
	t('Σοφία', 'Sofia', {lowercase: false});
});

test('R17 Cyrillic (Russian, Ukrainian, Serbian, Kazakh)', () => {
	t('Щука Ёж Жук', 'shchuka-yozh-zhuk');
	t('Подъезд, объём', 'podezd-obyom');
	t('Їжак Єнот Ґанок', 'yizhak-yenot-ganok');
	t('Ђорђе Љубав Њива Ћир Џем', 'djordje-ljubav-njiva-cir-dzem');
	t('Қазақ Әлем Ұлы Өнер Үй Һәм Ғалым Ңә', 'qazaq-alem-uly-oner-uy-ham-ghalym-nga');
	t('Привет мир', 'Privet-mir', {lowercase: false});
	t('Москва', 'moskva');
});

test('R17 Arabic and Persian', () => {
	t('سلام', 'slam');
	t('مرحبا', 'mrhba');
	t('محمد', 'mhmd');
	t('شكرا', 'shkra');
	t('٠١٢٣٤٥٦٧٨٩', '0123456789');
	t('۰۱۲۳۴۵۶۷۸۹', '0123456789');
	t('پارسی', 'parsy');
	t('چای', 'chay');
	t('گل ژاله', 'gl-zhalh');
	t('كِتَاب', 'ktab');
});

test('R17 Armenian', () => {
	t('Հայաստան', 'Hayastan', {lowercase: false});
	t('շնորհակալություն', 'shnorhakaloutyoun');
	t('Երևան', 'erevan');
});

test('R17 Georgian', () => {
	t('საქართველო', 'sakartvelo');
	t('თბილისი', 'tbilisi');
	t('გამარჯობა', 'gamarjoba');
});

test('R17 Hebrew', () => {
	t('שלום', 'shlvm');
	t('תודה', 'tvdh');
	t('בְּרֵאשִׁית', 'brshyt');
});

test('R17 symbols and fullwidth', () => {
	t('© 2024 ®', 'c-2024-r');
	t('5€', '5euro');
	t('Ｆｕｌｌ １２', 'full-12');
	t('x² + y³', 'x2-y3');
	t('½ cup', '1-2-cup');
	t('naïve ☃ café', 'naive-cafe');
});

test('R17 output is ASCII for transliterated text', () => {
	const corpus = 'Ælfred Ωmega ЖЮК שלום مرحبا Հայ ქართ ½ ™ 日本語 😀 ǅ ẞ ǰ Ǿ ȝ ʼn Ṩ ﬁ';
	for (const lowercase of [true, false]) {
		const out = slugify(corpus, {lowercase});
		assert.match(out, /^[\x00-\x7F]*$/);
		assert.match(out, /^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$/);
	}
});

test('R5 slug shape holds for assorted inputs', () => {
	for (const input of ['a b', '--x--', '__init__', 'Ünïcödé!!', 'A\tB\nC', '😀😀x😀', '\u0000a​b']) {
		const out = slugify(input);
		assert.match(out, /^([a-z0-9]+(-[a-z0-9]+)*)?$/);
	}
});

test('R18 type declarations and manifest', () => {
	const dts = readFileSync(new URL('../index.d.ts', import.meta.url), 'utf8');
	for (const word of ['export default function slugify', 'slugifyWithCounter', 'reset(): void', 'preserveCharacters', 'transliterate', 'locale', 'customReplacements']) {
		assert.ok(dts.includes(word), word);
	}

	const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
	assert.equal(pkg.type, 'module');
	assert.equal(pkg.engines.node, '>=18');
	assert.equal(pkg.types, './index.d.ts');
	assert.equal(pkg.dependencies, undefined);
	assert.match(pkg.scripts.test, /node --test/);
});
