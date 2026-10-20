//go:build e2e

package e2e

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"

	zelf "github.com/hellozelf/zelf-sdk/go"
)

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func newClient(t *testing.T, opts ...zelf.Option) *zelf.Client {
	t.Helper()
	base := []zelf.Option{
		zelf.WithAPIKey(env("ZELF_API_KEY", "sk_zelf_sandbox_demo")),
		zelf.WithBaseURL(env("ZELF_BASE_URL", "https://sandbox-api.hellozelf.com")),
	}
	client, err := zelf.New(append(base, opts...)...)
	if err != nil {
		t.Fatalf("building client: %v", err)
	}
	return client
}

func TestUsageDecodes(t *testing.T) {
	if _, err := newClient(t).Usage.Retrieve(context.Background()); err != nil {
		t.Fatalf("usage: %v", err)
	}
}

func TestAPageDecodesEveryRow(t *testing.T) {
	page, err := newClient(t).Content.List(context.Background(),
		&zelf.ContentListParams{PageSize: zelf.Ptr(2)})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if page.ItemCount != 2 {
		t.Fatalf("item_count = %d", page.ItemCount)
	}
	for _, row := range page.Results {
		if !strings.HasPrefix(row.Id, "con_") {
			t.Errorf("id = %q", row.Id)
		}
	}
}

func TestAutoPagingStopsAtTheBound(t *testing.T) {
	page, err := newClient(t).Content.List(context.Background(),
		&zelf.ContentListParams{PageSize: zelf.Ptr(2)})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	seen := 0
	if err := page.AutoPaging(context.Background(), func(zelf.Content) error {
		seen++
		return nil
	}, zelf.MaxPages(2)); err != nil {
		t.Fatalf("walk: %v", err)
	}
	if seen != 4 {
		t.Errorf("walked %d rows, want 4", seen)
	}
}

func TestABadKeyRaisesTheTypedError(t *testing.T) {
	client := newClient(t, zelf.WithAPIKey("sk_zelf_"+strings.Repeat("9", 64)), zelf.WithMaxRetries(0))
	_, err := client.Usage.Retrieve(context.Background())
	var api *zelf.APIError
	if !errors.As(err, &api) {
		t.Fatalf("err = %T %v", err, err)
	}
	if api.Status != 401 || api.Code != "INVALID_API_KEY" {
		t.Errorf("status = %d code = %q", api.Status, api.Code)
	}
}

func TestARateLimitIsRetriedThenSurfaced(t *testing.T) {
	client := newClient(t,
		zelf.WithMaxRetries(1),
		zelf.WithHeader("x-sandbox-force-error", "RATE_LIMIT_EXCEEDED"))
	_, err := client.Usage.Retrieve(context.Background())
	var api *zelf.APIError
	if !errors.As(err, &api) || api.Status != 429 {
		t.Errorf("err = %v", err)
	}
}

func TestEventTypesAreListed(t *testing.T) {
	events, err := newClient(t).Webhooks.ListEvents(context.Background())
	if err != nil || len(events) == 0 {
		t.Errorf("events = %v, %v", len(events), err)
	}
}
