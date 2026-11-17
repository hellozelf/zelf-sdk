package openapi

import (
	"bytes"
	"encoding/json"
	"math"
)

// Int is a whole number inside a downloaded report. It reads null as 0 and a
// decimal as the nearest whole number, so a report never fails to decode.
type Int int64

// UnmarshalJSON accepts a whole number, a decimal or null.
func (n *Int) UnmarshalJSON(data []byte) error {
	if bytes.Equal(data, []byte("null")) {
		*n = 0
		return nil
	}
	var whole int64
	if err := json.Unmarshal(data, &whole); err == nil {
		*n = Int(whole)
		return nil
	}
	var decimal float64
	if err := json.Unmarshal(data, &decimal); err != nil {
		return err
	}
	*n = Int(math.Round(decimal))
	return nil
}
