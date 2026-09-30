//! Headless identity/lifecycle forwarding. Hook failures never block an agent.
use super::client;
use anyhow::{Context, Result};
use serde_json::{Value, json};
use std::io::Read;
use std::process::Command;

pub(crate) fn run(host: &str) -> Result<()> {
    anyhow::ensure!(matches!(host, "codex" | "claude"), "supported Kitty hook hosts: codex, claude");
    // No endpoint or no exact window is an ordinary non-Kitty invocation.
    let Some(window) =
        std::env::var("KITTY_WINDOW_ID").ok().and_then(|v| v.parse::<u64>().ok()).filter(|id| *id > 0)
    else {
        return Ok(());
    };
    let Ok(to) = client::endpoint(None) else {
        return Ok(());
    };
    let mut text = String::new();
    std::io::stdin().take(1024 * 1024).read_to_string(&mut text)?;
    let input: Value = serde_json::from_str(&text).context("reading agent hook JSON")?;
    if input.get("agent_id").is_some() {
        return Ok(());
    }
    let Some(ancestors) = ancestors() else {
        return Ok(());
    };
    let mut event = serde_json::Map::new();
    for key in [
        "hook_event_name",
        "session_id",
        "transcript_path",
        "turn_id",
        "prompt_id",
        "notification_type",
        "tool_name",
    ] {
        if let Some(value) = input.get(key) {
            event.insert(key.into(), value.clone());
        }
    }
    let helper = client::helper()?;
    let _ = client::request(
        &to,
        &helper,
        window,
        &json!({"op":"event", "host":host, "ancestors":ancestors, "event":event}),
    );
    Ok(())
}

fn ancestors() -> Option<Vec<u32>> {
    let output = Command::new("ps").args(["-axo", "pid=,ppid="]).output().ok()?;
    let text = String::from_utf8_lossy(&output.stdout);
    let rows: Vec<_> = text
        .lines()
        .filter_map(|line| {
            let mut words = line.split_whitespace();
            Some((words.next()?.parse::<u32>().ok()?, words.next()?.parse::<u32>().ok()?))
        })
        .collect();
    let mut pid = std::process::id();
    let mut ancestors = Vec::new();
    for _ in 0..32 {
        let row = rows.iter().find(|row| row.0 == pid)?;
        ancestors.push(pid);
        if row.1 <= 1 || row.1 == pid {
            return Some(ancestors);
        }
        pid = row.1;
    }
    None
}
