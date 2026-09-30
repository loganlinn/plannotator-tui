//! Local Kitty RPC with private request files: feedback never goes through shell parsing or argv.
use anyhow::{Context, Result};
use serde_json::Value;
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

const ASSETS: &[(&str, &str)] = &[
    ("bridge.py", include_str!("assets/bridge.py")),
    ("state.py", include_str!("assets/state.py")),
    ("views.py", include_str!("assets/views.py")),
    ("launcher.py", include_str!("assets/launcher.py")),
];
static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

pub(crate) fn helper() -> Result<PathBuf> {
    let home = std::env::home_dir().context("cannot locate home directory for the Kitty helper")?;
    let base = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| home.join(".cache"));
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    ASSETS.hash(&mut hash);
    let dir = base.join("plannotator-tui/kitty").join(format!("{:016x}", hash.finish()));
    std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
    }
    for (name, source) in ASSETS {
        let dest = dir.join(name);
        if std::fs::read_to_string(&dest).ok().as_deref() != Some(source) {
            let temporary = RequestFile::bytes(&dir, source.as_bytes())?;
            std::fs::rename(&temporary.0, &dest)?;
        }
    }
    Ok(dir.join("bridge.py"))
}

pub(crate) struct RequestFile(pub(crate) PathBuf);
impl RequestFile {
    pub(crate) fn bytes(dir: &Path, data: &[u8]) -> Result<Self> {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        loop {
            let path = dir.join(format!(
                "request-{}-{}",
                std::process::id(),
                NEXT_FILE.fetch_add(1, Ordering::Relaxed)
            ));
            match options.open(&path) {
                Ok(mut file) => {
                    let result = Self(path);
                    file.write_all(data)?;
                    return Ok(result);
                }
                Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => (),
                Err(err) => return Err(err).context("creating private Kitty request"),
            }
        }
    }
}
impl Drop for RequestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

pub(crate) fn endpoint(explicit: Option<String>) -> Result<String> {
    let value = explicit
        .or_else(|| std::env::var("KITTY_LISTEN_ON").ok())
        .context("no Kitty socket: pass --to or launch inside a Kitty window")?;
    anyhow::ensure!(
        value.starts_with("unix:") && value.len() > 5,
        "Kitty integration currently requires a local unix: socket; SSH, TCP, and fd endpoints are unsupported"
    );
    Ok(value)
}

pub(crate) fn request(to: &str, helper: &Path, window: u64, request: &Value) -> Result<Value> {
    let file = RequestFile::bytes(
        helper.parent().context("Kitty helper has no directory")?,
        &serde_json::to_vec(request)?,
    )?;
    let output = Command::new("kitty")
        .args(["@", "--to", to, "kitten", "--match", &format!("id:{window}")])
        .arg(helper)
        .arg("--request")
        .arg(&file.0)
        .stdin(Stdio::null())
        .output()
        .context("running kitty remote control")?;
    anyhow::ensure!(
        output.status.success(),
        "Kitty request failed: {}",
        String::from_utf8_lossy(&output.stderr).trim()
    );
    serde_json::from_slice(&output.stdout).context("Kitty returned no valid response")
}

pub(crate) fn require_ok(response: &Value) -> Result<()> {
    anyhow::ensure!(
        response.get("status").and_then(Value::as_str) == Some("ok"),
        "{}",
        response.get("message").and_then(Value::as_str).unwrap_or("Kitty did not acknowledge the request")
    );
    Ok(())
}
