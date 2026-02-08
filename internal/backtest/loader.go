package backtest

import (
	"encoding/csv"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// LoadCSV loads OHLCV data from a CSV file and returns the symbol and bars
// Expected CSV format: timestamp,open,high,low,close,volume
func LoadCSV(path string) (string, []*Bar, error) {
	// Extract symbol from filename (e.g., BTC_USDT_1m_365d.csv -> BTC/USDT)
	filename := filepath.Base(path)
	parts := strings.Split(filename, "_")
	if len(parts) < 2 {
		return "", nil, fmt.Errorf("invalid filename format: %s", filename)
	}
	symbol := parts[0] + "/" + parts[1]

	// Open CSV file
	file, err := os.Open(path)
	if err != nil {
		return "", nil, fmt.Errorf("failed to open CSV: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)

	// Read header
	_, err = reader.Read()
	if err != nil {
		return "", nil, fmt.Errorf("failed to read header: %w", err)
	}

	// Read all records
	records, err := reader.ReadAll()
	if err != nil {
		return "", nil, fmt.Errorf("failed to read CSV: %w", err)
	}

	bars := make([]*Bar, 0, len(records))

	for i, record := range records {
		if len(record) < 6 {
			return "", nil, fmt.Errorf("invalid record at line %d: expected 6 fields, got %d", i+2, len(record))
		}

		// Parse timestamp (format: 2024-01-01 00:00:00 or Unix timestamp)
		var timestamp time.Time
		if ts, err := strconv.ParseInt(record[0], 10, 64); err == nil {
			// Unix millisecond timestamp
			timestamp = time.UnixMilli(ts)
		} else {
			// Try parsing as datetime string
			timestamp, err = time.Parse("2006-01-02 15:04:05", record[0])
			if err != nil {
				// Try ISO format
				timestamp, err = time.Parse(time.RFC3339, record[0])
				if err != nil {
					return "", nil, fmt.Errorf("failed to parse timestamp at line %d: %w", i+2, err)
				}
			}
		}

		open, err := strconv.ParseFloat(record[1], 64)
		if err != nil {
			return "", nil, fmt.Errorf("failed to parse open at line %d: %w", i+2, err)
		}

		high, err := strconv.ParseFloat(record[2], 64)
		if err != nil {
			return "", nil, fmt.Errorf("failed to parse high at line %d: %w", i+2, err)
		}

		low, err := strconv.ParseFloat(record[3], 64)
		if err != nil {
			return "", nil, fmt.Errorf("failed to parse low at line %d: %w", i+2, err)
		}

		close, err := strconv.ParseFloat(record[4], 64)
		if err != nil {
			return "", nil, fmt.Errorf("failed to parse close at line %d: %w", i+2, err)
		}

		volume, err := strconv.ParseFloat(record[5], 64)
		if err != nil {
			return "", nil, fmt.Errorf("failed to parse volume at line %d: %w", i+2, err)
		}

		bar := &Bar{
			Symbol:    symbol,
			Timestamp: timestamp,
			Open:      open,
			High:      high,
			Low:       low,
			Close:     close,
			Volume:    volume,
		}
		bars = append(bars, bar)
	}

	return symbol, bars, nil
}
