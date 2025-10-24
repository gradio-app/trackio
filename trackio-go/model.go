package trackio

type bulkLogPayload struct {
	Project     string           `json:"project"`
	Run         string           `json:"run"`
	MetricsList []map[string]any `json:"metrics_list"`
	Steps       []int            `json:"steps,omitempty"`
	Timestamps  []string         `json:"timestamps,omitempty"`
	Config      map[string]any   `json:"config,omitempty"`
}

type LogItem struct {
	Timestamp string         `json:"timestamp"`
	Step      *int           `json:"step,omitempty"`
	Metrics   map[string]any `json:"metrics"`
}

type BulkLogRequest struct {
	Project string         `json:"project"`
	Run     string         `json:"run"`
	Items   []LogItem      `json:"items"`
	Config  map[string]any `json:"config,omitempty"`
}

type OkResponse struct {
	Ok bool `json:"ok"`
}
