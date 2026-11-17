// Transliteration tables. Values are ASCII. Upper-case variants of single-letter
// keys are derived automatically (see `withCase`) unless given explicitly.

function withCase(table) {
	const result = {...table};
	for (const [key, value] of Object.entries(table)) {
		const upper = key.toUpperCase();
		if (upper !== key && [...upper].length === 1 && !(upper in result)) {
			result[upper] = value.length > 0 ? value[0].toUpperCase() + value.slice(1) : '';
		}
	}

	return result;
}

// Latin letters that do not decompose under NFD (the rest is handled by
// stripping combining marks, which covers German, Scandinavian, Vietnamese,
// Turkish, Czech, Polish, ...).
const latin = withCase({
	ß: 'ss', ẞ: 'SS', æ: 'ae', Æ: 'AE', œ: 'oe', Œ: 'OE', ø: 'o', Ø: 'O',
	đ: 'd', Đ: 'D', ð: 'd', Ð: 'D', þ: 'th', Þ: 'Th', ł: 'l', Ł: 'L',
	ı: 'i', ĸ: 'k', ŋ: 'ng', ħ: 'h', ŧ: 't', ƒ: 'f', ſ: 's', ĳ: 'ij', Ĳ: 'IJ',
	ŉ: 'n', ə: 'e', Ə: 'E', ɗ: 'd', ƀ: 'b', ɓ: 'b', ƈ: 'c', ƙ: 'k', ƥ: 'p', ƭ: 't',
	ƴ: 'y', ȷ: 'j', ǝ: 'e', ᵽ: 'p', ɨ: 'i', ʉ: 'u', ɱ: 'm', ɲ: 'n',
	ª: 'a', º: 'o', '¹': '1', '²': '2', '³': '3',
});

const symbols = {
	'€': ' euro ', '£': ' pound ', '¥': ' yen ', '¢': ' cent ', '₹': ' rupee ',
	'₩': ' won ', '₽': ' ruble ', '₺': ' lira ', '₴': ' hryvnia ', '₪': ' shekel ',
	'₫': ' dong ', '฿': ' baht ', '₿': ' bitcoin ', '™': ' ', '℠': ' ', '©': ' ', '®': ' ',
	'½': ' 1 2 ', '¼': ' 1 4 ', '¾': ' 3 4 ',
	'×': ' x ', 'ǀ': ' ',
	'٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
	'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
};

const greek = withCase({
	α: 'a', β: 'v', γ: 'g', δ: 'd', ε: 'e', ζ: 'z', η: 'i', θ: 'th', ι: 'i', κ: 'k',
	λ: 'l', μ: 'm', ν: 'n', ξ: 'x', ο: 'o', π: 'p', ρ: 'r', σ: 's', ς: 's', τ: 't',
	υ: 'y', φ: 'f', χ: 'ch', ψ: 'ps', ω: 'o',
});

const cyrillic = withCase({
	// Russian
	а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'yo', ж: 'zh', з: 'z', и: 'i',
	й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
	у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch', ъ: '', ы: 'y', ь: '',
	э: 'e', ю: 'yu', я: 'ya',
	// Ukrainian / Belarusian
	і: 'i', ї: 'yi', є: 'ye', ґ: 'g', ў: 'u',
	// Serbian / Macedonian
	ђ: 'dj', ј: 'j', љ: 'lj', њ: 'nj', ћ: 'c', џ: 'dz', ѓ: 'g', ќ: 'k', ѕ: 'dz',
	// Kazakh and other Turkic-style letters
	ә: 'a', ғ: 'gh', қ: 'q', ң: 'ng', ө: 'o', ұ: 'u', ү: 'u', һ: 'h', ҳ: 'h', ҷ: 'j', ӣ: 'i', ӯ: 'u',
});

const arabic = {
	ا: 'a', أ: 'a', إ: 'i', آ: 'a', ٱ: 'a', ء: '', ب: 'b', ت: 't', ث: 'th', ج: 'j', ح: 'h',
	خ: 'kh', د: 'd', ذ: 'dh', ر: 'r', ز: 'z', س: 's', ش: 'sh', ص: 's', ض: 'd', ط: 't',
	ظ: 'z', ع: 'a', غ: 'gh', ف: 'f', ق: 'q', ك: 'k', ل: 'l', م: 'm', ن: 'n', ه: 'h',
	و: 'w', ي: 'y', ى: 'a', ة: 'h', ئ: '', ؤ: '', ـ: '',
	// Persian additions
	پ: 'p', چ: 'ch', ژ: 'zh', گ: 'g', ک: 'k', ی: 'y', ڤ: 'v', ۀ: 'h', ە: 'e',
};

const armenian = withCase({
	ա: 'a', բ: 'b', գ: 'g', դ: 'd', ե: 'e', զ: 'z', է: 'e', ը: 'y', թ: 't', ժ: 'zh',
	ի: 'i', լ: 'l', խ: 'kh', ծ: 'ts', կ: 'k', հ: 'h', ձ: 'dz', ղ: 'gh', ճ: 'ch', մ: 'm',
	յ: 'y', ն: 'n', շ: 'sh', ո: 'o', չ: 'ch', պ: 'p', ջ: 'j', ռ: 'r', ս: 's', վ: 'v',
	տ: 't', ր: 'r', ց: 'ts', ւ: 'u', փ: 'p', ք: 'k', օ: 'o', ֆ: 'f', և: 'ev',
});

const georgian = {
	ა: 'a', ბ: 'b', გ: 'g', დ: 'd', ე: 'e', ვ: 'v', ზ: 'z', თ: 't', ი: 'i', კ: 'k',
	ლ: 'l', მ: 'm', ნ: 'n', ო: 'o', პ: 'p', ჟ: 'zh', რ: 'r', ს: 's', ტ: 't', უ: 'u',
	ფ: 'p', ქ: 'k', ღ: 'gh', ყ: 'q', შ: 'sh', ჩ: 'ch', ც: 'ts', ძ: 'dz', წ: 'ts', ჭ: 'ch',
	ხ: 'kh', ჯ: 'j', ჰ: 'h',
};
// Georgian Mtavruli capitals (U+1C90..U+1CBA) map like their lower-case forms.
for (const [key, value] of Object.entries({...georgian})) {
	const upper = key.toUpperCase();
	if (upper !== key) {
		georgian[upper] = value;
	}
}

const hebrew = {
	א: '', ב: 'b', ג: 'g', ד: 'd', ה: 'h', ו: 'v', ז: 'z', ח: 'kh', ט: 't', י: 'y',
	כ: 'k', ך: 'kh', ל: 'l', מ: 'm', ם: 'm', נ: 'n', ן: 'n', ס: 's', ע: '', פ: 'p',
	ף: 'f', צ: 'ts', ץ: 'ts', ק: 'k', ר: 'r', ש: 'sh', ת: 't', װ: 'vv', ײ: 'yy',
};

export const generalTable = Object.freeze({
	...latin, ...symbols, ...greek, ...cyrillic, ...arabic, ...armenian, ...georgian, ...hebrew,
});

// Language-specific overrides, keyed by primary language subtag.
const nordic = withCase({å: 'aa', æ: 'ae', ø: 'oe'});
export const localeTables = Object.freeze({
	de: withCase({ä: 'ae', ö: 'oe', ü: 'ue'}),
	sv: withCase({å: 'aa', ä: 'ae', ö: 'oe'}),
	da: nordic,
	nb: nordic,
	nn: nordic,
	no: nordic,
	fi: withCase({å: 'aa', ä: 'ae', ö: 'oe'}),
	uk: withCase({г: 'h', и: 'y', х: 'kh', щ: 'shch', ґ: 'g'}),
	bg: withCase({щ: 'sht', ъ: 'a', ь: 'y'}),
});
