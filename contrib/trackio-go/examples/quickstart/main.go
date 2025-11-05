// examples/quickstart/main.go
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	trackio "github.com/gradio-app/trackio/contrib/trackio-go"
)

func waitForAPI(base string, deadline time.Duration) (string, error) {
	fmt.Println("* Waiting for Trackio server at:", base)
	dead := time.Now().Add(deadline)

	// Probe a few candidates (in order of preference)
	candidates := []string{
		"/api/projects",                // FastAPI shim (when TRACKIO_SHOW_API=1)
		"/gradio_api/get_all_projects", // Gradio auto route (registered via gr.api)
		"/",                            // UI root: indicates app is up (last resort)
	}

	for time.Now().Before(dead) {
		for _, ep := range candidates {
			u := base + ep
			resp, err := http.Get(u)
			if err == nil && resp != nil {
				code := resp.StatusCode
				resp.Body.Close()
				// Treat any non-5xx as "up"
				if code >= 200 && code < 500 {
					return ep, nil
				}
			}
		}
		time.Sleep(200 * time.Millisecond)
	}
	return "", fmt.Errorf("no Trackio API found at %s", base)
}

func main() {
	base := os.Getenv("TRACKIO_SERVER_URL")
	if base == "" {
		base = "http://127.0.0.1:7860"
	}

	path, err := waitForAPI(base, 8*time.Second)
	if err != nil {
		log.Fatalf(`Trackio API not reachable at %s: %v
Start Trackio locally with:
  export TRACKIO_SHOW_API=1
  python -c "import trackio; trackio.init(project='go-quickstart', embed=False); import time; time.sleep(9999)"
`, base, err)
	}
	fmt.Println("* Trackio REST detected at:", base+path)

	// Build client (envs can also be used: TRACKIO_PROJECT / TRACKIO_RUN)
	c := trackio.New(
		trackio.WithBaseURL(base),
		trackio.WithProject("go-quickstart"),
		trackio.WithRun("go-run-1"),
	)

	// Log a couple of points (matches curl example)
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
