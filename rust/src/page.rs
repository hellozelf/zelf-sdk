use std::sync::Arc;

use reqwest::Method;
use serde::de::DeserializeOwned;

use crate::error::{Error, Result};
use crate::transport::{Envelope, Transport};

/// Bounds how far a walk over the remaining pages goes.
///
/// `Limits::default()` walks everything.
#[derive(Debug, Clone, Copy, Default)]
pub struct Limits {
    pub max_pages: Option<usize>,
    pub max_items: Option<usize>,
}

impl Limits {
    /// Stop after `n` pages, counting the one already in hand. A value of 1
    /// makes no further request.
    pub fn pages(n: usize) -> Self {
        Self {
            max_pages: Some(n),
            max_items: None,
        }
    }

    /// Stop once `n` items have been visited, so no page is requested that is
    /// not needed to reach `n`.
    pub fn items(n: usize) -> Self {
        Self {
            max_pages: None,
            max_items: Some(n),
        }
    }

    /// Add a page bound to an existing limit.
    pub fn with_max_pages(mut self, n: usize) -> Self {
        self.max_pages = Some(n);
        self
    }

    /// Add an item bound to an existing limit.
    pub fn with_max_items(mut self, n: usize) -> Self {
        self.max_items = Some(n);
        self
    }

    fn check(&self) -> Result<()> {
        if self.max_pages == Some(0) || self.max_items == Some(0) {
            return Err(Error::Configuration(
                "max_pages and max_items need a value of 1 or greater".into(),
            ));
        }
        Ok(())
    }
}

/// One page of results, plus the envelope metadata that came with it.
///
/// The page keeps the request that produced it, so the next page is fetched by
/// re-issuing that request with a new `page` value.
pub struct Page<T> {
    pub results: Vec<T>,
    pub log_id: String,
    pub page: i64,
    pub item_count: i64,
    pub next: Option<i64>,
    pub previous: Option<i64>,
    pub applied_filters: serde_json::Value,

    transport: Arc<Transport>,
    path: String,
    query: Vec<(String, String)>,
}

impl<T> std::fmt::Debug for Page<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Page")
            .field("page", &self.page)
            .field("item_count", &self.item_count)
            .field("has_next", &self.has_next())
            .finish()
    }
}

impl<T> Page<T> {
    /// Whether another page is available.
    pub fn has_next(&self) -> bool {
        self.next.is_some()
    }
}

impl<T: DeserializeOwned> Page<T> {
    pub(crate) fn new(
        envelope: Envelope<T>,
        transport: Arc<Transport>,
        path: String,
        query: Vec<(String, String)>,
    ) -> Self {
        Self {
            results: envelope.results,
            log_id: envelope.log_id,
            page: envelope.page,
            item_count: envelope.item_count,
            next: envelope.next,
            previous: envelope.previous,
            applied_filters: envelope.applied_filters,
            transport,
            path,
            query,
        }
    }

    /// Fetch the page after this one, or `None` when there is none.
    pub async fn next_page(&self) -> Result<Option<Page<T>>> {
        let Some(number) = self.next else {
            return Ok(None);
        };
        let mut query: Vec<(String, String)> = self
            .query
            .iter()
            .filter(|(k, _)| k != "page")
            .cloned()
            .collect();
        query.push(("page".to_string(), number.to_string()));

        let envelope: Envelope<T> = self
            .transport
            .request(Method::GET, &self.path, &[], &query, None)
            .await?;
        Ok(Some(Page::new(
            envelope,
            self.transport.clone(),
            self.path.clone(),
            query,
        )))
    }

    /// Walk the remaining pages, calling `visit` for each item.
    ///
    /// Returning `Err` from `visit` stops the walk and surfaces that error.
    pub async fn for_each<F>(&self, limits: Limits, mut visit: F) -> Result<()>
    where
        F: FnMut(&T) -> Result<()>,
    {
        limits.check()?;
        let mut current: Option<Page<T>> = None;
        let mut pages_seen = 0usize;
        let mut items_seen = 0usize;

        loop {
            let page = current.as_ref().unwrap_or(self);
            for item in &page.results {
                visit(item)?;
                items_seen += 1;
                if limits.max_items.is_some_and(|max| items_seen >= max) {
                    return Ok(());
                }
            }
            pages_seen += 1;
            if limits.max_pages.is_some_and(|max| pages_seen >= max) {
                return Ok(());
            }
            match page.next_page().await? {
                Some(next) => current = Some(next),
                None => return Ok(()),
            }
        }
    }
}

impl<T: DeserializeOwned + Clone> Page<T> {
    /// Walk the remaining pages and collect every item into one vector.
    pub async fn collect_all(&self, limits: Limits) -> Result<Vec<T>> {
        limits.check()?;
        let mut out: Vec<T> = Vec::new();
        let mut current: Option<Page<T>> = None;
        let mut pages_seen = 0usize;

        loop {
            let page = current.as_ref().unwrap_or(self);
            for item in page.results.iter() {
                out.push(item.clone());
                if limits.max_items.is_some_and(|max| out.len() >= max) {
                    return Ok(out);
                }
            }
            pages_seen += 1;
            if limits.max_pages.is_some_and(|max| pages_seen >= max) {
                return Ok(out);
            }
            match page.next_page().await? {
                Some(next) => current = Some(next),
                None => return Ok(out),
            }
        }
    }
}

/// Take the single row out of the envelope.
///
/// Reads that match nothing come back as 200 with an empty `results` array
/// rather than a 404, so the empty case becomes a not-found error.
pub(crate) fn one<T>(mut envelope: Envelope<T>, what: &str) -> Result<T> {
    if envelope.results.is_empty() {
        return Err(Error::Api {
            status: 404,
            code: Some("NOT_FOUND".to_string()),
            message: format!("No {what} matched the request."),
            details: None,
            log_id: Some(envelope.log_id),
        });
    }
    Ok(envelope.results.remove(0))
}
