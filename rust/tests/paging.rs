use serde_json::json;
use wiremock::matchers::method;
use wiremock::{Mock, MockServer, ResponseTemplate};

use zelf::resources::content::ContentListParams;
use zelf::{Client, Limits};

const KEY: &str = "sk_test_not_a_real_key";

fn row(id: &str) -> serde_json::Value {
    let raw = include_str!("../../fixtures/fixtures.json");
    let fixtures: serde_json::Value = serde_json::from_str(raw).unwrap();
    let mut out = fixtures["envelopes"]["content_list"]["results"][0].clone();
    out["id"] = json!(id);
    out
}

/// Serves `count` pages of one row each.
async fn paged_server(count: i64) -> (MockServer, Client) {
    let server = MockServer::start().await;
    for page in 1..=count {
        let next = if page < count {
            json!(page + 1)
        } else {
            json!(null)
        };
        let template = ResponseTemplate::new(200).set_body_json(json!({
            "log_id": "log_1",
            "timestamp": "2026-01-01T00:00:00Z",
            "applied_filters": {},
            "results": [row(&format!("con_{page}"))],
            "item_count": 1,
            "page": page,
            "next": next,
            "previous": null,
        }));
        Mock::given(method("GET"))
            .respond_with(template)
            .up_to_n_times(1)
            .with_priority((page as u8) + 1)
            .mount(&server)
            .await;
    }
    let client = Client::builder()
        .api_key(KEY)
        .base_url(server.uri())
        .max_retries(0)
        .build()
        .unwrap();
    (server, client)
}

async fn walk(client: &Client, limits: Limits) -> Vec<String> {
    let page = client
        .content()
        .list(ContentListParams::default())
        .await
        .expect("first page");
    page.collect_all(limits)
        .await
        .expect("walk succeeds")
        .into_iter()
        .map(|item| item.id)
        .collect()
}

#[tokio::test]
async fn max_pages_stops_the_walk_early() {
    let (server, client) = paged_server(5).await;

    let ids = walk(&client, Limits::pages(3)).await;

    assert_eq!(ids, ["con_1", "con_2", "con_3"]);
    assert_eq!(server.received_requests().await.unwrap().len(), 3);
}

#[tokio::test]
async fn max_pages_of_one_makes_no_further_request() {
    let (server, client) = paged_server(5).await;

    let ids = walk(&client, Limits::pages(1)).await;

    assert_eq!(ids, ["con_1"]);
    assert_eq!(server.received_requests().await.unwrap().len(), 1);
}

#[tokio::test]
async fn max_items_stops_before_a_page_it_does_not_need() {
    let (server, client) = paged_server(5).await;

    let ids = walk(&client, Limits::items(2)).await;

    assert_eq!(ids, ["con_1", "con_2"]);
    assert_eq!(server.received_requests().await.unwrap().len(), 2);
}

#[tokio::test]
async fn no_limit_walks_everything() {
    let (server, client) = paged_server(4).await;

    let ids = walk(&client, Limits::default()).await;

    assert_eq!(ids, ["con_1", "con_2", "con_3", "con_4"]);
    assert_eq!(server.received_requests().await.unwrap().len(), 4);
}

#[tokio::test]
async fn a_limit_below_one_is_rejected() {
    let (_server, client) = paged_server(3).await;
    let page = client
        .content()
        .list(ContentListParams::default())
        .await
        .unwrap();

    for limits in [Limits::pages(0), Limits::items(0)] {
        let error = page
            .collect_all(limits)
            .await
            .expect_err("a zero limit is refused");
        assert!(error.to_string().contains("1 or greater"));
    }
}

#[tokio::test]
async fn for_each_visits_every_item_and_honours_limits() {
    let (_server, client) = paged_server(4).await;
    let page = client
        .content()
        .list(ContentListParams::default())
        .await
        .unwrap();

    let mut seen = Vec::new();
    page.for_each(Limits::items(3), |item| {
        seen.push(item.id.clone());
        Ok(())
    })
    .await
    .unwrap();

    assert_eq!(seen, ["con_1", "con_2", "con_3"]);
}
