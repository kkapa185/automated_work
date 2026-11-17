export type Options = {
	/** @default '-' */
	readonly separator?: string;
	/** @default true */
	readonly lowercase?: boolean;
	/** Convert camelcase to separate words (`fooBar` → `foo bar`). @default true */
	readonly decamelize?: boolean;
	/**
	Custom `[from, to]` replacements run on the original string before decamelization and transliteration.
	@default [['&', ' and '], ['🦄', ' unicorn '], ['♥', ' love ']]
	*/
	readonly customReplacements?: ReadonlyArray<readonly [string, string]> | Iterable<readonly [string, string]>;
	/** @default false */
	readonly preserveLeadingUnderscore?: boolean;
	/** @default false */
	readonly preserveTrailingDash?: boolean;
	/** Characters to keep as-is. Cannot contain the `separator`. @default [] */
	readonly preserveCharacters?: readonly string[];
	/** Locale for language-specific transliteration, for example `'sv'`. */
	readonly locale?: string;
	/** Transliterate Unicode to ASCII. @default true */
	readonly transliterate?: boolean;
};

export type CountableSlugify = {
	(string: string, options?: Options): string;
	/** Reset the counter. */
	reset(): void;
};

/** Slugify a string. Throws `TypeError` for non-string input. */
export default function slugify(string: string, options?: Options): string;
export {slugify};

/** Returns a `slugify` that appends `-2`, `-3`, ... to repeated slugs. */
export function slugifyWithCounter(): CountableSlugify;
