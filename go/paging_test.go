package zelf

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

// pagedServer serves `count` pages of one row each, and counts the requests.
func pagedServer(t *testing.T, count int) (*Client, *atomic.Int32) {
	t.Helper()
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		page := int(calls.Add(1))
		next := "null"
		if page < count {
			next = fmt.Sprintf("%d", page+1)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, envelopeJSON(fmt.Sprintf(`[{"id":"con_%d"}]`, page), page, next))
	}))
	t.Cleanup(server.Close)

	client, err := New(WithAPIKey(testKey), WithBaseURL(server.URL), WithMaxRetries(0))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return client, &calls
}

func collect(t *testing.T, client *Client, opts ...PageOption) ([]string, error) {
	t.Helper()
	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	var ids []string
	err = page.AutoPaging(context.Background(), func(item Content) error {
		ids = append(ids, item.Id)
		return nil
	}, opts...)
	return ids, err
}

func TestMaxPagesStopsTheWalkEarly(t *testing.T) {
	client, calls := pagedServer(t, 5)

	ids, err := collect(t, client, MaxPages(3))
	if err != nil {
		t.Fatalf("AutoPaging: %v", err)
	}
	if strings.Join(ids, ",") != "con_1,con_2,con_3" {
		t.Fatalf("walked %v", ids)
	}
	if calls.Load() != 3 {
		t.Fatalf("made %d requests, want 3", calls.Load())
	}
}

func TestMaxPagesOfOneMakesNoFurtherRequest(t *testing.T) {
	client, calls := pagedServer(t, 5)

	ids, err := collect(t, client, MaxPages(1))
	if err != nil {
		t.Fatalf("AutoPaging: %v", err)
	}
	if strings.Join(ids, ",") != "con_1" || calls.Load() != 1 {
		t.Fatalf("walked %v in %d requests", ids, calls.Load())
	}
}

func TestMaxItemsStopsBeforeAPageItDoesNotNeed(t *testing.T) {
	client, calls := pagedServer(t, 5)

	ids, err := collect(t, client, MaxItems(2))
	if err != nil {
		t.Fatalf("AutoPaging: %v", err)
	}
	if strings.Join(ids, ",") != "con_1,con_2" || calls.Load() != 2 {
		t.Fatalf("walked %v in %d requests", ids, calls.Load())
	}
}

func TestNoLimitWalksEverything(t *testing.T) {
	client, calls := pagedServer(t, 4)

	ids, err := collect(t, client)
	if err != nil {
		t.Fatalf("AutoPaging: %v", err)
	}
	if strings.Join(ids, ",") != "con_1,con_2,con_3,con_4" || calls.Load() != 4 {
		t.Fatalf("walked %v in %d requests", ids, calls.Load())
	}
}

func TestALimitBelowOneIsRejected(t *testing.T) {
	client, calls := pagedServer(t, 3)

	for _, opt := range []PageOption{MaxPages(0), MaxPages(-1), MaxItems(0)} {
		if _, err := collect(t, client, opt); !errors.Is(err, ErrBadLimit) {
			t.Errorf("expected ErrBadLimit, got %v", err)
		}
	}
	// Only the initial List call per collect, never a second page.
	if calls.Load() != 3 {
		t.Fatalf("made %d requests, want 3 initial calls only", calls.Load())
	}
}

func TestAllRangesOverTheRemainingItems(t *testing.T) {
	client, _ := pagedServer(t, 3)
	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	var ids []string
	for item, err := range page.All(context.Background()) {
		if err != nil {
			t.Fatalf("All: %v", err)
		}
		ids = append(ids, item.Id)
	}
	if strings.Join(ids, ",") != "con_1,con_2,con_3" {
		t.Fatalf("walked %v", ids)
	}
}

func TestAllStopsWhenTheCallerBreaks(t *testing.T) {
	client, calls := pagedServer(t, 5)
	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	for item, err := range page.All(context.Background()) {
		if err != nil {
			t.Fatalf("All: %v", err)
		}
		if item.Id == "con_2" {
			break
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("made %d requests after breaking, want 2", calls.Load())
	}
}

func TestAllSurfacesABadLimit(t *testing.T) {
	client, _ := pagedServer(t, 2)
	page, err := client.Content.List(context.Background(), &ContentListParams{Search: Ptr("x")})
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	for _, iterErr := range page.All(context.Background(), MaxItems(0)) {
		if !errors.Is(iterErr, ErrBadLimit) {
			t.Fatalf("expected ErrBadLimit, got %v", iterErr)
		}
		break
	}
}
