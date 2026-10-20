package zelf

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

const testKey = "sk_test_not_a_real_key"

type capture struct {
	requests []*http.Request
	bodies   []string
}

func envelopeJSON(results string, page int, next string) string {
	return fmt.Sprintf(
		`{"log_id":"log_1","timestamp":"2026-01-01T00:00:00Z","applied_filters":{"page":%d},`+
			`"results":%s,"item_count":1,"page":%d,"next":%s,"previous":null}`,
		page, results, page, next,
	)
}

const contentRow = `{"id":"con_1","platform":"instagram","view_count":184230}`

func newServer(t *testing.T, handler http.HandlerFunc) (*Client, *capture) {
	t.Helper()
	seen := &capture{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		seen.requests = append(seen.requests, r)
		seen.bodies = append(seen.bodies, string(body))
		w.Header().Set("Content-Type", "application/json")
		handler(w, r)
	}))
	t.Cleanup(server.Close)

	client, err := New(WithAPIKey(testKey), WithBaseURL(server.URL), WithMaxRetries(0))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return client, seen
}

func TestListReturnsATypedPage(t *testing.T) {
	client, seen := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, envelopeJSON("["+contentRow+"]", 1, "null"))
	})

	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("running shoes")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(page.Results) != 1 || page.Results[0].Id != "con_1" {
		t.Fatalf("unexpected results: %+v", page.Results)
	}
	if page.HasNext() {
		t.Error("page should not report a next page")
	}
	if got := seen.requests[0].URL.Query().Get("search"); got != "running shoes" {
		t.Errorf("search = %q", got)
	}
}

func TestTheAPIKeyTravelsInAHeaderNeverTheURL(t *testing.T) {
	client, seen := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, envelopeJSON(`[{"plan":"pro"}]`, 1, "null"))
	})

	if _, err := client.Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	request := seen.requests[0]
	if request.Header.Get("x-api-key") != testKey {
		t.Error("the api key is not in the x-api-key header")
	}
	if strings.Contains(request.URL.String(), testKey) {
		t.Error("the api key leaked into the url")
	}
	if !strings.HasPrefix(request.Header.Get("User-Agent"), "zelf-go/") {
		t.Errorf("User-Agent = %q", request.Header.Get("User-Agent"))
	}
}

func TestAMissingKeyFailsBeforeAnyRequest(t *testing.T) {
	t.Setenv(APIKeyEnv, "")
	if _, err := New(); err == nil {
		t.Fatal("expected an error when no api key is configured")
	}
}

func TestTheKeyFallsBackToTheEnvironment(t *testing.T) {
	t.Setenv(APIKeyEnv, "sk_from_env")
	if _, err := New(); err != nil {
		t.Fatalf("New: %v", err)
	}
}

func TestTheBaseURLFallsBackToTheEnvironment(t *testing.T) {
	t.Setenv(APIKeyEnv, "sk_from_env")
	t.Setenv(BaseURLEnv, "https://staging-api.hellozelf.com")
	client, err := New()
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if client.t.baseURL != "https://staging-api.hellozelf.com" {
		t.Errorf("baseURL = %q", client.t.baseURL)
	}
}

func TestASingleReadThatMatchesNothingIsANotFound(t *testing.T) {
	client, _ := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, envelopeJSON("[]", 1, "null"))
	})

	_, err := client.Content.Details(context.Background(), "con_missing", nil)
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Status != http.StatusNotFound {
		t.Fatalf("expected a 404 APIError, got %v", err)
	}
	if !errors.Is(err, ErrNotFound) {
		t.Error("errors.Is(err, ErrNotFound) should match")
	}
}

func TestAutoPagingWalksEveryPage(t *testing.T) {
	var calls atomic.Int32
	client, seen := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		switch calls.Add(1) {
		case 1:
			fmt.Fprint(w, envelopeJSON(`[{"id":"con_1"}]`, 1, "2"))
		case 2:
			fmt.Fprint(w, envelopeJSON(`[{"id":"con_2"}]`, 2, "3"))
		default:
			fmt.Fprint(w, envelopeJSON(`[{"id":"con_3"}]`, 3, "null"))
		}
	})

	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	var ids []string
	if err := page.AutoPaging(context.Background(), func(item Content) error {
		ids = append(ids, item.Id)
		return nil
	}); err != nil {
		t.Fatalf("AutoPaging: %v", err)
	}
	if strings.Join(ids, ",") != "con_1,con_2,con_3" {
		t.Fatalf("walked %v", ids)
	}
	for index, want := range []string{"", "2", "3"} {
		if got := seen.requests[index].URL.Query().Get("page"); got != want {
			t.Errorf("request %d page = %q, want %q", index, got, want)
		}
	}
}

func TestErrorsCarryTheAPICode(t *testing.T) {
	client, _ := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		fmt.Fprint(w, `{"log_id":"log_1","error":{"code":"INVALID_API_KEY","message":"Nope.","details":{}}}`)
	})

	_, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected an APIError, got %v", err)
	}
	if apiErr.Status != 401 || apiErr.Code != CodeInvalidAPIKey || apiErr.LogID != "log_1" {
		t.Fatalf("unexpected error: %+v", apiErr)
	}
	if !errors.Is(err, ErrAuthentication) {
		t.Error("errors.Is(err, ErrAuthentication) should match")
	}
}

func TestARateLimitedReadIsRetried(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if calls.Add(1) == 1 {
			w.Header().Set("Retry-After", "0")
			w.WriteHeader(http.StatusTooManyRequests)
			fmt.Fprint(w, `{"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Slow down."}}`)
			return
		}
		fmt.Fprint(w, envelopeJSON("["+contentRow+"]", 1, "null"))
	}))
	defer server.Close()

	client, err := New(WithAPIKey(testKey), WithBaseURL(server.URL), WithMaxRetries(2))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")}); err != nil {
		t.Fatalf("List: %v", err)
	}
	if calls.Load() != 2 {
		t.Fatalf("expected 2 calls, got %d", calls.Load())
	}
}

func TestAWriteIsNotRetriedByDefault(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		fmt.Fprint(w, `{"error":{"code":"SERVICE_UNAVAILABLE","message":"Down."}}`)
	}))
	defer server.Close()

	client, err := New(WithAPIKey(testKey), WithBaseURL(server.URL), WithMaxRetries(3))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	body := CreatorSyncCreateJSONRequestBody{ProfileUrl: "https://www.tiktok.com/@zelf"}
	if _, err := client.CreatorSync.Create(context.Background(), body); err == nil {
		t.Fatal("expected an error")
	}
	if calls.Load() != 1 {
		t.Fatalf("a write with no idempotency key was retried %d times", calls.Load()-1)
	}
}

func TestAClientErrorIsNeverRetried(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		fmt.Fprint(w, `{"error":{"code":"VALIDATION_ERROR","message":"Bad."}}`)
	}))
	defer server.Close()

	client, _ := New(WithAPIKey(testKey), WithBaseURL(server.URL), WithMaxRetries(3))
	if _, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")}); err == nil {
		t.Fatal("expected an error")
	}
	if calls.Load() != 1 {
		t.Fatalf("a 400 was retried %d times", calls.Load()-1)
	}
}

func TestRequestBodiesAreSentAsJSON(t *testing.T) {
	client, seen := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
		fmt.Fprint(w, envelopeJSON(`[{"id":"ana_1"}]`, 1, "null"))
	})

	body := AiAnalysisCreateJSONRequestBody{
		Name:           "Launch sentiment",
		Topic:          "sentiment",
		ContentFilters: ContentFilterInputRequest{Search: Ptr("zelf")},
	}
	if _, err := client.AIAnalysis.Create(context.Background(), body); err != nil {
		t.Fatalf("Create: %v", err)
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(seen.bodies[0]), &sent); err != nil {
		t.Fatalf("body was not json: %v", err)
	}
	if sent["name"] != "Launch sentiment" || sent["topic"] != "sentiment" {
		t.Fatalf("unexpected body: %v", sent)
	}
}

func TestPathParametersAreEscaped(t *testing.T) {
	client, seen := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, envelopeJSON("["+contentRow+"]", 1, "null"))
	})

	if _, err := client.Content.Details(context.Background(), "con/../../admin", nil); err != nil {
		t.Fatalf("Details: %v", err)
	}
	if got := seen.requests[0].URL.EscapedPath(); !strings.Contains(got, "con%2F..%2F..%2Fadmin") {
		t.Fatalf("path = %q, the id was not escaped", got)
	}
}

func TestContextCancellationStopsTheCall(t *testing.T) {
	client, _ := newServer(t, func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, envelopeJSON("[]", 1, "null"))
	})

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := client.Content.List(ctx, &ContentListParams{Search: Ptr("x")}); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}
