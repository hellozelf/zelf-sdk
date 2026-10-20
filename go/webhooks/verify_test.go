package webhooks

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"testing"
	"time"
)

const secret = "whsec_abcdef0123456789"

var body = []byte(`{"id":"whd_1","type":"content.snapshot"}`)

// sign mirrors the signing scheme the API documents.
func sign(payload []byte, key string, timestamp int64) string {
	mac := hmac.New(sha256.New, []byte(key))
	mac.Write(append([]byte(fmt.Sprintf("%d.", timestamp)), payload...))
	return fmt.Sprintf("t=%d,v1=%s", timestamp, hex.EncodeToString(mac.Sum(nil)))
}

func TestAGenuineDeliveryVerifies(t *testing.T) {
	now := time.Now()
	payload, err := Verify(body, sign(body, secret, now.Unix()), []string{secret}, Options{Now: now})
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if payload["id"] != "whd_1" {
		t.Fatalf("payload = %v", payload)
	}
}

func TestAForgedSignatureIsRejected(t *testing.T) {
	now := time.Now()
	_, err := Verify(body, sign(body, "whsec_wrong", now.Unix()), []string{secret}, Options{Now: now})
	if !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestATamperedBodyIsRejected(t *testing.T) {
	now := time.Now()
	signature := sign(body, secret, now.Unix())
	if _, err := Verify(append(body, ' '), signature, []string{secret}, Options{Now: now}); !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestAnOldDeliveryIsRejectedAsAReplay(t *testing.T) {
	stale := time.Now().Add(-2 * time.Hour)
	if _, err := Verify(body, sign(body, secret, stale.Unix()), []string{secret}, Options{}); !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestAFutureTimestampIsAlsoRejected(t *testing.T) {
	ahead := time.Now().Add(2 * time.Hour)
	if _, err := Verify(body, sign(body, secret, ahead.Unix()), []string{secret}, Options{}); !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}

func TestEitherSecretVerifiesDuringARotation(t *testing.T) {
	now := time.Now()
	signature := sign(body, "whsec_new", now.Unix())
	if _, err := Verify(body, signature, []string{"whsec_old", "whsec_new"}, Options{Now: now}); err != nil {
		t.Fatalf("Verify: %v", err)
	}
}

func TestAMissingOrMalformedHeaderIsRejected(t *testing.T) {
	for _, signature := range []string{"", "garbage", "t=abc,v1=ff", "v1=ff", "t=1718000000"} {
		if _, err := Verify(body, signature, []string{secret}, Options{}); !errors.Is(err, ErrVerification) {
			t.Errorf("signature %q: expected ErrVerification, got %v", signature, err)
		}
	}
}

func TestNoSecretIsAProgrammingError(t *testing.T) {
	now := time.Now()
	_, err := Verify(body, sign(body, secret, now.Unix()), nil, Options{Now: now})
	if err == nil || errors.Is(err, ErrVerification) {
		t.Fatalf("expected a configuration error, got %v", err)
	}
}

func TestANonJSONBodyIsRejectedAfterTheSignatureChecksOut(t *testing.T) {
	now := time.Now()
	payload := []byte("not json")
	if _, err := Verify(payload, sign(payload, secret, now.Unix()), []string{secret}, Options{Now: now}); !errors.Is(err, ErrVerification) {
		t.Fatalf("expected ErrVerification, got %v", err)
	}
}
