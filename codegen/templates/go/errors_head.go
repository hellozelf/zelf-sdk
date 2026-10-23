package zelf

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"
)

// ConnectionError wraps a transport failure: the request never produced an
// HTTP response.
type ConnectionError struct{ Err error }

func (e *ConnectionError) Error() string { return "zelf: could not reach the API: " + e.Err.Error() }
func (e *ConnectionError) Unwrap() error { return e.Err }

// APIError is an error response from the API. Status, Code, and LogID come
// straight from the response envelope.
type APIError struct {
	Status  int
	Code    string
	Message string
	Details map[string]any
	LogID   string
}

// RenderDetails gives the field-level reasons the API sent as one readable
// clause, with the fields in a stable order.
func RenderDetails(details map[string]any) string {
	if len(details) == 0 {
		return ""
	}
	fields := make([]string, 0, len(details))
	for field := range details {
		fields = append(fields, field)
	}
	sort.Strings(fields)
	parts := make([]string, 0, len(fields))
	for _, field := range fields {
		parts = append(parts, field+": "+joinReasons(details[field]))
	}
	return strings.Join(parts, " ")
}

func joinReasons(value any) string {
	list, ok := value.([]any)
	if !ok {
		return fmt.Sprint(value)
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		out = append(out, fmt.Sprint(item))
	}
	return strings.Join(out, " ")
}

func (e *APIError) Error() string {
	out := "zelf: " + strconv.Itoa(e.Status)
	if e.Code != "" {
		out += " " + e.Code
	}
	out += ": " + e.Message
	// The message alone says a request was refused but never which field or
	// which limit, and that is the part a caller can act on.
	if detail := RenderDetails(e.Details); detail != "" {
		out += " " + detail
	}
	if e.LogID != "" {
		out += " (log_id=" + e.LogID + ")"
	}
	return out
}

type errorBody struct {
	LogID string `json:"log_id"`
	Error struct {
		Code    string         `json:"code"`
		Message string         `json:"message"`
		Details map[string]any `json:"details"`
	} `json:"error"`
}

func readAPIError(resp *http.Response) error {
	defer drain(resp)
	out := &APIError{
		Status:  resp.StatusCode,
		Message: fmt.Sprintf("HTTP %d from the Zelf API", resp.StatusCode),
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))
	if err != nil {
		return out
	}
	var parsed errorBody
	if json.Unmarshal(body, &parsed) == nil && parsed.Error.Code != "" {
		out.Code = parsed.Error.Code
		out.LogID = parsed.LogID
		out.Details = parsed.Error.Details
		if parsed.Error.Message != "" {
			out.Message = parsed.Error.Message
		}
	}
	return out
}
