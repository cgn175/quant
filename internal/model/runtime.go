package model

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	ort "github.com/yalue/onnxruntime_go"
	"github.com/rs/zerolog/log"
)

var initialized bool

func Initialize(sharedLibPath string) error {
	if initialized {
		return nil
	}

	if sharedLibPath == "" {
		sharedLibPath = findSharedLibrary()
	}

	if sharedLibPath != "" {
		ort.SetSharedLibraryPath(sharedLibPath)
	}

	if err := ort.InitializeEnvironment(); err != nil {
		return fmt.Errorf("failed to initialize onnxruntime: %w", err)
	}

	initialized = true
	log.Info().Str("library", sharedLibPath).Msg("onnxruntime initialized")
	return nil
}

func Shutdown() error {
	if !initialized {
		return nil
	}
	if err := ort.DestroyEnvironment(); err != nil {
		return err
	}
	initialized = false
	return nil
}

func findSharedLibrary() string {
	var libName string
	switch runtime.GOOS {
	case "windows":
		libName = "onnxruntime.dll"
	case "darwin":
		libName = "libonnxruntime.dylib"
	default:
		libName = "libonnxruntime.so"
	}

	searchPaths := []string{
		libName,
		filepath.Join(".", libName),
		filepath.Join("/usr/local/lib", libName),
		filepath.Join("/usr/lib", libName),
	}

	if runtime.GOOS == "darwin" {
		searchPaths = append(searchPaths,
			filepath.Join("/opt/homebrew/lib", libName),
			filepath.Join("/usr/local/opt/onnxruntime/lib", libName),
		)
	}

	for _, p := range searchPaths {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	return ""
}
