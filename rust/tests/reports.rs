use std::collections::HashMap;

use serde_json::Value;
use zelf::{
    AdvancedAiAnalysisReport, AdvancedCreatorProfile, AiAnalysisReport, CreatorVettingReport,
};

fn report_cases() -> HashMap<String, HashMap<String, Value>> {
    let raw = include_str!("../../fixtures/fixtures.json");
    let fixtures: Value = serde_json::from_str(raw).unwrap();
    serde_json::from_value(fixtures["reports"].clone()).unwrap()
}

#[test]
fn reports_decode_softly() {
    for (name, cases) in report_cases() {
        for (kind, document) in cases {
            let decoded = match name.as_str() {
                "AiAnalysisReport" => {
                    serde_json::from_value::<AiAnalysisReport>(document).map(|_| ())
                }
                "AdvancedAiAnalysisReport" => {
                    serde_json::from_value::<AdvancedAiAnalysisReport>(document).map(|_| ())
                }
                "CreatorVettingReport" => {
                    serde_json::from_value::<CreatorVettingReport>(document).map(|_| ())
                }
                other => panic!("unknown report {other}"),
            };
            assert!(decoded.is_ok(), "{name}.{kind}: {decoded:?}");
        }
    }
}

#[test]
fn report_decimal_rounds_to_nearest_whole() {
    let document = report_cases()["AdvancedAiAnalysisReport"]["decimals"].clone();
    let report: AdvancedAiAnalysisReport = serde_json::from_value(document).unwrap();
    assert_eq!(report.summary.videos, 13);
    assert_eq!(report.top_creators[0].posts, 13);
}

#[test]
fn report_null_and_missing_read_as_empty() {
    let report: CreatorVettingReport = serde_json::from_str(r#"{"violations": null}"#).unwrap();
    assert!(report.profile_summary.is_none());
    assert!(report.violations.is_empty());

    let profile: AdvancedCreatorProfile =
        serde_json::from_str(r#"{"handle": null, "partnership_fit": 71.5}"#).unwrap();
    assert_eq!(profile.handle, "");
    assert_eq!(profile.partnership_fit, Some(72));
}
