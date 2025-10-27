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
func (c *Client) postJSON(ctx context.Context, path string, payload any) error {
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	// If you later secure the API with a cookie or header:
	// if c.writeToken != "" { req.AddCookie(&http.Cookie{Name:"trackio_write_token", Value:c.writeToken}) }

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("POST %s -> %s; body: %s", path, resp.Status, string(body))
	}
	return nil
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
