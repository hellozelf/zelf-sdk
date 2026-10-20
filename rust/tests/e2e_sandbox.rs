//! Drives the sandbox. Run with `cargo test --test e2e_sandbox -- --ignored`.

use zelf::resources::content::ContentListParams;
use zelf::{Client, Limits};

fn base() -> String {
    std::env::var("ZELF_BASE_URL").unwrap_or_else(|_| "https://sandbox-api.hellozelf.com".into())
}

fn key() -> String {
    std::env::var("ZELF_API_KEY").unwrap_or_else(|_| "sk_zelf_sandbox_demo".into())
}

fn client() -> Client {
    Client::builder()
        .api_key(key())
        .base_url(base())
        .build()
        .expect("client builds")
}

fn page_of_two() -> ContentListParams {
    ContentListParams {
        page_size: Some(2),
        ..Default::default()
    }
}

#[tokio::test]
#[ignore = "needs the sandbox"]
async fn usage_decodes() {
    client().usage().retrieve().await.expect("usage");
}

#[tokio::test]
#[ignore = "needs the sandbox"]
async fn a_page_decodes_every_row() {
    let page = client().content().list(page_of_two()).await.expect("list");
    assert_eq!(page.item_count, 2);
    for row in &page.results {
        assert!(row.id.starts_with("con_"), "id {}", row.id);
    }
}

#[tokio::test]
#[ignore = "needs the sandbox"]
async fn auto_paging_stops_at_the_bound() {
    let page = client().content().list(page_of_two()).await.expect("list");
    let rows = page.collect_all(Limits::pages(2)).await.expect("walk");
    assert_eq!(rows.len(), 4);
}

#[tokio::test]
#[ignore = "needs the sandbox"]
async fn a_bad_key_raises_the_typed_error() {
    let bad = Client::builder()
        .api_key(format!("sk_zelf_{}", "9".repeat(64)))
        .base_url(base())
        .max_retries(0)
        .build()
        .expect("client builds");

    let error = bad.usage().retrieve().await.expect_err("expected a 401");
    assert_eq!(error.status(), Some(401));
    assert_eq!(error.code(), Some("INVALID_API_KEY"));
    assert!(error.is_unauthorized());
}

#[tokio::test]
#[ignore = "needs the sandbox"]
async fn event_types_are_listed() {
    let events = client().webhooks().list_events().await.expect("events");
    assert!(!events.is_empty());
}
