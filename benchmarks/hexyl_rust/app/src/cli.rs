//! Command-line definition and resolution into a render `Config`.

use std::io::IsTerminal;
use std::path::PathBuf;

use anyhow::{bail, Result};
use clap::{Parser, ValueEnum};

use crate::render::{Base, Border, Config, Table};
use crate::size::{parse_signed, parse_size};

#[derive(Clone, Copy, ValueEnum, Debug, PartialEq, Eq)]
pub enum ColorWhen {
    Always,
    Auto,
    Never,
    Force,
}

#[derive(Clone, Copy, ValueEnum, Debug, PartialEq, Eq)]
pub enum BorderArg {
    Unicode,
    Ascii,
    None,
}

#[derive(Clone, Copy, ValueEnum, Debug, PartialEq, Eq)]
pub enum TableArg {
    Default,
    Ascii,
    Braille,
}

#[derive(Clone, Copy, ValueEnum, Debug, PartialEq, Eq)]
pub enum Endian {
    Little,
    Big,
}

#[derive(Parser, Debug)]
#[command(name = "hexyl", version, about = "A colourful command-line hex viewer")]
pub struct Args {
    /// File to dump (stdin when omitted or `-`)
    pub file: Option<PathBuf>,

    /// Only read N bytes from the input
    #[arg(short = 'n', long = "length", visible_short_aliases = ['c', 'l'], visible_alias = "bytes", value_name = "N")]
    pub length: Option<String>,

    /// Skip the first N bytes (negative: relative to the end)
    #[arg(short = 's', long, value_name = "N", allow_hyphen_values = true)]
    pub skip: Option<String>,

    /// Size of a `block` unit
    #[arg(long, value_name = "SIZE")]
    pub block_size: Option<String>,

    /// Do not replace repeated identical lines by `*`
    #[arg(short = 'v', long)]
    pub no_squeezing: bool,

    /// When to use colours
    #[arg(long, value_enum, default_value = "always", value_name = "WHEN")]
    pub color: ColorWhen,

    /// Border style
    #[arg(long, value_enum, value_name = "STYLE")]
    pub border: Option<BorderArg>,

    /// Plain output: no characters, no position, no border, no colour
    #[arg(short = 'p', long)]
    pub plain: bool,

    /// Do not show the character panel
    #[arg(long, overrides_with = "characters")]
    pub no_characters: bool,

    /// Show the character panel
    #[arg(short = 'C', long, overrides_with = "no_characters")]
    pub characters: bool,

    /// Character table
    #[arg(long, value_enum, default_value = "default", value_name = "TABLE")]
    pub character_table: TableArg,

    /// Do not show the position column
    #[arg(short = 'P', long)]
    pub no_position: bool,

    /// Add N to the displayed offsets
    #[arg(short = 'o', long, value_name = "N", default_value = "0")]
    pub display_offset: String,

    /// Number of panels (N or `auto`)
    #[arg(long, value_name = "N|auto", default_value = "2")]
    pub panels: String,

    /// Bytes per group (1, 2, 4 or 8)
    #[arg(short = 'g', long, value_name = "N", default_value = "1",
          value_parser = clap::builder::PossibleValuesParser::new(["1", "2", "4", "8"]))]
    pub group_size: String,

    /// Byte order inside a group
    #[arg(long, value_enum, default_value = "big", value_name = "ORDER")]
    pub endianness: Endian,

    /// Numeric base: 2, 8, 10, 16 (or binary, octal, decimal, hexadecimal)
    #[arg(short = 'b', long, default_value = "16", value_name = "BASE",
          value_parser = clap::builder::PossibleValuesParser::new(
              ["2", "8", "10", "16", "binary", "octal", "decimal", "hexadecimal"]))]
    pub base: String,

    /// Terminal width used by `--panels auto`
    #[arg(long, value_name = "N")]
    pub terminal_width: Option<usize>,
}

/// Everything the driver needs after resolving the arguments.
pub struct Plan {
    pub config: Config,
    pub skip: i64,
    pub length: Option<u64>,
}

fn detect_terminal_width() -> usize {
    for fd in [1, 2, 0] {
        let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
        // SAFETY: TIOCGWINSZ fills a winsize struct for a valid fd.
        let r = unsafe { libc::ioctl(fd, libc::TIOCGWINSZ, &mut ws) };
        if r == 0 && ws.ws_col > 0 {
            return ws.ws_col as usize;
        }
    }
    if let Some(c) = std::env::var("COLUMNS").ok().and_then(|c| c.parse().ok()) {
        if c > 0 {
            return c;
        }
    }
    80
}

impl Args {
    pub fn resolve(&self) -> Result<Plan> {
        let block = match &self.block_size {
            Some(s) => {
                let b = parse_size(s, None)?;
                if b == 0 {
                    bail!("block size must be positive");
                }
                b
            }
            None => 512,
        };
        let length = self.length.as_deref().map(|s| parse_size(s, Some(block))).transpose()?;
        let skip = self.skip.as_deref().map(|s| parse_signed(s, Some(block))).transpose()?.unwrap_or(0);
        let display_offset = parse_size(&self.display_offset, Some(block))?;

        let group: usize = self.group_size.parse()?;
        let base = match self.base.as_str() {
            "2" | "binary" => Base::Binary,
            "8" | "octal" => Base::Octal,
            "10" | "decimal" => Base::Decimal,
            _ => Base::Hex,
        };

        let border = match self.border {
            Some(BorderArg::Unicode) => Border::Unicode,
            Some(BorderArg::Ascii) => Border::Ascii,
            Some(BorderArg::None) => Border::None,
            None if self.plain => Border::None,
            None => Border::Unicode,
        };
        let show_chars = if self.characters {
            true
        } else if self.no_characters {
            false
        } else {
            !self.plain
        };
        let show_position = !(self.no_position || self.plain);

        let no_color_env = std::env::var_os("NO_COLOR").map_or(false, |v| !v.is_empty());
        let color = match self.color {
            ColorWhen::Force => true,
            ColorWhen::Never => false,
            ColorWhen::Always => !no_color_env,
            ColorWhen::Auto => !no_color_env && std::io::stdout().is_terminal(),
        };
        // `--plain` implies `--color=never`; the default colour mode is overridden by it.
        let color = if self.plain { self.color == ColorWhen::Force } else { color };

        let table = match self.character_table {
            TableArg::Default => Table::Default,
            TableArg::Ascii => Table::Ascii,
            TableArg::Braille => Table::Braille,
        };

        let mut config = Config {
            panels: 1,
            group,
            little_endian: self.endianness == Endian::Little,
            base,
            border,
            color,
            show_position,
            show_chars,
            table,
            squeeze: !self.no_squeezing,
            display_offset,
        };
        config.panels = if self.panels == "auto" {
            let width = self.terminal_width.unwrap_or_else(detect_terminal_width);
            let mut n = 1;
            while config.line_width(n + 1) <= width {
                n += 1;
            }
            n
        } else {
            match self.panels.parse::<usize>() {
                Ok(n) if n >= 1 => n,
                _ => bail!("invalid value '{}' for --panels: expected a positive number or 'auto'", self.panels),
            }
        };
        Ok(Plan { config, skip, length })
    }
}
