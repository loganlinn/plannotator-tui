//! Kitty launcher and review entrypoint. No Herdr environment emulation.
#![allow(clippy::print_stdout, clippy::print_stderr, reason = "Kitty CLI entrypoints")]
pub(crate) mod args;
mod client;
mod context;
pub(crate) mod delivery;
mod hooks;

use self::context::Context;
use anyhow::{Context as _, Result};
use serde_json::json;
use std::path::PathBuf;

pub(crate) fn run(args: &[String]) -> Result<()> {
    if args.first().map(String::as_str) == Some("key") {
        let rest = args.get(1..).unwrap_or_default();
        if let Err(error) = run(rest) {
            if let Ok(options) = args::parse(rest)
                && let (Some(source), Ok(to), Ok(helper)) =
                    (options.source_window, client::endpoint(options.to), client::helper())
            {
                let _ = client::request(
                    &to,
                    &helper,
                    source,
                    &json!({"op":"error", "message":format!("{error:#}")}),
                );
            }
            return Err(error);
        }
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("setup") if args.len() == 1 => return setup(),
        Some("hook") if args.len() == 2 => {
            if let Some(host) = args.get(1) {
                let _ = hooks::run(host);
            }
            return Ok(());
        }
        Some("pane") if args.len() == 2 => {
            return pane(&PathBuf::from(args.get(1).context("missing review context")?));
        }
        _ => (),
    }
    let options = args::parse(args)?;
    let source = options
        .source_window
        .or_else(|| std::env::var("KITTY_WINDOW_ID").ok().and_then(|v| v.parse().ok()))
        .filter(|id| *id > 0)
        .context("no source window: pass --source-window or invoke from a Kitty window")?;
    let to = client::endpoint(options.to.clone())?;
    let helper = client::helper()?;
    let config = crate::config::Config::load()?;
    let response = client::request(
        &to,
        &helper,
        source,
        &json!({
            "op":"launch", "options": options, "placement": options.placement.unwrap_or(config.kitty.placement),
            "binary":std::env::current_exe()?, "to":to, "helper":helper,
            "caller_cwd":std::env::current_dir()?,
        }),
    )?;
    client::require_ok(&response)?;
    if options.print {
        let text =
            response.get("text").and_then(serde_json::Value::as_str).context("missing terminal text")?;
        print!("{}", crate::terminal::document(&crate::terminal::clean(text)));
    } else {
        println!("{}", response.get("window_id").context("missing review window ID")?);
    }
    Ok(())
}

fn pane(path: &PathBuf) -> Result<()> {
    let raw = std::fs::read(path).with_context(|| format!("reading review context {}", path.display()))?;
    let context: Context = serde_json::from_slice(&raw).context("invalid Kitty review context")?;
    std::fs::remove_file(path).context("removing consumed Kitty context")?;
    std::env::set_current_dir(&context.cwd).context("entering source window directory")?;
    delivery::install(context.clone());
    let result = match context.action.as_str() {
        "open" => crate::cli::interactive(context.path.as_ref().context("no file or folder to review")?),
        "last" => {
            anyhow::ensure!(
                context.transcript.is_some() || context.target.session.is_some(),
                "exact agent session unavailable"
            );
            crate::last::run(&crate::last::LastOptions {
                host: context.target.host.clone(),
                session: context.transcript.clone(),
                session_id: context.target.session.clone(),
                newest: context.newest,
                pick: 25,
                ..crate::last::LastOptions::default()
            })
        }
        "selection" | "terminal" => {
            let text = crate::terminal::clean(context.text.as_deref().context("missing captured text")?);
            let title = format!("{} · kitty:{}", context.action, context.target.window);
            crate::cli::run_ui(|width| crate::terminal::open(&text, title, width, crate::cli::delivery(true)))
        }
        other => anyhow::bail!("unknown review source {other}"),
    };
    if let Err(err) = &result {
        eprintln!("plannotator-tui: {err:#}\n\npress enter to close");
        let mut line = String::new();
        let _ = std::io::stdin().read_line(&mut line);
    }
    result
}

fn setup() -> Result<()> {
    let helper = client::helper()?;
    let binary = std::env::current_exe()?;
    println!("# Helper installed at {}", helper.display());
    println!("# Add to kitty.conf (change these example shortcuts as needed):");
    for (key, action) in [
        ("ctrl+shift+o", "open"),
        ("ctrl+shift+alt+o", "last"),
        ("ctrl+shift+a", "selection"),
        ("ctrl+shift+alt+a", "terminal"),
    ] {
        println!(
            "map {key} kitten {} {action} --binary {}",
            quoted(&helper.to_string_lossy()),
            quoted(&binary.to_string_lossy())
        );
    }
    println!(
        "\n# Add to open-actions.conf:\nprotocol file\next md,markdown,mdx\naction kitten {} open --binary {} ${{FILE_PATH}}",
        quoted(&helper.to_string_lossy()),
        quoted(&binary.to_string_lossy())
    );
    for host in ["codex", "claude"] {
        let command = format!("{} kitty hook {host}", quoted(&binary.to_string_lossy()));
        let mut events = serde_json::Map::new();
        for event in [
            "SessionStart",
            "SessionEnd",
            "UserPromptSubmit",
            "PreToolUse",
            "PermissionRequest",
            "PostToolUse",
            "Stop",
        ] {
            events.insert(
                event.into(),
                json!([{"hooks":[{"type":"command", "command":command, "timeout":2}]}]),
            );
        }
        if host == "claude" {
            for event in ["Notification", "Elicitation", "ElicitationResult", "StopFailure"] {
                events.insert(
                    event.into(),
                    json!([{"hooks":[{"type":"command", "command":command, "timeout":2}]}]),
                );
            }
        } else {
            events.insert(
                "Interrupt".into(),
                json!([{"hooks":[{"type":"command", "command":command, "timeout":2}]}]),
            );
        }
        println!(
            "\n# Merge these {host} hooks with existing hooks; do not replace other entries:\n{}",
            serde_json::to_string_pretty(&json!({"hooks":events}))?
        );
    }
    println!(
        "\n# Restart agent sessions after configuring hooks. Review Codex hooks with /hooks.\n# Unknown input surfaces remain copy-only; setup does not change your configuration."
    );
    Ok(())
}

fn quoted(text: &str) -> String {
    format!("'{}'", text.replace('\'', "'\"'\"'"))
}
