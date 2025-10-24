package trackio

// backoff.go
//
// withBackoff retries fn with exponential backoff and jitter.
// Currently unused, but planned for retry logic in postJSON / batcher.flush().

import (
	"math/rand"
	"time"
)

func withBackoff(fn func() error, maxRetries int) error {
	var err error
	base := 50 * time.Millisecond
	for i := 0; i <= maxRetries; i++ {
		err = fn()
		if err == nil {
			return nil
		}
		d := base * time.Duration(1<<i)
		jitter := time.Duration(rand.Int63n(int64(d / 2)))
		time.Sleep(d/2 + jitter)
	}
	return err
}
