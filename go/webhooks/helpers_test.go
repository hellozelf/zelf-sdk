package webhooks

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func snapshot(eventType EventType, data map[string]any) []byte {
	body := map[string]any{
		"id":              "whd_8f2c1d4e9a",
		"type":            string(eventType),
		"subscription_id": "whs_5Kq9Wd2pBxLm",
		"delivered_at":    1718000000,
		"livemode":        true,
		"resource":        "content",
		"delivery_mode":   "inline",
		"data":            data,
	}
	out, _ := json.Marshal(body)
	return out
}

func TestParseReturnsATypedEvent(t *testing.T) {
	payload := snapshot(EventContentSnapshot, map[string]any{
		"item_count": 1,
		"items":      []map[string]any{{"id": "con_1"}},
	})
	now := time.Now()

	event, err := Parse(payload, sign(payload, secret, now.Unix()), []string{secret}, Options{Now: now})
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if event.Type != EventContentSnapshot || event.ID != "whd_8f2c1d4e9a" {
		t.Fatalf("unexpected event: %+v", event)
	}
	if !event.Livemode || event.SubscriptionID != "whs_5Kq9Wd2pBxLm" {
		t.Fatalf("unexpected event: %+v", event)
	}
	if event.DeliveredAt.UTC().Year() != 2024 {
		t.Fatalf("DeliveredAt = %v", event.DeliveredAt)
	}
	if len(event.Items) != 1 || event.Items[0]["id"] != "con_1" {
		t.Fatalf("Items = %v", event.Items)
	}
	if event.Raw["id"] != "whd_8f2c1d4e9a" {
		t.Fatalf("Raw did not survive: %v", event.Raw)
	}
}

func TestEveryDeclaredEventTypeHasAConstant(t *testing.T) {
	for _, name := range []EventType{
		EventContentSnapshot, EventCreatorSnapshot,
		EventCreatorVettingCompleted, EventAIAnalysisCompleted,
	} {
		if !name.Valid() {
			t.Errorf("%q is not reported as a declared event type", name)
		}
		if name.String() == "" {
			t.Errorf("%q has no wire value", name)
		}
	}
	if EventType("content.exploded").Valid() {
		t.Error("an undeclared event type reported itself as valid")
	}
}

func TestTheHandlerRoutesToTheListenerForTheType(t *testing.T) {
	var seen []string
	handler := NewHandler([]string{secret}, Options{}).
		On(func(_ context.Context, e *Event) error { seen = append(seen, "content:"+e.ID); return nil }, EventContentSnapshot).
		On(func(_ context.Context, _ *Event) error { seen = append(seen, "creator"); return nil }, EventCreatorSnapshot)

	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	now := time.Now()
	handler.options = Options{Now: now}
	if _, err := handler.Handle(context.Background(), payload, sign(payload, secret, now.Unix())); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	if len(seen) != 1 || seen[0] != "content:whd_8f2c1d4e9a" {
		t.Fatalf("seen = %v", seen)
	}
}

func TestAnUnmatchedEventFallsBackOrIsANoOp(t *testing.T) {
	now := time.Now()
	payload := snapshot(EventAIAnalysisCompleted, map[string]any{"item_count": 0})
	signature := sign(payload, secret, now.Unix())

	var seen []string
	withFallback := NewHandler([]string{secret}, Options{Now: now}).
		OnAny(func(_ context.Context, e *Event) error { seen = append(seen, e.Type.String()); return nil })
	if _, err := withFallback.Handle(context.Background(), payload, signature); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	if len(seen) != 1 || seen[0] != EventAIAnalysisCompleted.String() {
		t.Fatalf("seen = %v", seen)
	}

	bare := NewHandler([]string{secret}, Options{Now: now})
	if _, err := bare.Handle(context.Background(), payload, signature); err != nil {
		t.Fatalf("a handler with no listener should not error: %v", err)
	}
}

func TestRegisteringAnUnknownEventTypePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected a panic for an unknown event type")
		}
	}()
	NewHandler([]string{secret}, Options{}).
		On(func(context.Context, *Event) error { return nil }, "content.exploded")
}

func TestNoListenerRunsWhenTheSignatureIsBad(t *testing.T) {
	now := time.Now()
	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	var seen []string
	handler := NewHandler([]string{secret}, Options{Now: now}).
		OnAny(func(_ context.Context, e *Event) error { seen = append(seen, e.Type.String()); return nil })

	_, err := handler.Handle(context.Background(), payload, sign(payload, "whsec_wrong", now.Unix()))
	if !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
	if len(seen) != 0 {
		t.Fatalf("a listener ran on an unverified delivery: %v", seen)
	}
}

const ndjson = "{\"id\":\"con_1\"}\n{\"id\":\"con_2\"}\n"

func manifestFor(t *testing.T, url, digest string) ([]byte, string, time.Time) {
	t.Helper()
	payload := snapshot(EventContentSnapshot, map[string]any{
		"item_count": 2,
		"files": []map[string]any{{
			"format": "ndjson", "expires_at": 1718000000, "sha256": digest,
			"size_bytes": len(ndjson), "item_count": 2, "download_url": url,
		}},
	})
	now := time.Now()
	return payload, sign(payload, secret, now.Unix()), now
}

func TestRowsDownloadsTheManifestAndVisitsEachLine(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, ndjson)
	}))
	defer server.Close()
	sum := sha256.Sum256([]byte(ndjson))

	payload, signature, now := manifestFor(t, server.URL, hex.EncodeToString(sum[:]))
	event, err := Parse(payload, signature, []string{secret}, Options{Now: now})
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}

	var ids []string
	if err := event.Rows(context.Background(), func(row map[string]any) error {
		ids = append(ids, row["id"].(string))
		return nil
	}, DownloadOptions{}); err != nil {
		t.Fatalf("Rows: %v", err)
	}
	if len(ids) != 2 || ids[0] != "con_1" || ids[1] != "con_2" {
		t.Fatalf("ids = %v", ids)
	}
}

func TestRowsRejectsADownloadWhoseChecksumDoesNotMatch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, "{\"id\":\"tampered\"}\n")
	}))
	defer server.Close()
	sum := sha256.Sum256([]byte(ndjson))

	payload, signature, now := manifestFor(t, server.URL, hex.EncodeToString(sum[:]))
	event, _ := Parse(payload, signature, []string{secret}, Options{Now: now})

	err := event.Rows(context.Background(), func(map[string]any) error {
		t.Fatal("a row was visited despite the checksum mismatch")
		return nil
	}, DownloadOptions{})
	if !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestRowsRejectsAManifestThatPublishedNoDigest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, ndjson)
	}))
	defer server.Close()

	payload, signature, now := manifestFor(t, server.URL, "")
	event, _ := Parse(payload, signature, []string{secret}, Options{Now: now})

	err := event.Rows(context.Background(), func(map[string]any) error {
		t.Fatal("a row was visited although nothing could be verified")
		return nil
	}, DownloadOptions{})
	if !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestRowsReadsAnUncheckedFileWhenVerificationIsWaived(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, ndjson)
	}))
	defer server.Close()

	payload, signature, now := manifestFor(t, server.URL, "")
	event, _ := Parse(payload, signature, []string{secret}, Options{Now: now})

	count := 0
	err := event.Rows(context.Background(), func(map[string]any) error {
		count++
		return nil
	}, DownloadOptions{SkipChecksum: true})
	if err != nil || count != 2 {
		t.Fatalf("Rows: err = %v, rows = %d", err, count)
	}
}

func TestRowsSurfacesAFailedDownload(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	}))
	defer server.Close()

	payload, signature, now := manifestFor(t, server.URL, "")
	event, _ := Parse(payload, signature, []string{secret}, Options{Now: now})

	if err := event.Rows(context.Background(), func(map[string]any) error { return nil }, DownloadOptions{}); err == nil {
		t.Fatal("expected an error for HTTP 403")
	}
}
