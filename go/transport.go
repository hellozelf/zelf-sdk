package zelf

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"

	"github.com/oapi-codegen/nullable"
)

const (
	// DefaultBaseURL is the production Zelf API.
	DefaultBaseURL = "https://api.hellozelf.com"
	// APIKeyEnv is read when no key is passed explicitly.
	APIKeyEnv = "ZELF_API_KEY"
	// BaseURLEnv is read when no base URL is passed explicitly.
	BaseURLEnv = "ZELF_BASE_URL"

	defaultTimeout = 60 * time.Second
	defaultRetries = 2
	maxBackoff     = 8 * time.Second
	maxBodyBytes   = 8 << 20
)

var retryStatuses = map[int]bool{429: true, 500: true, 502: true, 503: true, 504: true}

// The API documents no Idempotency-Key header, so a retried write could create
// a second analysis, vetting, or sync job. Writes are retried only on request.
var retrySafeMethods = map[string]bool{
	http.MethodGet:     true,
	http.MethodHead:    true,
	http.MethodOptions: true,
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

// Option configures a Client.
type Option func(*config)

type config struct {
	apiKey      string
	baseURL     string
	timeout     time.Duration
	maxRetries  int
	retryWrites bool
	headers     map[string]string
	httpClient  *http.Client
}

// WithAPIKey sets the brand API key. Without it the ZELF_API_KEY environment
// variable is used.
func WithAPIKey(key string) Option { return func(c *config) { c.apiKey = key } }

// WithBaseURL points the client at a different deployment.
func WithBaseURL(url string) Option { return func(c *config) { c.baseURL = url } }

// WithTimeout bounds each individual HTTP attempt.
func WithTimeout(d time.Duration) Option { return func(c *config) { c.timeout = d } }

// WithMaxRetries sets how many times a retryable response is retried.
func WithMaxRetries(n int) Option { return func(c *config) { c.maxRetries = n } }

// WithRetryWrites allows non-idempotent requests to be retried. The API
// publishes no idempotency key, so a retried create can run twice. Opt in only
// when the caller can tolerate that.
func WithRetryWrites(enabled bool) Option { return func(c *config) { c.retryWrites = enabled } }

// WithHeader adds a header to every request.
func WithHeader(name, value string) Option {
	return func(c *config) {
		if c.headers == nil {
			c.headers = map[string]string{}
		}
		c.headers[name] = value
	}
}

// WithHTTPClient supplies the http.Client used for transport.
func WithHTTPClient(client *http.Client) Option {
	return func(c *config) { c.httpClient = client }
}

type transport struct {
	httpClient  *http.Client
	apiKey      string
	headers     map[string]string
	maxRetries  int
	retryWrites bool
	baseURL     string
}

func newTransport(opts ...Option) (*transport, error) {
	cfg := config{
		apiKey:     os.Getenv(APIKeyEnv),
		baseURL:    envOr(BaseURLEnv, DefaultBaseURL),
		timeout:    defaultTimeout,
		maxRetries: defaultRetries,
	}
	for _, apply := range opts {
		apply(&cfg)
	}
	if cfg.apiKey == "" {
		return nil, fmt.Errorf("zelf: an API key is required; pass WithAPIKey or set %s", APIKeyEnv)
	}
	if cfg.maxRetries < 0 {
		return nil, errors.New("zelf: WithMaxRetries needs a value of zero or greater")
	}

	httpClient := cfg.httpClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: cfg.timeout}
	}

	return &transport{
		httpClient:  httpClient,
		apiKey:      cfg.apiKey,
		headers:     callerHeaders(cfg.headers),
		maxRetries:  cfg.maxRetries,
		retryWrites: cfg.retryWrites,
		baseURL:     strings.TrimRight(cfg.baseURL, "/"),
	}, nil
}

func (t *transport) resolve(path string, pathParams []string, params any) (string, error) {
	for i := 0; i+1 < len(pathParams); i += 2 {
		name, value := pathParams[i], pathParams[i+1]
		if value == "" {
			return "", fmt.Errorf("zelf: %s is required and must not be empty", name)
		}
		path = strings.ReplaceAll(path, "{"+name+"}", url.PathEscape(value))
	}
	query, err := encodeQuery(params)
	if err != nil {
		return "", err
	}
	if query != "" {
		return t.baseURL + path + "?" + query, nil
	}
	return t.baseURL + path, nil
}

// encodeQuery reads the `form` tags oapi-codegen puts on every *Params struct.
func encodeQuery(params any) (string, error) {
	if params == nil {
		return "", nil
	}
	value := reflect.ValueOf(params)
	for value.Kind() == reflect.Ptr {
		if value.IsNil() {
			return "", nil
		}
		value = value.Elem()
	}
	if value.Kind() != reflect.Struct {
		return "", fmt.Errorf("zelf: query parameters must be a struct, got %s", value.Kind())
	}

	out := url.Values{}
	target := value.Type()
	for i := 0; i < target.NumField(); i++ {
		name, _, _ := strings.Cut(target.Field(i).Tag.Get("form"), ",")
		if name == "" || name == "-" {
			continue
		}
		field := value.Field(i)
		for field.Kind() == reflect.Ptr {
			if field.IsNil() {
				break
			}
			field = field.Elem()
		}
		if field.Kind() == reflect.Ptr || !field.IsValid() {
			continue
		}
		if field.Kind() == reflect.Slice || field.Kind() == reflect.Array {
			for j := 0; j < field.Len(); j++ {
				out.Add(name, scalar(field.Index(j)))
			}
			continue
		}
		out.Add(name, scalar(field))
	}
	return out.Encode(), nil
}

// callerHeaders drops any header that would collide with the API key, so a
// differently cased copy of it cannot be sent alongside the client's own.
func callerHeaders(supplied map[string]string) map[string]string {
	out := make(map[string]string, len(supplied))
	for name, value := range supplied {
		if strings.EqualFold(name, "x-api-key") {
			continue
		}
		out[name] = value
	}
	return out
}

// scalar renders one query value, already dereferenced by encodeQuery.
func scalar(value reflect.Value) string {
	switch value.Kind() {
	case reflect.String:
		return value.String()
	case reflect.Bool:
		return strconv.FormatBool(value.Bool())
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return strconv.FormatInt(value.Int(), 10)
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return strconv.FormatUint(value.Uint(), 10)
	case reflect.Float32, reflect.Float64:
		// The field's own width, or a float32 widens to its binary neighbour
		// and 0.0425 reaches the wire as 0.042500000447034836.
		return strconv.FormatFloat(value.Float(), 'f', -1, value.Type().Bits())
	}
	if value.CanInterface() {
		// time.Time is a struct whose String method renders a display form the
		// API rejects, and time.Now also carries a monotonic reading. UTC drops
		// that reading, and RFC 3339 is the form the API documents.
		switch when := value.Interface().(type) {
		case time.Time:
			return when.UTC().Format(time.RFC3339)
		case *time.Time:
			if when == nil {
				return ""
			}
			return when.UTC().Format(time.RFC3339)
		}
		if stringer, ok := value.Interface().(fmt.Stringer); ok {
			return stringer.String()
		}
	}
	return fmt.Sprint(value.Interface())
}

func (t *transport) send(ctx context.Context, method, target string, body any) (*http.Response, error) {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("zelf: encoding the request body: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, target, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "zelf-go/"+Version)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for name, value := range t.headers {
		req.Header.Set(name, value)
	}
	// Last, so the client's own key always wins.
	req.Header.Set("x-api-key", t.apiKey)
	return t.httpClient.Do(req)
}

type envelope[T any] struct {
	LogID          string          `json:"log_id"`
	Timestamp      time.Time       `json:"timestamp"`
	AppliedFilters json.RawMessage `json:"applied_filters"`
	Results        []T             `json:"results"`
	ItemCount      int             `json:"item_count"`
	PageNumber     int             `json:"page"`
	Next           *int            `json:"next"`
	Previous       *int            `json:"previous"`
}

type call func(ctx context.Context) (*http.Response, error)

// request is what every generated resource method calls. pathParams is a flat
// name, value sequence.
func request[T any](
	ctx context.Context,
	t *transport,
	method, path string,
	pathParams []string,
	params any,
	body any,
) (*envelope[T], error) {
	target, err := t.resolve(path, pathParams, params)
	if err != nil {
		return nil, err
	}
	return do[T](ctx, t, method, func(ctx context.Context) (*http.Response, error) {
		return t.send(ctx, method, target, body)
	})
}

func do[T any](ctx context.Context, t *transport, method string, send call) (*envelope[T], error) {
	var lastErr error
	for attempt := 0; ; attempt++ {
		resp, err := send(ctx)
		status := 0
		if err == nil {
			status = resp.StatusCode
			if status < 400 {
				return decode[T](resp)
			}
			lastErr = readAPIError(resp)
		} else {
			lastErr = &ConnectionError{Err: err}
		}
		if ctxErr := ctx.Err(); ctxErr != nil {
			return nil, ctxErr
		}
		if attempt >= t.maxRetries || !shouldRetry(method, status, err != nil, t.retryWrites) {
			return nil, lastErr
		}
		wait := backoff(attempt, resp)
		drain(resp)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(wait):
		}
	}
}

func shouldRetry(method string, status int, transportFailure, retryWrites bool) bool {
	if !retrySafeMethods[method] && !retryWrites {
		return false
	}
	return transportFailure || retryStatuses[status]
}

func backoff(attempt int, resp *http.Response) time.Duration {
	if resp != nil {
		if header := resp.Header.Get("Retry-After"); header != "" {
			if seconds, err := strconv.ParseFloat(header, 64); err == nil && seconds >= 0 {
				return min(time.Duration(seconds*float64(time.Second)), time.Minute)
			}
		}
	}
	base := min(maxBackoff, time.Duration(500*(1<<attempt))*time.Millisecond)
	return time.Duration(float64(base) * (0.5 + rand.Float64()/2))
}

func decode[T any](resp *http.Response) (*envelope[T], error) {
	defer drain(resp)
	if resp.StatusCode == http.StatusNoContent {
		return &envelope[T]{}, nil
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))
	if err != nil {
		return nil, &ConnectionError{Err: err}
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return &envelope[T]{}, nil
	}
	var out envelope[T]
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, &APIError{
			Status:  resp.StatusCode,
			Message: "the API returned a response that is not a valid JSON envelope",
		}
	}
	return &out, nil
}

func drain(resp *http.Response) {
	if resp == nil || resp.Body == nil {
		return
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, maxBodyBytes))
	_ = resp.Body.Close()
}

// Ptr returns a pointer to v. Optional request fields are pointers, so this
// keeps call sites to one line: zelf.Ptr("running shoes").
func Ptr[T any](v T) *T { return &v }

// Nullable is a field that can carry a value, carry JSON null, or be left out
// of the request entirely. The generated types use it wherever the API treats
// those three as different, so it is re-exported here and a caller never needs
// to import the generator's own dependency.
type Nullable[T any] = nullable.Nullable[T]

// Value fills a Nullable field: zelf.Value("running shoes").
func Value[T any](v T) Nullable[T] { return nullable.NewNullableWithValue(v) }

// Null sends JSON null for a Nullable field, which is not the same as leaving
// the field out: zelf.Null[string]().
func Null[T any]() Nullable[T] { return nullable.NewNullNullable[T]() }
