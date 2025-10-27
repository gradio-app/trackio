package trackio

import (
	"context"
	"testing"
)

func TestClientFlushNoServer(t *testing.T) {
	// Use a port where no Trackio server is running
	c := New(
		WithBaseURL("http://127.0.0.1:9999"),
		WithProject("test"),
		WithRun("run1"),
	)

	// Enqueue one fake metric so Flush() actually attempts a POST
	step := 0
	c.Log(map[string]any{"loss": 0.1}, &step, "")

	err := c.Flush(context.Background())
	if err == nil {
		t.Fatal("expected connection error when no server is running, got nil")
	}
	t.Logf("got expected error: %v", err)
}
