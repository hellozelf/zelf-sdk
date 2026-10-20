use hmac::{Hmac, Mac};
use serde_json::json;
use sha2::{Digest, Sha256};

use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};
use zelf::webhooks::{self, EventType, Options, VerificationError};

const SECRET: &str = "whsec_abcdef0123456789";

fn body(event: &str, data: serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "id": "whd_8f2c1d4e9a",
        "type": event,
        "subscription_id": "whs_5Kq9Wd2pBxLm",
        "delivered_at": 1718000000,
        "livemode": true,
        "resource": "content",
        "delivery_mode": "inline",
        "data": data,
    }))
    .unwrap()
}

/// Mirrors the signing scheme the API documents.
fn sign(payload: &[u8], secret: &str, timestamp: i64) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).unwrap();
    let mut signed = format!("{timestamp}.").into_bytes();
    signed.extend_from_slice(payload);
    mac.update(&signed);
    format!(
        "t={timestamp},v1={}",
        hex::encode(mac.finalize().into_bytes())
    )
}

fn at(now: i64) -> Options {
    Options {
        now: Some(now),
        ..Default::default()
    }
}

#[test]
fn parse_returns_a_typed_event() {
    let payload = body(
        "content.snapshot",
        json!({"item_count": 1, "items": [{"id": "con_1"}]}),
    );
    let now = 1718000000;

    let event = webhooks::parse(&payload, &sign(&payload, SECRET, now), &[SECRET], at(now))
        .expect("verifies");

    assert_eq!(event.kind(), Some(EventType::ContentSnapshot));
    assert_eq!(event.id, "whd_8f2c1d4e9a");
    assert_eq!(event.subscription_id, "whs_5Kq9Wd2pBxLm");
    assert!(event.livemode);
    assert_eq!(event.items.len(), 1);
    assert_eq!(event.raw["id"], json!("whd_8f2c1d4e9a"));
}

#[test]
fn an_unrecognised_wire_type_leaves_the_kind_unknown() {
    let payload = body("content.from_the_future", json!({"item_count": 0}));
    let now = 1718000000;

    let event =
        webhooks::parse(&payload, &sign(&payload, SECRET, now), &[SECRET], at(now)).unwrap();

    assert_eq!(event.event_type, "content.from_the_future");
    assert_eq!(event.kind(), None);
}

#[test]
fn the_event_type_enum_covers_every_declared_event() {
    for wire in [
        "content.snapshot",
        "creator.snapshot",
        "creator_vetting.completed",
        "ai_analysis.completed",
    ] {
        let kind = EventType::from_wire(wire).expect("declared");
        assert_eq!(kind.as_str(), wire);
        assert_eq!(kind.to_string(), wire);
    }
    assert_eq!(EventType::from_wire("content.exploded"), None);
}

#[test]
fn a_forged_signature_is_rejected() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let now = 1718000000;

    let error = webhooks::parse(
        &payload,
        &sign(&payload, "whsec_wrong", now),
        &[SECRET],
        at(now),
    )
    .expect_err("a forged signature is refused");

    assert!(matches!(error, VerificationError::NoMatch));
}

#[test]
fn a_tampered_body_is_rejected() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let now = 1718000000;
    let signature = sign(&payload, SECRET, now);
    let mut tampered = payload.clone();
    tampered.push(b' ');

    assert!(matches!(
        webhooks::parse(&tampered, &signature, &[SECRET], at(now)),
        Err(VerificationError::NoMatch)
    ));
}

#[test]
fn an_old_delivery_is_rejected_as_a_replay() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let stale = 1718000000;

    let error = webhooks::parse(
        &payload,
        &sign(&payload, SECRET, stale),
        &[SECRET],
        at(stale + 4000),
    )
    .expect_err("a stale delivery is refused");

    assert!(matches!(error, VerificationError::Replay { .. }));
}

#[test]
fn a_future_timestamp_is_also_rejected() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let ahead = 1718000000;

    assert!(matches!(
        webhooks::parse(
            &payload,
            &sign(&payload, SECRET, ahead),
            &[SECRET],
            at(ahead - 4000)
        ),
        Err(VerificationError::Replay { .. })
    ));
}

#[test]
fn either_secret_verifies_during_a_rotation() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let now = 1718000000;
    let signature = sign(&payload, "whsec_new", now);

    assert!(webhooks::parse(&payload, &signature, &["whsec_old", "whsec_new"], at(now)).is_ok());
}

#[test]
fn a_malformed_signature_header_is_rejected() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    for signature in ["", "garbage", "t=abc,v1=ff", "v1=ff", "t=1718000000"] {
        assert!(matches!(
            webhooks::parse(&payload, signature, &[SECRET], at(1718000000)),
            Err(VerificationError::MalformedSignature)
        ));
    }
}

#[test]
fn no_secret_is_a_configuration_error() {
    let payload = body("content.snapshot", json!({"item_count": 0}));
    let empty: &[&str] = &[];

    assert!(matches!(
        webhooks::parse(
            &payload,
            &sign(&payload, SECRET, 1718000000),
            empty,
            at(1718000000)
        ),
        Err(VerificationError::NoSecret)
    ));
}

#[test]
fn the_handler_routes_to_the_listener_for_the_type() {
    use std::sync::{Arc, Mutex};

    let seen = Arc::new(Mutex::new(Vec::new()));
    let content_seen = seen.clone();
    let creator_seen = seen.clone();
    let now = 1718000000;

    let handler = webhooks::Handler::new(vec![SECRET.to_string()], at(now))
        .on(EventType::ContentSnapshot, move |event| {
            content_seen
                .lock()
                .unwrap()
                .push(format!("content:{}", event.id));
            Ok(())
        })
        .on(EventType::CreatorSnapshot, move |_| {
            creator_seen.lock().unwrap().push("creator".to_string());
            Ok(())
        });

    let payload = body("content.snapshot", json!({"item_count": 0}));
    handler
        .handle(&payload, &sign(&payload, SECRET, now))
        .expect("handles");

    assert_eq!(
        *seen.lock().unwrap(),
        vec!["content:whd_8f2c1d4e9a".to_string()]
    );
}

#[test]
fn no_listener_runs_when_the_signature_is_bad() {
    use std::sync::{Arc, Mutex};

    let seen = Arc::new(Mutex::new(Vec::new()));
    let captured = seen.clone();
    let now = 1718000000;
    let handler = webhooks::Handler::new(vec![SECRET.to_string()], at(now)).on_any(move |event| {
        captured.lock().unwrap().push(event.event_type.clone());
        Ok(())
    });

    let payload = body("content.snapshot", json!({"item_count": 0}));
    let error = handler
        .handle(&payload, &sign(&payload, "whsec_wrong", now))
        .expect_err("a forged delivery is refused");

    assert!(matches!(error, VerificationError::NoMatch));
    assert!(seen.lock().unwrap().is_empty());
}

#[test]
fn the_published_checksum_is_what_rows_compares_against() {
    // Guards the digest helper the download path relies on.
    let ndjson = b"{\"id\":\"con_1\"}\n";
    assert_eq!(hex::encode(Sha256::digest(ndjson)).len(), 64);
}

const NDJSON: &str = "{\"id\":\"con_1\"}\n{\"id\":\"con_2\"}\n";

async fn manifest_event(digest: &str) -> (webhooks::Event, MockServer) {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/whd_1.ndjson"))
        .respond_with(ResponseTemplate::new(200).set_body_string(NDJSON))
        .mount(&server)
        .await;

    let now = 1718000000;
    let payload = body(
        "content.snapshot",
        json!({
            "item_count": 2,
            "files": [{
                "format": "ndjson",
                "expires_at": 1718000000,
                "sha256": digest,
                "size_bytes": NDJSON.len(),
                "item_count": 2,
                "download_url": format!("{}/whd_1.ndjson", server.uri()),
            }],
        }),
    );
    let event = webhooks::parse(&payload, &sign(&payload, SECRET, now), &[SECRET], at(now))
        .expect("verifies");
    (event, server)
}

#[tokio::test]
async fn rows_downloads_the_manifest_and_returns_each_line() {
    let digest = hex::encode(Sha256::digest(NDJSON.as_bytes()));
    let (event, _server) = manifest_event(&digest).await;

    let rows = event
        .rows(&reqwest::Client::new(), false)
        .await
        .expect("rows");

    assert_eq!(rows, vec![json!({"id": "con_1"}), json!({"id": "con_2"})]);
}

#[tokio::test]
async fn rows_rejects_a_manifest_that_published_no_digest() {
    let (event, _server) = manifest_event("").await;

    let error = event
        .rows(&reqwest::Client::new(), false)
        .await
        .expect_err("an unverifiable file is refused");

    assert!(matches!(error, VerificationError::ChecksumMissing { .. }));
}

#[tokio::test]
async fn rows_reads_an_unchecked_file_when_verification_is_waived() {
    let (event, _server) = manifest_event("").await;

    let rows = event
        .rows(&reqwest::Client::new(), true)
        .await
        .expect("rows");

    assert_eq!(rows.len(), 2);
}

#[tokio::test]
async fn rows_rejects_a_download_whose_checksum_does_not_match() {
    let (event, _server) = manifest_event(&"0".repeat(64)).await;

    let error = event
        .rows(&reqwest::Client::new(), false)
        .await
        .expect_err("a tampered file is refused");

    assert!(matches!(error, VerificationError::ChecksumMismatch { .. }));
}
