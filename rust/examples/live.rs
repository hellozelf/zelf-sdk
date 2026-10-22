use std::time::Instant;

use zelf::resources::brand_accounts::BrandAccountsListParams;
use zelf::resources::content::{ContentDetailsParams, ContentListParams};
use zelf::{Client, Limits};

const BRAND: &str = "brd_6u599tNI2jemKDcb";

fn scope() -> ContentListParams {
    ContentListParams {
        brand_id: Some(BRAND.into()),
        posted_within_days: Some(365),
        view_count_min: Some(250_000_000),
        page_size: Some(3),
        ..Default::default()
    }
}

fn report(name: &str, started: Instant, outcome: Result<String, String>) {
    let (status, detail) = match outcome {
        Ok(detail) => ("PASS", detail),
        Err(detail) => ("FAIL", detail),
    };
    let detail: String = detail.chars().take(90).collect();
    println!(
        "{name:<34} {status}  {:>6}ms  {detail}",
        started.elapsed().as_millis()
    );
}

#[tokio::main]
async fn main() {
    let key = std::env::var("ZELF_API_KEY").expect("ZELF_API_KEY");
    let client = Client::new(&key).expect("client builds");

    let started = Instant::now();
    report(
        "usage.retrieve",
        started,
        client
            .usage()
            .retrieve()
            .await
            .map(|_| "usage ok".to_string())
            .map_err(|e| e.to_string()),
    );

    let started = Instant::now();
    report(
        "content.list",
        started,
        client
            .content()
            .list(scope())
            .await
            .map(|page| {
                format!(
                    "items={} first={} views={:?}",
                    page.item_count, page.results[0].id, page.results[0].view_count
                )
            })
            .map_err(|e| e.to_string()),
    );

    let started = Instant::now();
    let walked = async {
        let page = client
            .content()
            .list(scope())
            .await
            .map_err(|e| e.to_string())?;
        let rows = page
            .collect_all(Limits::pages(2))
            .await
            .map_err(|e| e.to_string())?;
        Ok::<String, String>(format!("walked {} across <=2 pages", rows.len()))
    }
    .await;
    report("content.list collect_all pages(2)", started, walked);

    let started = Instant::now();
    let detailed = async {
        let page = client
            .content()
            .list(scope())
            .await
            .map_err(|e| e.to_string())?;
        let found = client
            .content()
            .details(
                &page.results[0].id,
                ContentDetailsParams {
                    brand_id: Some(BRAND.into()),
                },
            )
            .await
            .map_err(|e| e.to_string())?;
        Ok::<String, String>(format!("id={} platform={}", found.id, found.platform))
    }
    .await;
    report("content.details", started, detailed);

    let started = Instant::now();
    let missing = match client
        .content()
        .details("con_J64wsBXg9rmhOE6dFX", ContentDetailsParams::default())
        .await
    {
        Ok(_) => Err("no error raised".to_string()),
        Err(error) => Ok(format!(
            "status={:?} code={:?}",
            error.status(),
            error.code()
        )),
    };
    report("content.details (missing)", started, missing);

    let started = Instant::now();
    let bad = Client::builder()
        .api_key("sk_zelf_definitely_invalid")
        .max_retries(0)
        .build()
        .expect("client builds");
    let unauthorised = match bad.usage().retrieve().await {
        Ok(_) => Err("no error raised".to_string()),
        Err(error) => Ok(format!(
            "{:?} {:?} unauthorized={}",
            error.status(),
            error.code(),
            error.is_unauthorized()
        )),
    };
    report("bad key -> 401 typed", started, unauthorised);

    let started = Instant::now();
    report(
        "brands.list",
        started,
        client
            .brands()
            .list(Default::default())
            .await
            .map(|page| format!("brands={}", page.item_count))
            .map_err(|e| e.to_string()),
    );

    let started = Instant::now();
    report(
        "webhooks.list_events",
        started,
        client
            .webhooks()
            .list_events()
            .await
            .map(|events| format!("events={}", events.len()))
            .map_err(|e| e.to_string()),
    );

    let started = Instant::now();
    report(
        "brand_accounts.list",
        started,
        client
            .brand_accounts()
            .list(BrandAccountsListParams {
                brand_id: Some(BRAND.into()),
                account_type: Some("tracked".into()),
            })
            .await
            .map(|groups| {
                format!(
                    "tracked={}",
                    groups.tracked.as_ref().map_or(0, |tracked| tracked.len())
                )
            })
            .map_err(|e| e.to_string()),
    );
}
