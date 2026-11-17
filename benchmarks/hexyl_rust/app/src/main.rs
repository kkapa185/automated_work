mod cli;
mod render;
mod size;

use std::fs::File;
use std::io::{self, BufWriter, Cursor, Read, Seek, SeekFrom};

use anyhow::{bail, Context, Result};
use clap::Parser;

use cli::Args;
use render::Renderer;

fn run() -> Result<()> {
    let args = Args::parse();
    let mut plan = args.resolve()?;
    let path = args.file.as_ref().filter(|p| p.as_os_str() != "-");

    let mut input: Box<dyn Read> = match path {
        Some(p) => {
            let mut f = File::open(p).with_context(|| format!("Failed to open file '{}'", p.display()))?;
            if f.metadata().map_or(false, |m| m.is_dir()) {
                bail!("Failed to read '{}': Is a directory", p.display());
            }
            let skipped = if plan.skip < 0 {
                match f.seek(SeekFrom::End(plan.skip)) {
                    Ok(pos) => pos,
                    Err(_) => bail!("cannot skip {} bytes from the end: input is shorter", -plan.skip),
                }
            } else if plan.skip > 0 {
                f.seek(SeekFrom::Start(plan.skip as u64))
                    .with_context(|| "Failed to skip input")?
            } else {
                0
            };
            plan.config.display_offset += skipped;
            Box::new(f)
        }
        None => {
            let stdin = io::stdin();
            if plan.skip < 0 {
                let mut all = Vec::new();
                stdin.lock().read_to_end(&mut all).context("Failed to read stdin")?;
                let back = plan.skip.unsigned_abs();
                if back > all.len() as u64 {
                    bail!("cannot skip {back} bytes from the end: input is shorter");
                }
                let start = all.len() - back as usize;
                plan.config.display_offset += start as u64;
                Box::new(Cursor::new(all.split_off(start)))
            } else {
                let mut lock = stdin.lock();
                let skip = plan.skip as u64;
                io::copy(&mut (&mut lock).take(skip), &mut io::sink()).context("Failed to skip input")?;
                plan.config.display_offset += skip;
                Box::new(stdin)
            }
        }
    };
    if let Some(n) = plan.length {
        input = Box::new(input.take(n));
    }

    let stdout = io::stdout();
    let out = BufWriter::new(stdout.lock());
    Renderer::new(plan.config, out)
        .dump(input)
        .context("Failed to write output")?;
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        if let Some(io_err) = e.downcast_ref::<io::Error>() {
            if io_err.kind() == io::ErrorKind::BrokenPipe {
                return;
            }
        }
        // `{:#}` prints the whole context chain, including a broken pipe nested in it.
        if e.chain().any(|c| c.downcast_ref::<io::Error>().map_or(false, |i| i.kind() == io::ErrorKind::BrokenPipe)) {
            return;
        }
        eprintln!("Error: {e:#}");
        std::process::exit(1);
    }
}
