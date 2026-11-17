//! Parsing of byte-count arguments (`16`, `0x10`, `2KiB`, `3block`, ...).

use anyhow::{anyhow, bail, Result};

const UNITS: &[(&str, u64)] = &[
    ("KiB", 1024),
    ("MiB", 1024 * 1024),
    ("GiB", 1024 * 1024 * 1024),
    ("kB", 1000),
    ("MB", 1_000_000),
    ("GB", 1_000_000_000),
];

/// Parse a non-negative size. `block` is the multiplier of the `block` unit
/// (`None` when `block` is not allowed, e.g. for `--block-size` itself).
pub fn parse_size(input: &str, block: Option<u64>) -> Result<u64> {
    let s = input.trim();
    if s.is_empty() {
        bail!("empty number");
    }
    let mut mult = 1u64;
    let mut num = s;
    if let Some(rest) = s.strip_suffix("block") {
        mult = block.ok_or_else(|| anyhow!("unit 'block' is not allowed here: '{input}'"))?;
        num = rest;
    } else {
        for (suffix, m) in UNITS {
            if let Some(rest) = s.strip_suffix(suffix) {
                mult = *m;
                num = rest;
                break;
            }
        }
    }
    let num = num.trim();
    let value = if let Some(hex) = num.strip_prefix("0x").or_else(|| num.strip_prefix("0X")) {
        u64::from_str_radix(hex, 16)
    } else {
        num.parse::<u64>()
    }
    .map_err(|_| anyhow!("invalid number '{input}'"))?;
    value
        .checked_mul(mult)
        .ok_or_else(|| anyhow!("number '{input}' is too large"))
}

/// Parse a possibly negative size (used by `--skip`).
pub fn parse_signed(input: &str, block: Option<u64>) -> Result<i64> {
    let s = input.trim();
    let (neg, rest) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s),
    };
    let v = parse_size(rest, block)?;
    let v = i64::try_from(v).map_err(|_| anyhow!("number '{input}' is too large"))?;
    Ok(if neg { -v } else { v })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_and_hex() {
        assert_eq!(parse_size("42", None).unwrap(), 42);
        assert_eq!(parse_size("0x1f", None).unwrap(), 31);
        assert_eq!(parse_size("0x1B", None).unwrap(), 27);
    }

    #[test]
    fn units() {
        assert_eq!(parse_size("2kB", None).unwrap(), 2000);
        assert_eq!(parse_size("3MB", None).unwrap(), 3_000_000);
        assert_eq!(parse_size("1GB", None).unwrap(), 1_000_000_000);
        assert_eq!(parse_size("2KiB", None).unwrap(), 2048);
        assert_eq!(parse_size("1MiB", None).unwrap(), 1_048_576);
        assert_eq!(parse_size("1GiB", None).unwrap(), 1_073_741_824);
        assert_eq!(parse_size("0x10KiB", None).unwrap(), 16384);
    }

    #[test]
    fn block() {
        assert_eq!(parse_size("3block", Some(512)).unwrap(), 1536);
        assert!(parse_size("3block", None).is_err());
    }

    #[test]
    fn errors() {
        assert!(parse_size("", None).is_err());
        assert!(parse_size("abc", None).is_err());
        assert!(parse_size("-1", None).is_err());
        assert!(parse_size("99999999999999999999", None).is_err());
        assert!(parse_size("0xZZ", None).is_err());
    }

    #[test]
    fn signed() {
        assert_eq!(parse_signed("-16", None).unwrap(), -16);
        assert_eq!(parse_signed("-1KiB", None).unwrap(), -1024);
        assert_eq!(parse_signed("8", None).unwrap(), 8);
    }
}
