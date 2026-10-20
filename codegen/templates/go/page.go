package zelf

import (
	"context"
	"encoding/json"
	"errors"
	"iter"
	"net/http"
)

// PageOption bounds how far a walk over the remaining pages goes.
type PageOption func(*pageLimits)

type pageLimits struct {
	maxPages int
	maxItems int
	err      error
}

// ErrBadLimit is returned when MaxPages or MaxItems is given a value below 1.
var ErrBadLimit = errors.New("zelf: MaxPages and MaxItems need a value of 1 or greater")

// MaxPages stops the walk after n pages, counting the one already in hand. A
// value of 1 makes no further request.
func MaxPages(n int) PageOption {
	return func(l *pageLimits) {
		if n < 1 {
			l.err = ErrBadLimit
		}
		l.maxPages = n
	}
}

// MaxItems stops the walk once n items have been visited, so no page is
// requested that is not needed to reach n.
func MaxItems(n int) PageOption {
	return func(l *pageLimits) {
		if n < 1 {
			l.err = ErrBadLimit
		}
		l.maxItems = n
	}
}

func limitsFrom(opts []PageOption) (pageLimits, error) {
	limits := pageLimits{}
	for _, apply := range opts {
		apply(&limits)
	}
	return limits, limits.err
}

// Page holds one page of results plus the envelope metadata that came with it.
type Page[T any] struct {
	Results  []T
	LogID    string
	Page     int
	ItemCount int
	Next     *int
	Previous *int

	appliedFilters json.RawMessage
	fetch          func(ctx context.Context, page int) (*envelope[T], error)
}

// AppliedFilters decodes the effective filters the API reports back, which
// explains an empty result set.
func (p *Page[T]) AppliedFilters(into any) error {
	if len(p.appliedFilters) == 0 {
		return nil
	}
	return json.Unmarshal(p.appliedFilters, into)
}

// HasNext reports whether another page is available.
func (p *Page[T]) HasNext() bool { return p != nil && p.Next != nil }

// NextPage fetches the page after this one, or returns nil when there is none.
func (p *Page[T]) NextPage(ctx context.Context) (*Page[T], error) {
	if p == nil || p.Next == nil || p.fetch == nil {
		return nil, nil
	}
	env, err := p.fetch(ctx, *p.Next)
	if err != nil {
		return nil, err
	}
	return newPage(env, p.fetch), nil
}

// AutoPaging walks the remaining pages and calls visit for each item.
// Returning an error from visit stops the walk and surfaces that error.
// MaxPages and MaxItems bound how far it goes.
func (p *Page[T]) AutoPaging(ctx context.Context, visit func(item T) error, opts ...PageOption) error {
	limits, err := limitsFrom(opts)
	if err != nil {
		return err
	}
	seenPages, seenItems := 0, 0
	for current := p; current != nil; {
		for _, item := range current.Results {
			if err := visit(item); err != nil {
				return err
			}
			seenItems++
			if limits.maxItems > 0 && seenItems >= limits.maxItems {
				return nil
			}
		}
		seenPages++
		if limits.maxPages > 0 && seenPages >= limits.maxPages {
			return nil
		}
		next, err := current.NextPage(ctx)
		if err != nil {
			return err
		}
		current = next
	}
	return nil
}

// All ranges over the remaining items, yielding the error that ended the walk
// as the second value. Stop early by breaking out of the loop.
//
//	for item, err := range page.All(ctx, zelf.MaxItems(100)) {
//	    if err != nil { return err }
//	    ...
//	}
func (p *Page[T]) All(ctx context.Context, opts ...PageOption) iter.Seq2[T, error] {
	return func(yield func(T, error) bool) {
		var zero T
		limits, err := limitsFrom(opts)
		if err != nil {
			yield(zero, err)
			return
		}
		seenPages, seenItems := 0, 0
		for current := p; current != nil; {
			for _, item := range current.Results {
				if !yield(item, nil) {
					return
				}
				seenItems++
				if limits.maxItems > 0 && seenItems >= limits.maxItems {
					return
				}
			}
			seenPages++
			if limits.maxPages > 0 && seenPages >= limits.maxPages {
				return
			}
			next, err := current.NextPage(ctx)
			if err != nil {
				yield(zero, err)
				return
			}
			current = next
		}
	}
}

func newPage[T any](env *envelope[T], fetch func(ctx context.Context, page int) (*envelope[T], error)) *Page[T] {
	return &Page[T]{
		Results:        env.Results,
		LogID:          env.LogID,
		Page:           env.PageNumber,
		ItemCount:      env.ItemCount,
		Next:           env.Next,
		Previous:       env.Previous,
		appliedFilters: env.AppliedFilters,
		fetch:          fetch,
	}
}

// one takes the single row out of the envelope. Reads that match nothing come
// back as 200 with an empty results array rather than a 404, so the empty case
// becomes a not-found error.
func one[T any](env *envelope[T], what string) (*T, error) {
	if len(env.Results) == 0 {
		return nil, &APIError{
			Status:  http.StatusNotFound,
			Code:    "NOT_FOUND",
			Message: "No " + what + " matched the request.",
			LogID:   env.LogID,
		}
	}
	return &env.Results[0], nil
}
