use std::fmt;

/// Result alias used across the client.
pub type Result<T> = std::result::Result<T, Error>;

/// Everything that can go wrong talking to the ZelfAI API.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The client was built wrong, for example with no API key.
    #[error("zelf: {0}")]
    Configuration(String),

    /// The request never produced an HTTP response.
    #[error("zelf: could not reach the API: {source}")]
    Connection {
        #[source]
        source: reqwest::Error,
    },

    /// The request exceeded the configured timeout.
    #[error("zelf: the request timed out")]
    Timeout,

    /// The body did not parse as the response envelope.
    #[error("zelf: HTTP {status} returned a body that is not a valid envelope: {source}")]
    Decode {
        status: u16,
        #[source]
        source: serde_json::Error,
    },

    /// An error response from the API, carrying the envelope's own fields.
    #[error("{}", format_api(.status, .code.as_deref(), .message, .log_id.as_deref()))]
    Api {
        status: u16,
        code: Option<String>,
        message: String,
        details: Option<serde_json::Value>,
        log_id: Option<String>,
    },
}

fn format_api(status: &u16, code: Option<&str>, message: &str, log_id: Option<&str>) -> String {
    let mut out = format!("zelf: {status}");
    if let Some(code) = code {
        out.push(' ');
        out.push_str(code);
    }
    out.push_str(": ");
    out.push_str(message);
    if let Some(log_id) = log_id {
        out.push_str(&format!(" (log_id={log_id})"));
    }
    out
}

impl Error {
    /// The HTTP status, when the failure came back as a response.
    pub fn status(&self) -> Option<u16> {
        match self {
            Error::Api { status, .. } | Error::Decode { status, .. } => Some(*status),
            _ => None,
        }
    }

    /// The API's own error code, for example `RATE_LIMIT_EXCEEDED`.
    pub fn code(&self) -> Option<&str> {
        match self {
            Error::Api { code, .. } => code.as_deref(),
            _ => None,
        }
    }

    /// The log id to quote when reporting a problem.
    pub fn log_id(&self) -> Option<&str> {
        match self {
            Error::Api { log_id, .. } => log_id.as_deref(),
            _ => None,
        }
    }

    /// Whether the API rejected the request for want of a valid key.
    pub fn is_unauthorized(&self) -> bool {
        matches!(self.status(), Some(401) | Some(403))
    }

    /// Whether the request was rate limited.
    pub fn is_rate_limited(&self) -> bool {
        self.status() == Some(429)
    }

    /// Whether a read matched nothing.
    pub fn is_not_found(&self) -> bool {
        self.status() == Some(404)
    }
}

/// Describes a status the API documents, for matching without magic numbers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StatusKind(pub u16);

impl fmt::Display for StatusKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}
