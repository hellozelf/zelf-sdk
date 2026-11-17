package zelf

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func reportCases(t *testing.T) map[string]map[string]json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "fixtures", "fixtures.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixtures struct {
		Reports map[string]map[string]json.RawMessage `json:"reports"`
	}
	if err := json.Unmarshal(raw, &fixtures); err != nil {
		t.Fatal(err)
	}
	return fixtures.Reports
}

func TestReportsDecodeSoftly(t *testing.T) {
	targets := map[string]func() any{
		"AiAnalysisReport":         func() any { return &AiAnalysisReport{} },
		"AdvancedAiAnalysisReport": func() any { return &AdvancedAiAnalysisReport{} },
		"CreatorVettingReport":     func() any { return &CreatorVettingReport{} },
	}
	for name, cases := range reportCases(t) {
		for kind, document := range cases {
			if err := json.Unmarshal(document, targets[name]()); err != nil {
				t.Errorf("%s.%s: %v", name, kind, err)
			}
		}
	}
}

func TestReportDecimalRoundsToNearestWhole(t *testing.T) {
	var report AdvancedAiAnalysisReport
	if err := json.Unmarshal(reportCases(t)["AdvancedAiAnalysisReport"]["decimals"], &report); err != nil {
		t.Fatal(err)
	}
	if report.Summary.Videos != 13 || report.TopCreators[0].Posts != 13 {
		t.Fatalf("got %d and %d, want 13", report.Summary.Videos, report.TopCreators[0].Posts)
	}
}

func TestReportIntReadsWholeNullAndRejectsText(t *testing.T) {
	var summary AdvancedSummary
	if err := json.Unmarshal([]byte(`{"videos": 9007199254740993, "creators": null}`), &summary); err != nil {
		t.Fatal(err)
	}
	if summary.Videos != 9007199254740993 || summary.Creators != 0 {
		t.Fatalf("got %d and %d", summary.Videos, summary.Creators)
	}
	if err := json.Unmarshal([]byte(`{"videos": "many"}`), &summary); err == nil {
		t.Fatal("text in a whole number field should still fail")
	}
}

func TestReportNullableIntReadsDecimal(t *testing.T) {
	var profile AdvancedCreatorProfile
	if err := json.Unmarshal([]byte(`{"partnership_fit": 71.5}`), &profile); err != nil {
		t.Fatal(err)
	}
	if got, _ := profile.PartnershipFit.Get(); got != 72 {
		t.Fatalf("got %d, want 72", got)
	}
}
