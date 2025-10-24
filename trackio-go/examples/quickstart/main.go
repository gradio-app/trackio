package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	trackio "github.com/gradio-app/trackio/trackio-go"
)

func waitForAPI(base string, deadline time.Duration) (string, error) {
	dead := time.Now().Add(deadline)
	for {
		resp, err := http.Get(base + "/api/projects")
		if err == nil && resp != nil && resp.StatusCode >= 200 && resp.StatusCode < 400 {
			resp.Body.Close()
			return "/api/projects", nil
		}
		if resp != nil {
			resp.Body.Close()
		}
		if time.Now().After(dead) {
			return "", fmt.Errorf("no Trackio API found at %s", base)
		}
		time.Sleep(150 * time.Millisecond)
	}
}

func main() {
	base := os.Getenv("TRACKIO_SERVER_URL")
	if base == "" {
		base = "http://127.0.0.1:7860"
	}
	fmt.Println("* Waiting for Trackio server at:", base)
	path, err := waitForAPI(base, 5*time.Second)
	if err != nil {
		log.Fatalf(`Trackio API not reachable at %s: %v
Start Trackio with:
  export TRACKIO_SHOW_API=1
  python -c "import trackio; trackio.init(project='go-quickstart', embed=False); import time; time.sleep(9999)"
`, base, err)
	}
	fmt.Println("* Trackio REST detected at:", base+path)

	// Build client
	c := trackio.New(
		trackio.WithBaseURL(base),
		trackio.WithProject("go-quickstart"),
		trackio.WithRun("go-run-1"),
	)

	// Log a couple of points (aligns with your curl)
	fmt.Println("* Logging sample metrics to:", base)
	s0 := 0
	c.Log(map[string]any{"loss": 0.5, "acc": 0.80}, &s0, "")
	s1 := 1
	c.Log(map[string]any{"loss": 0.4, "acc": 0.82}, &s1, "")

	// Flush
	fmt.Println("* Flushing logs...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Flush(ctx); err != nil {
		log.Fatalf("flush error: %v", err)
	}
	fmt.Println("* Done. Check the Trackio dashboard.")
}
