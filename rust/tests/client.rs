use serde_json::json;
use wiremock::matchers::{header, method, path, query_param};
use wiremock::{Mock, MockServer, Request, ResponseTemplate};

use zelf::resources::content::ContentListParams;
use zelf::Client;

const KEY: &str = "sk_test_not_a_real_key";

fn envelope(results: serde_json::Value, page: i64, next: Option<i64>) -> serde_json::Value {
    json!({
        "log_id": "log_1",
        "timestamp": "2026-01-01T00:00:00Z",
        "applied_filters": {"page": page},
        "results": results,
        "item_count": 1,
        "page": page,
        "next": next,
        "previous": null,
    })
}

/// The spec's own published example for content.list, so the fixture always
/// satisfies the schema the models were generated from.
fn content_row(id: &str) -> serde_json::Value {
    let raw = include_str!("../../fixtures.json");
    let fixtures: serde_json::Value = serde_json::from_str(raw).expect("fixtures parse");
    let mut row = fixtures["envelopes"]["content_list"]["results"][0].clone();
    row["id"] = json!(id);
    row
}

async fn client_for(server: &MockServer) -> Client {
    Client::builder()
        .api_key(KEY)
        .base_url(server.uri())
        .max_retries(0)
        .build()
        .expect("client builds")
}

#[tokio::test]
async fn list_returns_a_typed_page() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/content/"))
        .and(query_param("search", "running shoes"))
        .and(header("x-api-key", KEY))
        .respond_with(ResponseTemplate::new(200).set_body_json(envelope(
            json!([content_row("con_1")]),
            1,
            None,
        )))
        .mount(&server)
        .await;

    let client = client_for(&server).await;
    let page = client
        .content()
        .list(ContentListParams {
            search: Some("running shoes".into()),
            ..Default::default()
        })
        .await
        .expect("list succeeds");

    assert_eq!(page.results.len(), 1);
    assert_eq!(page.results[0].id, "con_1");
    assert_eq!(page.results[0].view_count, Some(184230));
    assert_eq!(page.log_id, "log_1");
    assert!(!page.has_next());
}

#[tokio::test]
async fn the_api_key_travels_in_a_header_never_the_url() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/usage/"))
        .respond_with(ResponseTemplate::new(200).set_body_json(envelope(
            json!([{"plan": "pro"}]),
            1,
            None,
        )))
        .mount(&server)
        .await;

    let client = client_for(&server).await;
    let _ = client.usage().retrieve().await;

    let requests = server.received_requests().await.expect("requests recorded");
    let request: &Request = &requests[0];
    assert_eq!(request.headers.get("x-api-key").unwrap(), KEY);
    assert!(!request.url.as_str().contains(KEY));
    assert!(request
        .headers
        .get("user-agent")
        .unwrap()
        .to_str()
        .unwrap()
        .starts_with("zelf-rust/"));
}

#[tokio::test]
async fn the_api_key_stays_out_of_debug_output() {
    let client = Client::new(KEY).expect("client builds");
    assert!(!format!("{client:?}").contains(KEY));
    assert!(format!("{client:?}").contains("***"));
}

#[tokio::test]
async fn the_builder_keeps_the_key_out_of_debug_output() {
    // The builder holds the key just as long as the transport does, so it has
    // to redact it too.
    let builder = Client::builder()
        .api_key(KEY)
        .base_url("https://example.invalid")
        .max_retries(3)
        .retry_writes(true)
        .header("x-trace", "abc");
    let shown = format!("{builder:?}");

    assert!(!shown.contains(KEY));
    assert!(shown.contains("***"));
    assert!(shown.contains("https://example.invalid"));
    assert!(shown.contains("x-trace"));
}

#[tokio::test]
async fn a_builder_with_no_key_shows_none() {
    let builder = Client::builder().api_key("");
    assert!(format!("{builder:?}").contains("***"));
}

#[tokio::test]
async fn a_missing_key_fails_before_any_request() {
    let error = Client::builder()
        .api_key("")
        .build()
        .expect_err("an empty key is refused");
    assert!(error.to_string().contains("API key is required"));
}

#[tokio::test]
async fn a_single_read_that_matches_nothing_is_a_not_found() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(envelope(json!([]), 1, None)))
        .mount(&server)
        .await;

    let client = client_for(&server).await;
    let error = client
        .content()
        .details("con_missing", Default::default())
        .await
        .expect_err("an empty result set is a 404");

    assert!(error.is_not_found());
    assert_eq!(error.status(), Some(404));
}

#[tokio::test]
async fn errors_carry_the_api_code() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(401).set_body_json(json!({
            "log_id": "log_1",
            "error": {"code": "INVALID_API_KEY", "message": "Nope.", "details": {}}
        })))
        .mount(&server)
        .await;

    let client = client_for(&server).await;
    let error = client
        .content()
        .list(ContentListParams::default())
        .await
        .expect_err("a 401 is an error");

    assert_eq!(error.status(), Some(401));
    assert_eq!(error.code(), Some("INVALID_API_KEY"));
    assert_eq!(error.log_id(), Some("log_1"));
    assert!(error.is_unauthorized());
}

#[tokio::test]
async fn path_parameters_are_escaped() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(envelope(
            json!([content_row("con_1")]),
            1,
            None,
        )))
        .mount(&server)
        .await;

    let client = client_for(&server).await;
    let _ = client
        .content()
        .details("con/../../admin", Default::default())
        .await;

    let requests = server.received_requests().await.unwrap();
    assert!(requests[0].url.as_str().contains("con%2F..%2F..%2Fadmin"));
}

#[tokio::test]
async fn an_empty_path_parameter_is_rejected() {
    let client = Client::new(KEY).expect("client builds");
    let error = client
        .content()
        .details("", Default::default())
        .await
        .expect_err("an empty id is refused");
    assert!(error.to_string().contains("must not be empty"));
}

#[tokio::test]
async fn a_rate_limited_read_is_retried() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(429).insert_header("retry-after", "0"))
        .up_to_n_times(1)
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(envelope(
            json!([content_row("con_1")]),
            1,
            None,
        )))
        .mount(&server)
        .await;

    let client = Client::builder()
        .api_key(KEY)
        .base_url(server.uri())
        .max_retries(2)
        .build()
        .unwrap();
    let page = client
        .content()
        .list(ContentListParams::default())
        .await
        .unwrap();

    assert_eq!(page.results.len(), 1);
    assert_eq!(server.received_requests().await.unwrap().len(), 2);
}

#[tokio::test]
async fn a_write_is_not_retried_by_default() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(503).set_body_json(json!({
            "error": {"code": "SERVICE_UNAVAILABLE", "message": "Down."}
        })))
        .mount(&server)
        .await;

    let client = Client::builder()
        .api_key(KEY)
        .base_url(server.uri())
        .max_retries(3)
        .build()
        .unwrap();
    let params = zelf::resources::creator_sync::CreatorSyncCreateParams {
        profile_url: "https://www.tiktok.com/@zelf".into(),
    };
    let _ = client.creator_sync().create(params).await;

    // The API has no idempotency key, so a retried create could run twice.
    assert_eq!(server.received_requests().await.unwrap().len(), 1);
}

#[tokio::test]
async fn a_client_error_is_never_retried() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(400).set_body_json(json!({
            "error": {"code": "VALIDATION_ERROR", "message": "Bad."}
        })))
        .mount(&server)
        .await;

    let client = Client::builder()
        .api_key(KEY)
        .base_url(server.uri())
        .max_retries(3)
        .build()
        .unwrap();
    let _ = client.content().list(ContentListParams::default()).await;

    assert_eq!(server.received_requests().await.unwrap().len(), 1);
}
