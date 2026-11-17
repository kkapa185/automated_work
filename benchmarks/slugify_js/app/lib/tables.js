// Transliteration tables. Specs are space-separated "char:latin" tokens.
// For cased scripts the uppercase letter is derived from the lowercase one
// (value capitalised), unless the uppercase form is ASCII or multi-character.

const capitalize = s => s.charAt(0).toUpperCase() + s.slice(1);

export function build(spec, cased = true, into = new Map()) {
	for (const token of spec.split(/\s+/).filter(Boolean)) {
		const index = token.lastIndexOf(':');
		const ch = token.slice(0, index);
		const value = token.slice(index + 1);
		into.set(ch, value);
		if (cased) {
			const upper = ch.toUpperCase();
			if (upper !== ch && [...upper].length === 1 && upper.codePointAt(0) > 127) {
				into.set(upper, capitalize(value));
			}
		}
	}

	return into;
}

const latin = `ä:ae ö:oe ü:ue ß:ss æ:ae œ:oe ø:o å:a þ:th ð:d đ:d ł:l ı:i ĳ:ij ŋ:ng ſ:s ƒ:f ħ:h ŧ:t
ǆ:dz ǉ:lj ǌ:nj ĸ:k ŉ:n ə:e ɛ:e ɔ:o ʼ:`;

const greek = `α:a β:v γ:g δ:d ε:e ζ:z η:i θ:th ι:i κ:k λ:l μ:m ν:n ξ:x ο:o π:p ρ:r σ:s ς:s τ:t υ:y φ:f χ:ch ψ:ps ω:o`;

const cyrillic = `а:a б:b в:v г:g д:d е:e ё:yo ж:zh з:z и:i й:y к:k л:l м:m н:n о:o п:p р:r с:s т:t у:u ф:f х:kh ц:ts ч:ch ш:sh щ:shch ъ: ы:y ь: э:e ю:yu я:ya
є:ye і:i ї:yi ґ:g ў:u
ђ:dj ј:j љ:lj њ:nj ћ:c џ:dz ѓ:gj ќ:kj ѕ:dz
ә:a ғ:gh қ:q ң:ng ө:o ұ:u ү:u һ:h ҝ:k ҙ:z ӣ:i ӯ:u ҷ:j ҳ:h ӈ:ng`;

const armenian = `ա:a բ:b գ:g դ:d ե:e զ:z է:e ը:e թ:t ժ:zh ի:i լ:l խ:kh ծ:ts կ:k հ:h ձ:dz ղ:gh ճ:ch մ:m յ:y ն:n շ:sh ո:o չ:ch պ:p ջ:j ռ:r ս:s վ:v տ:t ր:r ց:ts ւ:u փ:p ք:q օ:o ֆ:f և:ev`;

const georgian = `ა:a ბ:b გ:g დ:d ე:e ვ:v ზ:z თ:t ი:i კ:k ლ:l მ:m ნ:n ო:o პ:p ჟ:zh რ:r ს:s ტ:t უ:u ფ:p ქ:k ღ:gh ყ:q შ:sh ჩ:ch ც:ts ძ:dz წ:ts ჭ:ch ხ:kh ჯ:j ჰ:h`;

const hebrew = `א: ב:b ג:g ד:d ה:h ו:v ז:z ח:kh ט:t י:y ך:kh כ:k ל:l ם:m מ:m ן:n נ:n ס:s ע: ף:f פ:p ץ:ts צ:ts ק:k ר:r ש:sh ת:t װ:v ײ:y`;

const arabic = `ا:a أ:a إ:i آ:a ٱ:a ء: ب:b ت:t ث:th ج:j ح:h خ:kh د:d ذ:dh ر:r ز:z س:s ش:sh ص:s ض:d ط:t ظ:z ع: غ:gh ف:f ق:q ك:k ل:l م:m ن:n ه:h و:w ي:y ى:a ة:h ئ: ؤ: ـ:
پ:p چ:ch ژ:zh گ:g ک:k ی:y ڤ:v ڨ:g ں:n ھ:h ہ:h ۀ:h ے:y ٹ:t ڈ:d ڑ:r`;

const symbols = {
	'©': 'c', '®': 'r', '™': 'tm', '€': 'euro', '£': 'pound', '¥': 'yen', '¢': 'cent',
	'°': 'deg', '×': 'x', 'µ': 'u', 'ª': 'a', 'º': 'o', '¹': '1', '²': '2', '³': '3',
	'½': ' 1 2 ', '¼': ' 1 4 ', '¾': ' 3 4 ', '⅓': ' 1 3 ', '⅔': ' 2 3 ',
	'№': 'no', '℃': ' c ', '℉': ' f ', '‰': ' permille ', '∞': ' infinity ', '＆': ' and '
};

export const general = new Map();
build(latin, true, general);
build(greek, true, general);
build(cyrillic, true, general);
build(armenian, true, general);
build(georgian, true, general);
build(hebrew, false, general);
build(arabic, false, general);
general.set('ẞ', 'Ss');
general.set('ǅ', 'Dz');
for (const [key, value] of Object.entries(symbols)) {
	general.set(key, value);
}

// Digits: Arabic-Indic, Extended Arabic-Indic (Persian), fullwidth forms.
for (let i = 0; i < 10; i++) {
	general.set(String.fromCodePoint(0x660 + i), String(i));
	general.set(String.fromCodePoint(0x6F0 + i), String(i));
	general.set(String.fromCodePoint(0xFF10 + i), String(i));
}

for (let i = 0; i < 26; i++) {
	general.set(String.fromCodePoint(0xFF21 + i), String.fromCodePoint(65 + i));
	general.set(String.fromCodePoint(0xFF41 + i), String.fromCodePoint(97 + i));
}
