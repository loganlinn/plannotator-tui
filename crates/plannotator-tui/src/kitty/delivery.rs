//! An acknowledged native Kitty submission; ambiguous transport results latch against retries.
use super::{client, context::Context};
use crate::delivery::{Delivery, DeliveryError};
use std::cell::Cell;

pub(crate) struct KittyAgent {
    context: Context,
    uncertain: Cell<bool>,
}
impl KittyAgent {
    pub(crate) fn new(context: Context) -> Self {
        Self { context, uncertain: Cell::new(false) }
    }
}
impl Delivery for KittyAgent {
    fn describe(&self) -> String {
        format!(
            "{} in kitty:{}",
            self.context.target.host.as_deref().unwrap_or("agent"),
            self.context.target.window
        )
    }
    fn is_agent(&self) -> bool {
        true
    }
    fn agent_host(&self) -> Option<&str> {
        self.context.target.host.as_deref()
    }
    fn deliver(&self, feedback: &str) -> Result<(), DeliveryError> {
        if self.uncertain.get() {
            return Err(DeliveryError::Uncertain(
                "inspect the agent before reopening this review; automatic retry is disabled".into(),
            ));
        }
        let context = &self.context;
        let response = client::request(
            &context.to,
            &context.helper,
            context.target.window,
            &serde_json::json!({
                "op": "deliver", "target": context.target, "feedback": feedback,
            }),
        );
        match response {
            Ok(value) => match value.get("status").and_then(serde_json::Value::as_str) {
                Some("ok") => Ok(()),
                Some("blocked" | "unavailable") => Err(DeliveryError::Unavailable(
                    value
                        .get("message")
                        .and_then(serde_json::Value::as_str)
                        .unwrap_or("agent readiness is unknown")
                        .into(),
                )),
                _ => {
                    self.uncertain.set(true);
                    Err(DeliveryError::Uncertain(
                        value
                            .get("message")
                            .and_then(serde_json::Value::as_str)
                            .unwrap_or("Kitty submission was not acknowledged")
                            .into(),
                    ))
                }
            },
            Err(err) => {
                self.uncertain.set(true);
                Err(DeliveryError::Uncertain(format!("{err:#}")))
            }
        }
    }
}

/// Only the explicit Kitty pane entrypoint sets this process-local context.
static CONTEXT: std::sync::OnceLock<Context> = std::sync::OnceLock::new();
pub(crate) fn install(context: Context) {
    let _ = CONTEXT.set(context);
}
pub(crate) fn from_context() -> Option<Box<dyn Delivery>> {
    CONTEXT
        .get()
        .filter(|context| context.target.host.is_some())
        .map(|context| Box::new(KittyAgent::new(context.clone())) as Box<dyn Delivery>)
}
