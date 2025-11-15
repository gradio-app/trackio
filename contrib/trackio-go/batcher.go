package trackio

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"sync"
	"time"
)

type batcher struct {
	c        *Client
	mu       sync.Mutex
	buf      []LogItem
	maxBatch int
	ticker   *time.Ticker
	stopped  chan struct{}
}

func newBatcher(c *Client) *batcher {
	max := envInt("TRACKIO_MAX_BATCH", 128)
	interval := time.Duration(envInt("TRACKIO_FLUSH_INTERVAL_MS", 200)) * time.Millisecond
	b := &batcher{
		c:        c,
		maxBatch: max,
		ticker:   time.NewTicker(interval),
		stopped:  make(chan struct{}),
	}
	go b.loop()
	return b
}

func (b *batcher) loop() {
	for {
		select {
		case <-b.ticker.C:
			_ = b.flush(context.Background())
		case <-b.stopped:
			return
		}
	}
}

func (b *batcher) enqueue(it LogItem) {
	b.mu.Lock()
	b.buf = append(b.buf, it)
	shouldFlush := len(b.buf) >= b.maxBatch
	b.mu.Unlock()
	if shouldFlush {
		_ = b.flush(context.Background())
	}
}

func (b *batcher) flush(ctx context.Context) error {
	b.mu.Lock()
	items := b.buf
	b.buf = nil
	b.mu.Unlock()

	if len(items) == 0 {
		return nil
	}

	metricsList := make([]map[string]any, 0, len(items))
	steps := make([]int, 0, len(items))
	timestamps := make([]string, 0, len(items))

	for _, it := range items {
		if it.Metrics == nil {
			it.Metrics = map[string]any{}
		}
		metricsList = append(metricsList, it.Metrics)

		if it.Step != nil {
			steps = append(steps, *it.Step)
		} else {
			// keep step vector aligned; use -1 as "unset"
			steps = append(steps, -1)
		}

		if it.Timestamp == "" {
			timestamps = append(timestamps, "")
		} else {
			timestamps = append(timestamps, it.Timestamp)
		}
	}

	payload := bulkLogPayload{
		Project:     b.c.project,
		Run:         b.c.run,
		MetricsList: metricsList,
		Steps:       steps,
		Timestamps:  timestamps,
		// Config:    nil, // set if you want to send config once
	}

	// Try modern REST route first, then legacy gradio route
	if err := b.c.tryPost(ctx, "/api/bulk_log", payload); err == nil {
		return nil
	}
	if err := b.c.tryPost(ctx, "/gradio_api/bulk_log", payload); err == nil {
		return nil
	}
	return fmt.Errorf("trackio: unable to POST to either /api/bulk_log or /gradio_api/bulk_log")
}

func envInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
