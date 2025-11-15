package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
)

func main() {
	base := os.Getenv("TRACKIO_SERVER_URL")
	if base == "" {
		base = "https://vaibhav2507-trackio-dashboard.hf.space"
	}
	base = strings.TrimRight(base, "/")

	hfToken := os.Getenv("HF_TOKEN")
	if hfToken == "" {
		log.Fatal("HF_TOKEN env var is required (write token for your Space)")
	}

	// This matches the Trackio bulk_log schema in your /config:
	// items: { project, run, metrics, step, config }
	logs := []map[string]interface{}{
		{
			"project": "go-quickstart",
			"run":     "go-run-1",
			"metrics": map[string]float64{"loss": 0.5, "acc": 0.80},
			"step":    0,
			"config":  nil,
		},
		{
			"project": "go-quickstart",
			"run":     "go-run-1",
			"metrics": map[string]float64{"loss": 0.4, "acc": 0.82},
			"step":    1,
			"config":  nil,
		},
	}

	// SimplePredictBody: { "data": [ logs, hf_token ] }
	body := map[string]interface{}{
		"data": []interface{}{logs, hfToken},
	}

	buf, err := json.Marshal(body)
	if err != nil {
		log.Fatalf("marshal body: %v", err)
	}

	url := base + "/gradio_api/call/bulk_log"
	fmt.Println("* POST", url)

	req, err := http.NewRequest("POST", url, bytes.NewReader(buf))
	if err != nil {
		log.Fatalf("new request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Fatalf("do request: %v", err)
	}
	defer resp.Body.Close()

	fmt.Println("status:", resp.Status)
	var respBody map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respBody); err != nil {
		fmt.Println("could not decode response JSON (maybe empty):", err)
	} else {
		b, _ := json.MarshalIndent(respBody, "", "  ")
		fmt.Println(string(b))
	}

	fmt.Printf("* If status is 200, open %s/?selected_project=go-quickstart in your browser.\n", base)
}
