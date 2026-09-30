//! Kitty launcher options, kept separate from Herdr's different placement model.
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Placement {
    #[default]
    Overlay,
    Split,
    Tab,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub(crate) struct KittyConfig {
    pub(crate) placement: Placement,
}

#[derive(Debug, Default, Serialize)]
pub(crate) struct Args {
    pub(crate) action: String,
    pub(crate) path: Option<String>,
    pub(crate) source_window: Option<u64>,
    pub(crate) to: Option<String>,
    pub(crate) placement: Option<Placement>,
    pub(crate) newest: bool,
    pub(crate) extent: String,
    pub(crate) lines: Option<usize>,
    pub(crate) print: bool,
}

pub(crate) fn parse(args: &[String]) -> Result<Args> {
    let mut items = args.iter();
    let action = items.next().context("kitty needs open, last, selection, terminal, setup, or hook")?;
    anyhow::ensure!(
        matches!(action.as_str(), "open" | "last" | "selection" | "terminal"),
        "unknown Kitty action {action}"
    );
    let mut result = Args { action: action.clone(), extent: "screen".into(), ..Args::default() };
    while let Some(arg) = items.next() {
        let mut value = || items.next().with_context(|| format!("{arg} needs a value"));
        match arg.as_str() {
            "--source-window" => {
                let id = value()?.parse::<u64>().context("--source-window needs a positive window ID")?;
                anyhow::ensure!(id > 0, "--source-window needs a positive window ID");
                result.source_window = Some(id);
            }
            "--to" => result.to = Some(value()?.clone()),
            "--placement" => {
                result.placement = Some(match value()?.as_str() {
                    "overlay" => Placement::Overlay,
                    "split" => Placement::Split,
                    "tab" => Placement::Tab,
                    other => {
                        anyhow::bail!("unknown Kitty placement {other}; expected overlay, split, or tab")
                    }
                });
            }
            "--newest" if action == "last" => result.newest = true,
            "--extent" if action == "terminal" => {
                result.extent.clone_from(value()?);
                anyhow::ensure!(
                    matches!(
                        result.extent.as_str(),
                        "screen"
                            | "all"
                            | "alternate"
                            | "alternate_scrollback"
                            | "last_cmd_output"
                            | "last_non_empty_output"
                            | "last_visited_cmd_output"
                            | "first_cmd_output_on_screen"
                    ),
                    "unsupported terminal extent {}",
                    result.extent
                );
            }
            "--lines" if action == "terminal" => {
                let count = value()?.parse::<usize>().context("--lines needs a positive number")?;
                anyhow::ensure!(count > 0, "--lines needs a positive number");
                result.lines = Some(count);
            }
            "--print" if matches!(action.as_str(), "selection" | "terminal") => result.print = true,
            path if action == "open" && !path.starts_with('-') && result.path.is_none() => {
                result.path = Some(path.into());
            }
            other => anyhow::bail!("unexpected argument {other:?} for kitty {action}"),
        }
    }
    Ok(result)
}

#[cfg(test)]
#[allow(clippy::expect_used, reason = "test assertions")]
mod tests {
    use super::*;
    fn parse_words(words: &[&str]) -> Result<Args> {
        parse(&words.iter().map(|word| (*word).to_owned()).collect::<Vec<_>>())
    }
    #[test]
    fn targets_must_be_positive_and_options_apply_only_to_their_view() {
        for args in [
            vec!["open", "--source-window", "0"],
            vec!["open", "--source-window", "-1"],
            vec!["open", "--newest"],
            vec!["last", "doc.md"],
            vec!["selection", "--extent", "all"],
            vec!["terminal", "--lines", "0"],
        ] {
            assert!(parse_words(&args).is_err(), "{args:?}");
        }
        let args = parse_words(&[
            "terminal",
            "--source-window",
            "42",
            "--extent",
            "all",
            "--lines",
            "200",
            "--print",
        ])
        .expect("valid");
        assert_eq!(args.source_window, Some(42));
        assert_eq!(args.lines, Some(200));
        assert!(args.print);
    }
}
