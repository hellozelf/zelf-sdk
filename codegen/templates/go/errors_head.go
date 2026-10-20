package zelf

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
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

func (e *APIError) Error() string {
	out := "zelf: " + strconv.Itoa(e.Status)
	if e.Code != "" {
		out += " " + e.Code
	}
	out += ": " + e.Message
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
		Message: fmt.Sprintf("HTTP %d from the ZelfAI API", resp.StatusCode),
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
