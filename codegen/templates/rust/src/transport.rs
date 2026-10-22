use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use reqwest::{Method, StatusCode};
use serde::de::DeserializeOwned;
use serde::Deserialize;

use crate::error::{Error, Result};
use crate::VERSION;

/// The production Zelf API.
pub const DEFAULT_BASE_URL: &str = "https://api.hellozelf.com";
/// Read when no key is passed explicitly.
pub const API_KEY_ENV: &str = "ZELF_API_KEY";
/// Read when no base URL is passed explicitly.
pub const BASE_URL_ENV: &str = "ZELF_BASE_URL";

const MAX_BACKOFF: Duration = Duration::from_secs(8);
const RETRY_STATUSES: [u16; 5] = [429, 500, 502, 503, 504];

/// The response wrapper every Zelf endpoint returns.
#[derive(Debug, Clone, Deserialize)]
pub struct Envelope<T> {
    pub log_id: String,
    pub timestamp: String,
    #[serde(default)]
    pub applied_filters: serde_json::Value,
    #[serde(default = "Vec::new")]
    pub results: Vec<T>,
    #[serde(default)]
    pub item_count: i64,
    #[serde(default)]
    pub page: i64,
    #[serde(default)]
    pub next: Option<i64>,
    #[serde(default)]
    pub previous: Option<i64>,
}

/// Builds a [`crate::Client`].
#[derive(Clone)]
pub struct ClientBuilder {
    api_key: Option<String>,
    base_url: String,
    timeout: Duration,
    max_retries: u32,
    retry_writes: bool,
    headers: HashMap<String, String>,
    http_client: Option<reqwest::Client>,
}

// The key must never reach a log line, so Debug prints a placeholder. The
// transport does the same; the builder holds the key just as long.
impl std::fmt::Debug for ClientBuilder {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ClientBuilder")
            .field("api_key", &self.api_key.as_ref().map(|_| "***"))
            .field("base_url", &self.base_url)
            .field("timeout", &self.timeout)
            .field("max_retries", &self.max_retries)
            .field("retry_writes", &self.retry_writes)
            .field("headers", &self.headers)
            .finish()
    }
}

impl Default for ClientBuilder {
    fn default() -> Self {
        Self {
            api_key: std::env::var(API_KEY_ENV).ok().filter(|key| !key.is_empty()),
            base_url: std::env::var(BASE_URL_ENV)
                .ok()
                .filter(|url| !url.is_empty())
                .unwrap_or_else(|| DEFAULT_BASE_URL.to_string()),
            timeout: Duration::from_secs(60),
            max_retries: 2,
            retry_writes: false,
            headers: HashMap::new(),
            http_client: None,
        }
    }
}

impl ClientBuilder {
    /// Sets the brand API key. Without it `ZELF_API_KEY` is used.
    pub fn api_key(mut self, key: impl Into<String>) -> Self {
        self.api_key = Some(key.into());
        self
    }

    /// Points the client at a different deployment.
    pub fn base_url(mut self, url: impl Into<String>) -> Self {
        self.base_url = url.into();
        self
    }

    /// Bounds each individual HTTP attempt.
    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Sets how many times a retryable response is retried.
    pub fn max_retries(mut self, retries: u32) -> Self {
        self.max_retries = retries;
        self
    }

    /// Allows non-idempotent requests to be retried. The API publishes no
    /// idempotency key, so a retried create can run twice. Opt in only when
    /// the caller can tolerate that.
    pub fn retry_writes(mut self, enabled: bool) -> Self {
        self.retry_writes = enabled;
        self
    }

    /// Adds a header to every request.
    pub fn header(mut self, name: impl Into<String>, value: impl Into<String>) -> Self {
        self.headers.insert(name.into(), value.into());
        self
    }

    /// Supplies the reqwest client used for transport.
    pub fn http_client(mut self, client: reqwest::Client) -> Self {
        self.http_client = Some(client);
        self
    }

    pub(crate) fn into_transport(self) -> Result<Arc<Transport>> {
        let api_key = self.api_key.filter(|key| !key.is_empty()).ok_or_else(|| {
            Error::Configuration(format!(
                "an API key is required; call api_key() or set {API_KEY_ENV}"
            ))
        })?;
        let http = match self.http_client {
            Some(client) => client,
            None => reqwest::Client::builder()
                .timeout(self.timeout)
                .build()
                .map_err(|source| Error::Connection { source })?,
        };
        Ok(Arc::new(Transport {
            http,
            api_key,
            base_url: self.base_url.trim_end_matches('/').to_string(),
            max_retries: self.max_retries,
            retry_writes: self.retry_writes,
            // A caller's copy of the API key is dropped whatever its casing,
            // so it cannot be appended alongside the client's own.
            headers: self
                .headers
                .into_iter()
                .filter(|(name, _)| !name.eq_ignore_ascii_case("x-api-key"))
                .collect(),
        }))
    }
}

pub struct Transport {
    http: reqwest::Client,
    api_key: String,
    pub(crate) base_url: String,
    max_retries: u32,
    retry_writes: bool,
    headers: HashMap<String, String>,
}

// The key must never reach a log line, so Debug prints a placeholder.
impl std::fmt::Debug for Transport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Transport")
            .field("base_url", &self.base_url)
            .field("api_key", &"***")
            .finish()
    }
}

fn backoff(attempt: u32, retry_after: Option<&str>) -> Duration {
    if let Some(header) = retry_after {
        if let Ok(seconds) = header.parse::<f64>() {
            if seconds >= 0.0 {
                return Duration::from_secs_f64(seconds.min(60.0));
            }
        }
    }
    let base = MAX_BACKOFF.min(Duration::from_millis(500 * 2u64.pow(attempt.min(6))));
    let jitter = rand::rng().random_range(0.5..1.0);
    base.mul_f64(jitter)
}

impl Transport {
    fn should_retry(&self, method: &Method, status: Option<u16>) -> bool {
        let idempotent = matches!(*method, Method::GET | Method::HEAD | Method::OPTIONS);
        // The API documents no Idempotency-Key header, so a retried write
        // could create a second analysis, vetting, or sync job.
        if !idempotent && !self.retry_writes {
            return false;
        }
        match status {
            None => true,
            Some(code) => RETRY_STATUSES.contains(&code),
        }
    }

    /// Substitute the path parameters, leaving a path relative to the base URL.
    pub(crate) fn resolve_path(&self, path: &str, path_params: &[(&str, &str)]) -> Result<String> {
        let mut resolved = path.to_string();
        for (name, value) in path_params {
            if value.is_empty() {
                return Err(Error::Configuration(format!(
                    "{name} is required and must not be empty"
                )));
            }
            resolved = resolved.replace(&format!("{{{name}}}"), urlencoding::encode(value).as_ref());
        }
        Ok(resolved)
    }

    pub(crate) fn url(&self, path: &str, path_params: &[(&str, &str)]) -> Result<String> {
        Ok(format!("{}{}", self.base_url, self.resolve_path(path, path_params)?))
    }

    pub(crate) async fn request<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        path_params: &[(&str, &str)],
        query: &[(String, String)],
        body: Option<serde_json::Value>,
    ) -> Result<Envelope<T>> {
        let url = self.url(path, path_params)?;
        let mut last: Option<Error> = None;

        for attempt in 0..=self.max_retries {
            let mut request = self
                .http
                .request(method.clone(), &url)
                .query(query)
                .header("accept", "application/json")
                .header("user-agent", format!("zelf-rust/{VERSION}"));
            for (name, value) in &self.headers {
                request = request.header(name, value);
            }
            // Last, so the client's own key always wins.
            request = request.header("x-api-key", &self.api_key);
            if let Some(payload) = &body {
                request = request.json(payload);
            }

            let (status, retry_after) = match request.send().await {
                Ok(response) => {
                    let status = response.status();
                    if status.is_success() {
                        return decode(response).await;
                    }
                    let retry_after = response
                        .headers()
                        .get("retry-after")
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_owned);
                    last = Some(api_error(status, response).await);
                    (Some(status.as_u16()), retry_after)
                }
                Err(source) => {
                    let timed_out = source.is_timeout();
                    last = Some(if timed_out {
                        Error::Timeout
                    } else {
                        Error::Connection { source }
                    });
                    (None, None)
                }
            };

            if attempt == self.max_retries || !self.should_retry(&method, status) {
                break;
            }
            tokio::time::sleep(backoff(attempt, retry_after.as_deref())).await;
        }
        Err(last.unwrap_or_else(|| Error::Configuration("the request was never sent".into())))
    }
}

async fn decode<T: DeserializeOwned>(response: reqwest::Response) -> Result<Envelope<T>> {
    let status = response.status();
    let body = response
        .bytes()
        .await
        .map_err(|source| Error::Connection { source })?;
    if body.is_empty() || status == StatusCode::NO_CONTENT {
        return Ok(Envelope {
            log_id: String::new(),
            timestamp: String::new(),
            applied_filters: serde_json::Value::Null,
            results: Vec::new(),
            item_count: 0,
            page: 0,
            next: None,
            previous: None,
        });
    }
    serde_json::from_slice(&body).map_err(|source| Error::Decode {
        status: status.as_u16(),
        source,
    })
}

#[derive(Deserialize)]
struct ErrorBody {
    #[serde(default)]
    log_id: Option<String>,
    #[serde(default)]
    error: Option<ErrorDetail>,
}

#[derive(Deserialize)]
struct ErrorDetail {
    #[serde(default)]
    code: Option<String>,
    #[serde(default)]
    message: Option<String>,
    #[serde(default)]
    details: Option<serde_json::Value>,
}

async fn api_error(status: StatusCode, response: reqwest::Response) -> Error {
    let parsed = response.json::<ErrorBody>().await.ok();
    let detail = parsed.as_ref().and_then(|body| body.error.as_ref());
    Error::Api {
        status: status.as_u16(),
        code: detail.and_then(|d| d.code.clone()),
        message: detail
            .and_then(|d| d.message.clone())
            .unwrap_or_else(|| format!("HTTP {} from the Zelf API", status.as_u16())),
        details: detail.and_then(|d| d.details.clone()),
        log_id: parsed.and_then(|body| body.log_id),
    }
}
