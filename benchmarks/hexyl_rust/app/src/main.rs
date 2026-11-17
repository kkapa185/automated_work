use anyhow::{anyhow, bail, Context, Result};
use clap::{Parser, ValueEnum};
use hexyl::*;
use std::fs::File;
use std::io::{BufWriter, IsTerminal, Read, Seek, SeekFrom};
use std::path::PathBuf;

#[derive(Clone, Copy, ValueEnum)]
enum ColorWhen {
    Always,
    Auto,
    Never,
    Force,
}

#[derive(Clone, Copy, ValueEnum)]
enum Border {
    Unicode,
    Ascii,
    None,
}

#[derive(Clone, Copy, ValueEnum)]
enum Table {
    Default,
    Ascii,
    Braille,
}

#[derive(Clone, Copy, ValueEnum)]
enum Endian {
    Little,
    Big,
}

#[derive(Parser)]
#[command(name = "hexyl", version, about = "A command-line hex viewer")]
struct Opts {
    /// File to display; stdin if omitted or `-`
    file: Option<PathBuf>,

    /// Only read N bytes from the input
    #[arg(short = 'n', long = "length", visible_short_aliases = ['c', 'l'], visible_alias = "bytes", value_name = "N")]
    length: Option<String>,

    /// Skip the first N bytes (negative: relative to the end)
    #[arg(short = 's', long = "skip", value_name = "N", allow_hyphen_values = true)]
    skip: Option<String>,

    /// Size of a `block` unit (default 512)
    #[arg(long = "block-size", value_name = "SIZE")]
    block_size: Option<String>,

    /// Display all lines, do not squeeze repeated ones
    #[arg(short = 'v', long = "no-squeezing")]
    no_squeezing: bool,

    /// When to use colors
    #[arg(long, value_enum, default_value = "always")]
    color: ColorWhen,

    /// Border style
    #[arg(long, value_enum, default_value = "unicode")]
    border: Border,

    /// Plain output: no characters, no position, no border, no color
    #[arg(short = 'p', long)]
    plain: bool,

    /// Do not show the character panel
    #[arg(long = "no-characters")]
    no_characters: bool,

    /// Show the character panel
    #[arg(short = 'C', long = "characters")]
    characters: bool,

    /// Character table
    #[arg(long = "character-table", value_enum, default_value = "default")]
    character_table: Table,

    /// Do not show the position column
    #[arg(short = 'P', long = "no-position")]
    no_position: bool,

    /// Add N to the displayed offsets
    #[arg(short = 'o', long = "display-offset", value_name = "N")]
    display_offset: Option<String>,

    /// Number of 8-byte panels, or `auto`
    #[arg(long, value_name = "N|auto", default_value = "2")]
    panels: String,

    /// Bytes per group (1, 2, 4, 8)
    #[arg(short = 'g', long = "group-size", default_value_t = 1, value_parser = parse_group)]
    group_size: usize,

    /// Byte order within a group
    #[arg(long, value_enum, default_value = "big")]
    endianness: Endian,

    /// Number base: 2, 8, 10, 16, binary, octal, decimal, hexadecimal
    #[arg(short = 'b', long, default_value = "16", value_parser = parse_base)]
    base: Base,

    /// Terminal width used by --panels auto
    #[arg(long = "terminal-width", value_name = "N")]
    terminal_width: Option<usize>,
}

fn parse_group(s: &str) -> Result<usize, String> {
    match s {
        "1" | "2" | "4" | "8" => Ok(s.parse().unwrap()),
        _ => Err(format!("invalid group size '{}' (expected 1, 2, 4 or 8)", s)),
    }
}

fn parse_base(s: &str) -> Result<Base, String> {
    match s.to_ascii_lowercase().as_str() {
        "2" | "binary" => Ok(Base::Binary),
        "8" | "octal" => Ok(Base::Octal),
        "10" | "decimal" => Ok(Base::Decimal),
        "16" | "hexadecimal" => Ok(Base::Hexadecimal),
        _ => Err(format!("invalid base '{}'", s)),
    }
}

fn run() -> Result<()> {
    let o = Opts::parse();
    let block_size = match &o.block_size {
        Some(s) => {
            let v = parse_size(s, 512).with_context(|| format!("invalid --block-size '{}'", s))?;
            if v == 0 {
                bail!("--block-size must be positive");
            }
            v
        }
        None => 512,
    };
    let length = match &o.length {
        Some(s) => Some(parse_size(s, block_size).with_context(|| format!("invalid length '{}'", s))?),
        None => None,
    };
    let skip: Option<(bool, u64)> = match &o.skip {
        Some(s) => {
            let (neg, rest) = match s.strip_prefix('-') {
                Some(r) => (true, r),
                None => (false, s.as_str()),
            };
            Some((neg, parse_size(rest, block_size).with_context(|| format!("invalid skip '{}'", s))?))
        }
        None => None,
    };
    let display_offset = match &o.display_offset {
        Some(s) => parse_size(s, block_size).with_context(|| format!("invalid display offset '{}'", s))?,
        None => 0,
    };

    let stdout = std::io::stdout();
    let tty = stdout.is_terminal();
    let no_color_env = std::env::var_os("NO_COLOR").map_or(false, |v| !v.is_empty());
    let show_color = if o.plain {
        false
    } else {
        match o.color {
            ColorWhen::Force => true,
            ColorWhen::Always => !no_color_env,
            ColorWhen::Auto => tty && !no_color_env,
            ColorWhen::Never => false,
        }
    };
    let border = if o.plain {
        BorderStyle::None
    } else {
        match o.border {
            Border::Unicode => BorderStyle::Unicode,
            Border::Ascii => BorderStyle::Ascii,
            Border::None => BorderStyle::None,
        }
    };
    let mut cfg = Config {
        show_color,
        show_char_panel: o.characters || !(o.no_characters || o.plain),
        show_position: !(o.no_position || o.plain),
        border,
        character_table: match o.character_table {
            Table::Default => CharacterTable::Default,
            Table::Ascii => CharacterTable::Ascii,
            Table::Braille => CharacterTable::Braille,
        },
        squeeze: !o.no_squeezing,
        panels: 2,
        group_size: o.group_size,
        endianness: match o.endianness {
            Endian::Little => Endianness::Little,
            Endian::Big => Endianness::Big,
        },
        base: o.base,
        display_offset,
    };
    cfg.panels = if o.panels == "auto" {
        let width = o
            .terminal_width
            .or_else(|| terminal_size::terminal_size().map(|(w, _)| w.0 as usize))
            .unwrap_or(80);
        auto_panels(&cfg, width)
    } else {
        match o.panels.parse::<usize>() {
            Ok(n) if n >= 1 => n,
            _ => bail!("invalid --panels value '{}': expected a positive number or 'auto'", o.panels),
        }
    };

    // Open input and apply skip.
    let mut start: u64 = 0;
    let mut reader: Box<dyn Read> = match &o.file {
        Some(p) if p.as_os_str() != "-" => {
            let mut f = File::open(p).with_context(|| format!("Failed to open file '{}'", p.display()))?;
            if f.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                bail!("'{}' is a directory", p.display());
            }
            match skip {
                Some((false, n)) => {
                    f.seek(SeekFrom::Start(n)).context("Failed to seek")?;
                    start = n;
                }
                Some((true, n)) => {
                    let len = f.seek(SeekFrom::End(0)).context("Failed to seek")?;
                    let pos = len.checked_sub(n).ok_or_else(|| anyhow!("Tried to skip past the beginning of the file"))?;
                    f.seek(SeekFrom::Start(pos))?;
                    start = pos;
                }
                None => {}
            }
            Box::new(f)
        }
        _ => {
            let mut stdin = std::io::stdin().lock();
            match skip {
                Some((false, n)) => {
                    std::io::copy(&mut (&mut stdin).take(n), &mut std::io::sink())?;
                    start = n;
                    Box::new(stdin)
                }
                Some((true, n)) => {
                    let mut all = Vec::new();
                    stdin.read_to_end(&mut all)?;
                    let pos = (all.len() as u64)
                        .checked_sub(n)
                        .ok_or_else(|| anyhow!("Tried to skip past the beginning of the input"))?;
                    start = pos;
                    Box::new(std::io::Cursor::new(all.split_off(pos as usize)))
                }
                None => Box::new(stdin),
            }
        }
    };
    if let Some(n) = length {
        reader = Box::new(reader.take(n));
    }

    let mut printer = Printer::new(BufWriter::new(stdout.lock()), cfg);
    printer.print_all(reader, start)
}

fn main() {
    if let Err(e) = run() {
        if let Some(io) = e.downcast_ref::<std::io::Error>() {
            if io.kind() == std::io::ErrorKind::BrokenPipe {
                std::process::exit(0);
            }
        }
        eprintln!("Error: {:#}", e);
        std::process::exit(1);
    }
}
