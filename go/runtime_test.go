package zelf

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"testing"
	"time"
)

const runtimeKey = "sk_zelf_" + "0000000000000000000000000000000000000000000000000000000000000000"

type scriptedRoundTripper struct {
	responses []*http.Response
	errs      []error
	calls     int
	requests  []*http.Request
}

func (s *scriptedRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	index := min(s.calls, len(s.responses)-1)
	s.calls++
	s.requests = append(s.requests, req)
	if s.errs != nil {
		if err := s.errs[min(len(s.errs)-1, index)]; err != nil {
			return nil, err
		}
	}
	resp := s.responses[index]
	return &http.Response{
		StatusCode: resp.StatusCode,
		Header:     resp.Header,
		Body:       io.NopCloser(strings.NewReader(bodyOf(resp))),
		Request:    req,
	}, nil
}

func bodyOf(resp *http.Response) string {
	if resp.Body == nil {
		return ""
	}
	raw, _ := io.ReadAll(resp.Body)
	return string(raw)
}

func jsonResponse(status int, body string, headers ...string) *http.Response {
	header := http.Header{"Content-Type": []string{"application/json"}}
	for i := 0; i+1 < len(headers); i += 2 {
		header.Set(headers[i], headers[i+1])
	}
	return &http.Response{
		StatusCode: status,
		Header:     header,
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func clientWith(t *testing.T, rt http.RoundTripper, opts ...Option) *Client {
	t.Helper()
	base := []Option{WithAPIKey(runtimeKey), WithMaxRetries(0), WithHTTPClient(&http.Client{Transport: rt})}
	client, err := New(append(base, opts...)...)
	if err != nil {
		t.Fatalf("building client: %v", err)
	}
	return client
}

func TestBaseURLIsReported(t *testing.T) {
	client := clientWith(t, &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "{}")}},
		WithBaseURL("https://sandbox-api.hellozelf.com"))
	if client.BaseURL() != "https://sandbox-api.hellozelf.com" {
		t.Errorf("BaseURL = %q", client.BaseURL())
	}
}

func TestOptionsAreApplied(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, `{"results":[{"brand_id":"brd_1"}],"item_count":1}`)}}
	client := clientWith(t, rt,
		WithTimeout(5*time.Second),
		WithRetryWrites(true),
		WithHeader("X-Trace", "abc"),
	)
	if _, err := client.Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("retrieve: %v", err)
	}
	if got := rt.requests[0].Header.Get("X-Trace"); got != "abc" {
		t.Errorf("custom header = %q", got)
	}
}

func TestAnAPIKeyIsRequired(t *testing.T) {
	t.Setenv(APIKeyEnv, "")
	if _, err := New(); err == nil {
		t.Error("expected a missing-key error")
	}
}

func TestNegativeRetriesAreRefused(t *testing.T) {
	if _, err := New(WithAPIKey(runtimeKey), WithMaxRetries(-1)); err == nil {
		t.Error("expected a bad-retries error")
	}
}

func TestTheKeyComesFromTheEnvironment(t *testing.T) {
	t.Setenv(APIKeyEnv, runtimeKey)
	if _, err := New(); err != nil {
		t.Errorf("env key rejected: %v", err)
	}
}

func TestErrorsPrintAndUnwrap(t *testing.T) {
	inner := errors.New("socket closed")
	conn := &ConnectionError{Err: inner}
	if conn.Error() == "" {
		t.Error("ConnectionError printed nothing")
	}
	if !errors.Is(conn, inner) {
		t.Error("ConnectionError did not unwrap")
	}
	api := &APIError{Status: 404, Code: "NOT_FOUND", Message: "Resource not found."}
	if !strings.Contains(api.Error(), "NOT_FOUND") {
		t.Errorf("APIError = %q", api.Error())
	}
}

func TestAnErrorBodyThatIsNotJSONStillRaises(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(500, "<html>")}}
	client := clientWith(t, rt)
	if _, err := client.Usage.Retrieve(context.Background()); err == nil {
		t.Error("expected an error")
	}
}

func TestAppliedFiltersDecodesIntoATarget(t *testing.T) {
	body := `{"log_id":"log_1","timestamp":"2026-01-01T00:00:00Z","applied_filters":{"page":1},"results":[],"item_count":0,"page":1,"next":null,"previous":null}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, body)}}
	client := clientWith(t, rt)

	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	var filters map[string]any
	if err := page.AppliedFilters(&filters); err != nil {
		t.Fatalf("applied filters: %v", err)
	}
	if filters["page"] != float64(1) {
		t.Errorf("applied filters = %v", filters)
	}
}

func TestAppliedFiltersIsEmptyWhenAbsent(t *testing.T) {
	body := `{"results":[],"item_count":0,"page":1}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, body)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	var filters map[string]any
	if err := page.AppliedFilters(&filters); err != nil {
		t.Errorf("applied filters: %v", err)
	}
}

func TestPagingBoundsAreValidated(t *testing.T) {
	body := `{"results":[],"item_count":0,"page":1,"next":2}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, body)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}

	if err := page.AutoPaging(context.Background(), func(Brand) error { return nil }, MaxPages(0)); !errors.Is(err, ErrBadLimit) {
		t.Errorf("MaxPages(0) = %v", err)
	}
	if err := page.AutoPaging(context.Background(), func(Brand) error { return nil }, MaxItems(0)); !errors.Is(err, ErrBadLimit) {
		t.Errorf("MaxItems(0) = %v", err)
	}
	for _, err := range page.All(context.Background(), MaxPages(0)) {
		if !errors.Is(err, ErrBadLimit) {
			t.Errorf("All with a bad limit = %v", err)
		}
	}
}

func TestAutoPagingStopsWhenTheVisitorFails(t *testing.T) {
	row := `{"id":"brd_1","title":"Zelf","is_primary":true,"keywords":{}}`
	first := `{"results":[` + row + `],"item_count":1,"page":1,"next":2}`
	second := `{"results":[` + row + `],"item_count":1,"page":2,"next":null}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, first), jsonResponse(200, second)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}

	stop := errors.New("stop")
	if err := page.AutoPaging(context.Background(), func(Brand) error { return stop }, MaxItems(5)); !errors.Is(err, stop) {
		t.Errorf("visitor error = %v", err)
	}
}

func TestAllYieldsEveryRow(t *testing.T) {
	row := `{"id":"brd_1","title":"Zelf","is_primary":true,"keywords":{}}`
	first := `{"results":[` + row + `],"item_count":1,"page":1,"next":2}`
	second := `{"results":[` + row + `],"item_count":1,"page":2,"next":null}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, first), jsonResponse(200, second)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}

	seen := 0
	for _, err := range page.All(context.Background(), MaxPages(2)) {
		if err != nil {
			t.Fatalf("walk: %v", err)
		}
		seen++
	}
	if seen != 2 {
		t.Errorf("walked %d rows, want 2", seen)
	}
}

func TestAllStopsEarlyWhenTheCallerBreaks(t *testing.T) {
	row := `{"id":"brd_1","title":"Zelf","is_primary":true,"keywords":{}}`
	first := `{"results":[` + row + `,` + row + `],"item_count":2,"page":1,"next":2}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, first)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	for range page.All(context.Background()) {
		break
	}
}

func TestNextPageReportsTheEnd(t *testing.T) {
	body := `{"results":[],"item_count":0,"page":1,"next":null}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, body)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if page.HasNext() {
		t.Error("HasNext on a last page")
	}
	next, err := page.NextPage(context.Background())
	if err != nil || next != nil {
		t.Errorf("NextPage = %v, %v", next, err)
	}
}

func TestAnEmptyPathParameterIsRefused(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "{}")}}
	client := clientWith(t, rt)
	if _, err := client.Content.Details(context.Background(), "", nil); err == nil {
		t.Error("expected a missing-path-parameter error")
	}
}

func TestQueryEncodingCoversEveryKind(t *testing.T) {
	type sample struct {
		Text   *string   `form:"text,omitempty"`
		Count  *int      `form:"count,omitempty"`
		Ratio  *float64  `form:"ratio,omitempty"`
		Flag   *bool     `form:"flag,omitempty"`
		Many   *[]string `form:"many,omitempty"`
		Absent *string   `form:"absent,omitempty"`
		Hidden string    `form:"-"`
		None   string
	}
	encoded, err := encodeQuery(&sample{
		Text:  Ptr("hello"),
		Count: Ptr(7),
		Ratio: Ptr(1.5),
		Flag:  Ptr(true),
		Many:  Ptr([]string{"a", "b"}),
	})
	if err != nil {
		t.Fatalf("encodeQuery: %v", err)
	}
	for _, want := range []string{"text=hello", "count=7", "ratio=1.5", "flag=true", "many=a", "many=b"} {
		if !strings.Contains(encoded, want) {
			t.Errorf("%q missing from %q", want, encoded)
		}
	}
	if strings.Contains(encoded, "absent") || strings.Contains(encoded, "Hidden") {
		t.Errorf("encoded an omitted field: %q", encoded)
	}
}

func TestQueryEncodingHandlesNilAndNonStructs(t *testing.T) {
	if got, err := encodeQuery(nil); err != nil || got != "" {
		t.Errorf("nil = %q, %v", got, err)
	}
	var typed *struct{}
	if got, err := encodeQuery(typed); err != nil || got != "" {
		t.Errorf("typed nil = %q, %v", got, err)
	}
	if _, err := encodeQuery(42); err == nil {
		t.Error("expected a non-struct error")
	}
}

func TestScalarFallsBackToStringer(t *testing.T) {
	type sample struct {
		When stringerValue `form:"when"`
	}
	encoded, err := encodeQuery(&sample{})
	if err != nil {
		t.Fatalf("encodeQuery: %v", err)
	}
	if !strings.Contains(encoded, "when=stringer") {
		t.Errorf("stringer not used: %q", encoded)
	}
}

func TestATransportFailureBecomesAConnectionError(t *testing.T) {
	rt := &scriptedRoundTripper{
		responses: []*http.Response{jsonResponse(200, "{}")},
		errs:      []error{errors.New("dial tcp: refused")},
	}
	client := clientWith(t, rt)
	_, err := client.Usage.Retrieve(context.Background())
	var conn *ConnectionError
	if !errors.As(err, &conn) {
		t.Errorf("err = %T %v", err, err)
	}
}

func TestARetryableStatusIsRetried(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(503, `{"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}`, "Retry-After", "0"),
		jsonResponse(200, `{"results":[{"brand_id":"brd_1"}],"item_count":1}`),
	}}
	client := clientWith(t, rt, WithMaxRetries(1))
	if _, err := client.Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("retrieve: %v", err)
	}
	if rt.calls != 2 {
		t.Errorf("made %d calls, want 2", rt.calls)
	}
}

func TestAnUnparseableRetryAfterFallsBackToBackoff(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(500, `{"error":{"code":"INTERNAL_ERROR","message":"boom"}}`, "Retry-After", "soon"),
		jsonResponse(200, `{"results":[{"brand_id":"brd_1"}],"item_count":1}`),
	}}
	client := clientWith(t, rt, WithMaxRetries(1))
	if _, err := client.Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("retrieve: %v", err)
	}
	if rt.calls != 2 {
		t.Errorf("made %d calls, want 2", rt.calls)
	}
}

func TestAWriteIsNotRetriedWithoutOptIn(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(503, `{"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}`),
	}}
	client := clientWith(t, rt, WithMaxRetries(2))
	_, err := client.AIAnalysis.Create(context.Background(), AiAnalysisCreateJSONRequestBody{})
	if err == nil {
		t.Fatal("expected an error")
	}
	if rt.calls != 1 {
		t.Errorf("retried a write %d times", rt.calls-1)
	}
}

func TestACancelledContextStopsTheWalk(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(500, `{"error":{"code":"INTERNAL_ERROR","message":"boom"}}`)}}
	client := clientWith(t, rt, WithMaxRetries(3))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := client.Usage.Retrieve(ctx); err == nil {
		t.Error("expected a context error")
	}
}

func TestANoContentResponseDecodesToAnEmptyEnvelope(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{{
		StatusCode: http.StatusNoContent,
		Header:     http.Header{},
		Body:       io.NopCloser(strings.NewReader("")),
	}}}
	client := clientWith(t, rt)
	if _, err := client.Webhooks.DeleteSubscription(context.Background(), "whs_1"); err == nil {
		t.Error("expected a no-result error for an empty 204 envelope")
	}
}

func TestAnEmptyBodyDecodesToAnEmptyEnvelope(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "   ")}}
	client := clientWith(t, rt)
	if _, err := client.Webhooks.DeleteSubscription(context.Background(), "whs_1"); err == nil {
		t.Error("expected a no-result error for an empty body")
	}
}

func TestABodyThatIsNotAnEnvelopeIsRejected(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "<html>")}}
	client := clientWith(t, rt)
	_, err := client.Usage.Retrieve(context.Background())
	var api *APIError
	if !errors.As(err, &api) {
		t.Errorf("err = %T %v", err, err)
	}
}

func TestUnionFieldsRoundTrip(t *testing.T) {
	var status WebhookSubscription_LastStatus
	if err := status.FromLastStatusEnum(LastStatusEnum("SUCCESS")); err != nil {
		t.Fatalf("from enum: %v", err)
	}
	if got, err := status.AsLastStatusEnum(); err != nil || got != "SUCCESS" {
		t.Errorf("as enum = %v, %v", got, err)
	}
	encoded, err := status.MarshalJSON()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var again WebhookSubscription_LastStatus
	if err := again.UnmarshalJSON(encoded); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if err := status.MergeLastStatusEnum(LastStatusEnum("FAILED")); err != nil {
		t.Errorf("merge: %v", err)
	}

	var blank WebhookSubscription_LastStatus
	if err := blank.FromBlankEnum(BlankEnum("")); err != nil {
		t.Fatalf("from blank: %v", err)
	}
	if _, err := blank.AsBlankEnum(); err != nil {
		t.Errorf("as blank: %v", err)
	}
	if err := blank.MergeBlankEnum(BlankEnum("")); err != nil {
		t.Errorf("merge blank: %v", err)
	}

	var resource WebhookSubscription_Resource
	if err := resource.FromResourceEnum(ResourceEnum("content")); err != nil {
		t.Fatalf("from resource: %v", err)
	}
	if _, err := resource.AsResourceEnum(); err != nil {
		t.Errorf("as resource: %v", err)
	}
	if err := resource.MergeResourceEnum(ResourceEnum("creator")); err != nil {
		t.Errorf("merge resource: %v", err)
	}
	if _, err := resource.MarshalJSON(); err != nil {
		t.Errorf("marshal resource: %v", err)
	}
	var nullEnum WebhookSubscription_Resource
	if err := nullEnum.FromNullEnum(NullEnum("")); err != nil {
		t.Fatalf("from null: %v", err)
	}
	if _, err := nullEnum.AsNullEnum(); err != nil {
		t.Errorf("as null: %v", err)
	}
	if err := nullEnum.MergeNullEnum(NullEnum("")); err != nil {
		t.Errorf("merge null: %v", err)
	}
	raw, _ := json.Marshal(map[string]string{"x": "y"})
	if err := nullEnum.UnmarshalJSON(raw); err != nil {
		t.Errorf("unmarshal null: %v", err)
	}
}

type stringerValue struct{}

func (stringerValue) String() string { return "stringer" }

func TestAPIErrorIncludesTheLogID(t *testing.T) {
	err := &APIError{Status: 409, Code: "CONFLICT", Message: "Nope.", LogID: "log_9"}
	if !strings.Contains(err.Error(), "log_id=log_9") {
		t.Errorf("Error() = %q", err.Error())
	}
	bare := &APIError{Status: 500, Message: "boom"}
	if strings.Contains(bare.Error(), "log_id") {
		t.Errorf("bare Error() = %q", bare.Error())
	}
}

func TestAnErrorBodyWithoutACodeKeepsTheDefaultMessage(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(503, `{"error":{"message":"no code"}}`)}}
	client := clientWith(t, rt)
	_, err := client.Usage.Retrieve(context.Background())
	var api *APIError
	if !errors.As(err, &api) {
		t.Fatalf("err = %T", err)
	}
	if !strings.Contains(api.Message, "HTTP 503") {
		t.Errorf("message = %q", api.Message)
	}
}

func TestAnErrorBodyWithACodeButNoMessageKeepsTheDefault(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(500, `{"error":{"code":"INTERNAL_ERROR"}}`)}}
	client := clientWith(t, rt)
	_, err := client.Usage.Retrieve(context.Background())
	var api *APIError
	if !errors.As(err, &api) {
		t.Fatalf("err = %T", err)
	}
	if api.Code != "INTERNAL_ERROR" || !strings.Contains(api.Message, "HTTP 500") {
		t.Errorf("code = %q message = %q", api.Code, api.Message)
	}
}

func TestPagingSurfacesAFailedFetch(t *testing.T) {
	row := `{"id":"brd_1","title":"Zelf","is_primary":true,"keywords":{}}`
	first := `{"results":[` + row + `],"item_count":1,"page":1,"next":2}`
	rt := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(200, first),
		jsonResponse(500, `{"error":{"code":"INTERNAL_ERROR","message":"boom"}}`),
	}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if _, err := page.NextPage(context.Background()); err == nil {
		t.Error("NextPage swallowed a 500")
	}

	rt.calls = 1
	if err := page.AutoPaging(context.Background(), func(Brand) error { return nil }); err == nil {
		t.Error("AutoPaging swallowed a 500")
	}

	rt.calls = 1
	seen := 0
	for _, err := range page.All(context.Background()) {
		if err != nil {
			seen++
		}
	}
	if seen == 0 {
		t.Error("All swallowed a 500")
	}
}

func TestAutoPagingStopsAtMaxItems(t *testing.T) {
	row := `{"id":"brd_1","title":"Zelf","is_primary":true,"keywords":{}}`
	first := `{"results":[` + row + `,` + row + `],"item_count":2,"page":1,"next":2}`
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, first)}}
	client := clientWith(t, rt)
	page, err := client.Brands.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	seen := 0
	if err := page.AutoPaging(context.Background(), func(Brand) error { seen++; return nil }, MaxItems(1)); err != nil {
		t.Fatalf("walk: %v", err)
	}
	if seen != 1 {
		t.Errorf("visited %d rows, want 1", seen)
	}

	rt.calls = 0
	seen = 0
	for range page.All(context.Background(), MaxItems(1)) {
		seen++
	}
	if seen != 1 {
		t.Errorf("All visited %d rows, want 1", seen)
	}
}

func TestAnUnbuildableRequestIsReported(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "{}")}}
	client := clientWith(t, rt, WithBaseURL("://not a url"))
	if _, err := client.Usage.Retrieve(context.Background()); err == nil {
		t.Error("expected a request-building error")
	}
}

func TestAnUnencodableBodyIsReported(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "{}")}}
	client := clientWith(t, rt)
	_, err := client.t.send(context.Background(), "POST", client.BaseURL()+"/x", make(chan int))
	if err == nil {
		t.Error("expected an encoding error")
	}
}

func TestDrainToleratesAMissingBody(t *testing.T) {
	drain(nil)
	drain(&http.Response{})
}

func TestScalarHandlesUnsignedAndFloat(t *testing.T) {
	type sample struct {
		Count *uint    `form:"count,omitempty"`
		Ratio *float32 `form:"ratio,omitempty"`
	}
	encoded, err := encodeQuery(&sample{Count: Ptr(uint(3)), Ratio: Ptr(float32(0.5))})
	if err != nil {
		t.Fatalf("encodeQuery: %v", err)
	}
	if !strings.Contains(encoded, "count=3") || !strings.Contains(encoded, "ratio=0.5") {
		t.Errorf("encoded = %q", encoded)
	}
}

type failingBody struct{}

func (failingBody) Read([]byte) (int, error) { return 0, errors.New("body went away") }
func (failingBody) Close() error             { return nil }

type bodyFailureRoundTripper struct{ status int }

func (b bodyFailureRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	return &http.Response{
		StatusCode: b.status,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       failingBody{},
		Request:    req,
	}, nil
}

func TestABodyThatFailsMidReadIsReported(t *testing.T) {
	client := clientWith(t, bodyFailureRoundTripper{status: 200})
	_, err := client.Usage.Retrieve(context.Background())
	var conn *ConnectionError
	if !errors.As(err, &conn) {
		t.Errorf("success path: err = %T %v", err, err)
	}

	client = clientWith(t, bodyFailureRoundTripper{status: 500})
	if _, err := client.Usage.Retrieve(context.Background()); err == nil {
		t.Error("error path swallowed a failing body")
	}
}

func TestResolveRejectsNonStructParams(t *testing.T) {
	client := clientWith(t, &scriptedRoundTripper{responses: []*http.Response{jsonResponse(200, "{}")}})
	if _, err := client.t.resolve("/api/v1/usage/", nil, 42); err == nil {
		t.Error("expected a non-struct params error")
	}
}

func TestScalarRendersTimesAsRFC3339(t *testing.T) {
	moment := time.Date(2026, 1, 1, 6, 0, 0, 500, time.FixedZone("+06", 6*3600))
	type sample struct {
		At    time.Time    `form:"at"`
		Also  *time.Time   `form:"also,omitempty"`
		Every []*time.Time `form:"every,omitempty"`
	}
	encoded, err := encodeQuery(&sample{At: moment, Also: &moment, Every: []*time.Time{&moment, nil}})
	if err != nil {
		t.Fatalf("encodeQuery: %v", err)
	}
	values, err := url.ParseQuery(encoded)
	if err != nil {
		t.Fatalf("ParseQuery: %v", err)
	}
	if got := values["at"]; !slices.Equal(got, []string{"2026-01-01T00:00:00Z"}) {
		t.Errorf("at = %q", got)
	}
	if got := values["also"]; !slices.Equal(got, []string{"2026-01-01T00:00:00Z"}) {
		t.Errorf("also = %q", got)
	}
	if got := values["every"]; !slices.Equal(got, []string{"2026-01-01T00:00:00Z", ""}) {
		t.Errorf("every = %q", got)
	}
}

func TestNullableHelpersBuildEveryState(t *testing.T) {
	set := Value("running shoes")
	if got, err := set.Get(); err != nil || got != "running shoes" {
		t.Errorf("Value = %q, %v", got, err)
	}
	empty := Null[string]()
	if !empty.IsNull() {
		t.Error("Null did not produce a null")
	}
	var absent Nullable[string]
	if absent.IsSpecified() {
		t.Error("the zero value should leave the field out")
	}
}

func TestACallerHeaderCannotReplaceTheAPIKey(t *testing.T) {
	recorder := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(200, `{"results":[{"brand_id":"brd_1"}],"item_count":1}`),
	}}
	client, err := New(
		WithAPIKey("sk_zelf_real"),
		WithMaxRetries(0),
		WithHeader("X-API-Key", "sk_zelf_forged"),
		WithHeader("x-trace-id", "trace_1"),
		WithHTTPClient(&http.Client{Transport: recorder}),
	)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, err := client.Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	sent := recorder.requests[0].Header
	if got := sent.Values("x-api-key"); !slices.Equal(got, []string{"sk_zelf_real"}) {
		t.Errorf("x-api-key = %q", got)
	}
	if got := sent.Get("x-trace-id"); got != "trace_1" {
		t.Errorf("an unrelated caller header was dropped: %q", got)
	}
}

func TestScalarRendersAnUnhandledKind(t *testing.T) {
	type sample struct {
		Weird map[string]string `form:"weird"`
	}
	if _, err := encodeQuery(&sample{Weird: map[string]string{"a": "b"}}); err != nil {
		t.Errorf("encodeQuery: %v", err)
	}
}

func TestACancelledContextStopsTheBackoffSleep(t *testing.T) {
	rt := &scriptedRoundTripper{responses: []*http.Response{
		jsonResponse(503, `{"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}`, "Retry-After", "30"),
	}}
	client := clientWith(t, rt, WithMaxRetries(3))
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if _, err := client.Usage.Retrieve(ctx); err == nil {
		t.Error("expected a context error")
	}
}
