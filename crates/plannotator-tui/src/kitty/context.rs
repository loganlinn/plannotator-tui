//! The source identity captured before a review is launched.
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct Target {
    pub(crate) instance: u32,
    pub(crate) window: u64,
    pub(crate) pid: Option<u32>,
    pub(crate) host: Option<String>,
    pub(crate) session: Option<String>,
    pub(crate) generation: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct Context {
    pub(crate) to: String,
    pub(crate) helper: PathBuf,
    pub(crate) target: Target,
    pub(crate) action: String,
    pub(crate) cwd: PathBuf,
    pub(crate) path: Option<PathBuf>,
    pub(crate) text: Option<String>,
    pub(crate) transcript: Option<PathBuf>,
    pub(crate) newest: bool,
}
