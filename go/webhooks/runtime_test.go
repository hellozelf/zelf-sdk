package webhooks

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestParseRejectsABodyThatIsNotTheDeliveryEnvelope(t *testing.T) {
	payload := []byte(`"a bare string"`)
	now := time.Now()
	_, err := Parse(payload, sign(payload, secret, now.Unix()), []string{secret}, Options{Now: now})
	if !errors.Is(err, ErrVerification) {
		t.Errorf("err = %v", err)
	}
}

func TestParseSurfacesAVerificationFailure(t *testing.T) {
	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	if _, err := Parse(payload, "t=1,v1=deadbeef", []string{secret}, Options{}); err == nil {
		t.Error("Parse accepted a bad signature")
	}
}

func TestRowsReportsADownloadFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	event := &Event{Files: []File{{DownloadURL: server.URL}}}
	err := event.Rows(context.Background(), func(map[string]any) error { return nil }, DownloadOptions{})
	if err == nil || !strings.Contains(err.Error(), "HTTP 500") {
		t.Errorf("err = %v", err)
	}
}

func TestRowsReportsAnUnreachableHost(t *testing.T) {
	event := &Event{Files: []File{{DownloadURL: "http://127.0.0.1:1/missing"}}}
	if err := event.Rows(context.Background(), func(map[string]any) error { return nil }, DownloadOptions{}); err == nil {
		t.Error("Rows swallowed a connection failure")
	}
}

func TestRowsRejectsAnUnbuildableURL(t *testing.T) {
	event := &Event{Files: []File{{DownloadURL: "://nope"}}}
	if err := event.Rows(context.Background(), func(map[string]any) error { return nil }, DownloadOptions{}); err == nil {
		t.Error("Rows accepted a malformed URL")
	}
}

func TestOnRefusesAnEmptyEventList(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Error("On accepted no event types")
		}
	}()
	NewHandler([]string{secret}, Options{}).On(func(context.Context, *Event) error { return nil })
}

func TestOnRefusesAnUnknownEventType(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Error("On accepted an unknown event type")
		}
	}()
	NewHandler([]string{secret}, Options{}).On(func(context.Context, *Event) error { return nil }, EventType("content.exploded"))
}

func TestHandleSurfacesAParseFailure(t *testing.T) {
	handler := NewHandler([]string{secret}, Options{})
	if _, err := handler.Handle(context.Background(), []byte("{}"), "t=1,v1=bad"); err == nil {
		t.Error("Handle accepted a bad signature")
	}
}

func TestASignatureWithTwoTimestampsIsRefused(t *testing.T) {
	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	if _, err := Verify(payload, "t=1,t=2,v1=abcd", []string{secret}, Options{Tolerance: -1}); err == nil {
		t.Error("accepted two timestamps")
	}
}

func TestASignatureWithANonHexDigestIsRefused(t *testing.T) {
	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	now := time.Now()
	raw := "t=" + strconv.FormatInt(now.Unix(), 10) + ",v1=nothex!!"
	if _, err := Verify(payload, raw, []string{secret}, Options{Now: now}); err == nil {
		t.Error("accepted a non-hex digest")
	}
}

func TestParseRejectsAnEnvelopeWithTheWrongFieldTypes(t *testing.T) {
	payload := []byte(`{"id":"whd_1","delivered_at":"not a number"}`)
	now := time.Now()
	_, err := Parse(payload, sign(payload, secret, now.Unix()), []string{secret}, Options{Now: now})
	if !errors.Is(err, ErrVerification) {
		t.Errorf("err = %v", err)
	}
}

type truncatedBody struct{ reads int }

func (t *truncatedBody) Read([]byte) (int, error) { return 0, errors.New("connection reset") }
func (t *truncatedBody) Close() error             { return nil }

func TestRowsReportsABodyThatFailsMidRead(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	event := &Event{Files: []File{{DownloadURL: server.URL}}}
	if err := event.Rows(context.Background(), func(map[string]any) error { return nil }, DownloadOptions{}); err == nil {
		t.Error("Rows swallowed a truncated body")
	}
}

func TestRowsRejectsALineThatIsNotJSON(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("not json\n"))
	}))
	defer server.Close()

	event := &Event{Files: []File{{DownloadURL: server.URL}}}
	err := event.Rows(context.Background(), func(map[string]any) error { return nil },
		DownloadOptions{SkipChecksum: true})
	if err == nil {
		t.Error("Rows accepted a malformed line")
	}
}

func TestRowsStopsWhenTheVisitorFails(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"id":"con_1"}` + "\n"))
	}))
	defer server.Close()

	stop := errors.New("stop")
	event := &Event{Files: []File{{DownloadURL: server.URL}}}
	err := event.Rows(context.Background(), func(map[string]any) error { return stop },
		DownloadOptions{SkipChecksum: true})
	if !errors.Is(err, stop) {
		t.Errorf("err = %v", err)
	}
}

func TestHandleSurfacesAListenerFailure(t *testing.T) {
	payload := snapshot(EventContentSnapshot, map[string]any{"item_count": 0})
	now := time.Now()
	stop := errors.New("stop")
	handler := NewHandler([]string{secret}, Options{Now: now}).
		On(func(context.Context, *Event) error { return stop }, EventContentSnapshot)

	if _, err := handler.Handle(context.Background(), payload, sign(payload, secret, now.Unix())); !errors.Is(err, stop) {
		t.Errorf("err = %v", err)
	}
}
