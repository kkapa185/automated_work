export interface Options {
	/** @default '-' */
	readonly separator?: string;
	/** @default true */
	readonly lowercase?: boolean;
	/** Split camelCase / acronyms into words. @default true */
	readonly decamelize?: boolean;
	/**
	 * `[from, to]` pairs applied to the original string first. Overrides defaults with the same key.
	 * @default [['&', ' and '], ['🦄', ' unicorn '], ['♥', ' love ']]
	 */
	readonly customReplacements?: ReadonlyArray<readonly [string, string]> | ReadonlyMap<string, string>;
	/** @default false */
	readonly preserveLeadingUnderscore?: boolean;
	/** @default false */
	readonly preserveTrailingDash?: boolean;
	/** Characters kept as-is. Must not include the separator. @default [] */
	readonly preserveCharacters?: readonly string[];
	/** Language-specific transliteration, e.g. `'de'`, `'sv'`, `'da'`, `'nb'`, `'uk'`. */
	readonly locale?: string;
	/** When false, non-ASCII letters and digits are kept. @default true */
	readonly transliterate?: boolean;
}

export interface CounterFunction {
	(string: string, options?: Options): string;
	/** Forget all slugs seen so far. */
	reset(): void;
}

export default function slugify(string: string, options?: Options): string;
export function slugifyWithCounter(): CounterFunction;
