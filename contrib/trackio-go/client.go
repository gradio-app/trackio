package trackio

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

type Client struct {
	baseURL    string
	project    string
	run        string
	writeToken string
	http       *http.Client
	batcher    *batcher
}

type Option func(*Client)

func WithBaseURL(u string) Option    { return func(c *Client) { c.baseURL = u } }
func WithProject(p string) Option    { return func(c *Client) { c.project = p } }
func WithRun(r string) Option        { return func(c *Client) { c.run = r } }
func WithHTTP(h *http.Client) Option { return func(c *Client) { c.http = h } }
func WithTimeout(d time.Duration) Option {
	return func(c *Client) {
		if c.http == nil {
			c.http = &http.Client{}
		}
		c.http.Timeout = d
	}
}
func WithWriteToken(tok string) Option { return func(c *Client) { c.writeToken = tok } }

func New(opts ...Option) *Client {
	c := &Client{
		baseURL:    getenv("TRACKIO_SERVER_URL", "http://127.0.0.1:7860"),
		project:    os.Getenv("TRACKIO_PROJECT"),
		run:        os.Getenv("TRACKIO_RUN"),
		writeToken: os.Getenv("TRACKIO_WRITE_TOKEN"),
		http:       &http.Client{Timeout: 5 * time.Second},
	}
	for _, opt := range opts {
		opt(c)
	}
	c.batcher = newBatcher(c)
	return c
}

func (c *Client) Log(metrics map[string]any, step *int, ts string) {
	c.batcher.enqueue(LogItem{Timestamp: ts, Step: step, Metrics: metrics})
}

func (c *Client) Flush(ctx context.Context) error {
	return c.batcher.flush(ctx)
}

// Close flushes outstanding logs with a short background timeout.
// Safe to use as `defer client.Close()`.
func (c *Client) Close() error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	return c.Flush(ctx)
}

// postJSON sends JSON to baseURL+path and returns a verbose error on non-2xx.
func (c *Client) tryPost(ctx context.Context, path string, payload any) error {
	url := c.baseURL + path
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	do := func(u string) (*http.Response, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(b))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		if c.writeToken != "" {
			req.Header.Set("X-Trackio-Write-Token", c.writeToken)
		}
		return c.http.Do(req)
	}

	// first attempt
	resp, err := do(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	// handle redirect-on-POST (preserve method & body)
	if resp.StatusCode == http.StatusMovedPermanently || // 301
		resp.StatusCode == http.StatusFound || // 302
		resp.StatusCode == http.StatusSeeOther || // 303
		resp.StatusCode == http.StatusTemporaryRedirect || // 307
		resp.StatusCode == http.StatusPermanentRedirect { // 308

		loc := resp.Header.Get("Location")
		if loc != "" {
			// one re-post to the redirected location
			resp.Body.Close()
			resp2, err2 := do(loc)
			if err2 != nil {
				return err2
			}
			defer resp2.Body.Close()
			if resp2.StatusCode >= 300 {
				body, _ := io.ReadAll(resp2.Body)
				return fmt.Errorf("POST %s -> %s; body: %s", loc, resp2.Status, string(body))
			}
			return nil
		}
	}

	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("POST %s -> %s; body: %s", url, resp.Status, string(body))
	}
	return nil
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
